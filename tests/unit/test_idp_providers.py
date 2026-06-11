"""Q12 (Day 13F) — unit tests for the OIDC / SAML provider stubs + the
provider-agnostic CSRF (state) and replay stores in auth.py.

These exercise the validation logic in isolation (no FastAPI), so a failure
points straight at the provider rather than the route wiring.
"""

from __future__ import annotations

import subprocess
import time
import uuid

import pytest

from backend.gateway import auth as auth_mod
from backend.gateway.auth import (
    IdpError,
    StubOIDCProvider,
    StubSAMLProvider,
    _resolve_idp_user,
)
from backend.shared.config import settings
from backend.shared.models import UserRole


@pytest.fixture(autouse=True)
def _reset_idp_state():
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    yield
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()


# ---------------------------------------------------------------------------
# OIDC provider
# ---------------------------------------------------------------------------
def _oidc_provider() -> StubOIDCProvider:
    return StubOIDCProvider(
        settings.OIDC_STUB_SIGNING_SECRET,
        issuer=settings.OIDC_ISSUER,
        audience=settings.OIDC_CLIENT_ID,
    )


def test_oidc_roundtrip_ok():
    code = StubOIDCProvider.mint_code(
        settings.OIDC_STUB_SIGNING_SECRET,
        sub="alice",
        iss=settings.OIDC_ISSUER,
        aud=settings.OIDC_CLIENT_ID,
        nonce="n1",
        exp=int(time.time()) + 60,
    )
    identity = _oidc_provider().exchange_code(code, "n1")
    assert identity.subject == "alice"
    assert identity.issuer == settings.OIDC_ISSUER


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param({"iss": "evil"}, id="wrong-issuer"),
        pytest.param({"aud": "wrong-client"}, id="wrong-audience"),
    ],
)
def test_oidc_pinning_rejections(mutate):
    base = dict(
        sub="alice",
        iss=settings.OIDC_ISSUER,
        aud=settings.OIDC_CLIENT_ID,
        nonce="n1",
        exp=int(time.time()) + 60,
    )
    base.update(mutate)
    code = StubOIDCProvider.mint_code(settings.OIDC_STUB_SIGNING_SECRET, **base)
    with pytest.raises(IdpError):
        _oidc_provider().exchange_code(code, "n1")


def test_oidc_nonce_mismatch_raises():
    code = StubOIDCProvider.mint_code(
        settings.OIDC_STUB_SIGNING_SECRET,
        sub="alice",
        iss=settings.OIDC_ISSUER,
        aud=settings.OIDC_CLIENT_ID,
        nonce="real-nonce",
        exp=int(time.time()) + 60,
    )
    with pytest.raises(IdpError):
        _oidc_provider().exchange_code(code, "attacker-nonce")


def test_oidc_clock_skew_tolerated(monkeypatch):
    """An ID token that expired a few seconds ago is still accepted within the
    clock-skew window (NTP drift), but not beyond it."""
    monkeypatch.setattr(settings, "IDP_CLOCK_SKEW_SEC", 30)
    code = StubOIDCProvider.mint_code(
        settings.OIDC_STUB_SIGNING_SECRET,
        sub="alice",
        iss=settings.OIDC_ISSUER,
        aud=settings.OIDC_CLIENT_ID,
        nonce="n",
        exp=int(time.time()) - 5,  # expired 5s ago, within 30s skew
    )
    # Within skew -> accepted.
    assert _oidc_provider().exchange_code(code, "n").subject == "alice"


# ---------------------------------------------------------------------------
# OIDC state store (CSRF)
# ---------------------------------------------------------------------------
def test_oidc_state_is_single_use_and_unguessable():
    state, nonce = auth_mod.begin_oidc_login()
    assert len(state) >= 16 and len(nonce) >= 16  # unguessable
    assert auth_mod.consume_oidc_state(state) == nonce
    # Second consume -> CSRF / replay error.
    with pytest.raises(IdpError):
        auth_mod.consume_oidc_state(state)


def test_oidc_unknown_state_raises():
    with pytest.raises(IdpError):
        auth_mod.consume_oidc_state("never-minted")


def test_oidc_missing_state_raises():
    with pytest.raises(IdpError):
        auth_mod.consume_oidc_state(None)


# ---------------------------------------------------------------------------
# SAML provider
# ---------------------------------------------------------------------------
def _saml_provider() -> StubSAMLProvider:
    return StubSAMLProvider(settings.SAML_STUB_SIGNING_SECRET, audience=settings.SAML_AUDIENCE)


def _mint_saml(**overrides):
    now = int(time.time())
    base = dict(
        assertion_id=str(uuid.uuid4()),
        subject="alice",
        issuer="idp",
        audience=settings.SAML_AUDIENCE,
        not_before=now - 30,
        not_on_or_after=now + 300,
    )
    base.update(overrides)
    return StubSAMLProvider.mint_assertion(settings.SAML_STUB_SIGNING_SECRET, **base)


def test_saml_roundtrip_ok():
    assertion = _mint_saml()
    identity, aid, noa = _saml_provider().validate_assertion(assertion)
    assert identity.subject == "alice"
    assert aid
    assert noa > time.time()


def test_saml_audience_mismatch_raises():
    assertion = _mint_saml(audience="someone-else")
    with pytest.raises(IdpError):
        _saml_provider().validate_assertion(assertion)


def test_saml_expired_window_raises():
    now = int(time.time())
    assertion = _mint_saml(not_before=now - 600, not_on_or_after=now - 300)
    with pytest.raises(IdpError):
        _saml_provider().validate_assertion(assertion)


def test_saml_replay_store_single_use():
    aid = str(uuid.uuid4())
    noa = int(time.time()) + 300
    assert auth_mod._saml_assertion_seen(aid, noa) is False  # first time
    assert auth_mod._saml_assertion_seen(aid, noa) is True  # replay


# ---------------------------------------------------------------------------
# _resolve_idp_user privilege boundary (shared with the upstream-header path)
# ---------------------------------------------------------------------------
def test_resolve_known_user_pins_role_and_tenant():
    from backend.gateway.auth import IdpIdentity

    user = _resolve_idp_user(
        IdpIdentity(subject="alice", issuer="idp", tenant_hint="tenant_b", role_hint="it_admin")
    )
    assert user.role == UserRole.ATTORNEY  # from _USERS, not the hint
    assert user.tenant_id == "tenant_a"


def test_resolve_unknown_user_cannot_claim_privileged_role():
    from backend.gateway.auth import IdpIdentity

    for bad_role in ("auditor", "it_admin"):
        user = _resolve_idp_user(
            IdpIdentity(subject="eve", issuer="idp", tenant_hint="t", role_hint=bad_role)
        )
        assert user.role == UserRole.PARALEGAL, bad_role


def test_resolve_unknown_user_can_claim_attorney():
    from backend.gateway.auth import IdpIdentity

    user = _resolve_idp_user(
        IdpIdentity(subject="newbie", issuer="idp", tenant_hint="t", role_hint="attorney")
    )
    assert user.role == UserRole.ATTORNEY


# --- Boot guard: stub IdP defaults refused outside mock/test (review P2-5) --


def _boot_subprocess(extra_env_lines: str) -> subprocess.CompletedProcess[str]:
    import sys
    import textwrap
    from pathlib import Path

    script = textwrap.dedent(
        f"""
        import os
        os.environ.pop('PYTEST_CURRENT_TEST', None)
        os.environ['LLM_MODE'] = 'anthropic'
        os.environ['ANTHROPIC_API_KEY'] = 'sk-fake'
        os.environ['JWT_SECRET'] = 'a' * 64
{extra_env_lines}
        import sys
        for mod in [m for m in list(sys.modules) if m.startswith('backend.')]:
            del sys.modules[mod]
        try:
            import backend.shared.config  # noqa: F401
            print('BOOT_OK')
        except RuntimeError as exc:
            print('GUARD_TRIPPED', exc)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def test_stub_idp_published_secret_refuses_non_mock_boot():
    """OIDC/SAML stub providers with the PUBLISHED default signing secrets
    must refuse to boot outside mock/test — anyone reading the repo could
    mint valid IdP assertions."""
    proc = _boot_subprocess("")  # no stub secrets -> published defaults
    assert proc.returncode == 0, proc.stderr
    assert "GUARD_TRIPPED" in proc.stdout, proc.stdout
    assert "OIDC_PROVIDER=stub" in proc.stdout


def test_stub_idp_private_secret_boots_ok():
    proc = _boot_subprocess(
        "        os.environ['OIDC_STUB_SIGNING_SECRET'] = 'private-x'\n"
        "        os.environ['SAML_STUB_SIGNING_SECRET'] = 'private-y'"
    )
    assert proc.returncode == 0, proc.stderr
    assert "BOOT_OK" in proc.stdout, proc.stdout


def test_stub_idp_disabled_boots_ok():
    proc = _boot_subprocess(
        "        os.environ['OIDC_ENABLED'] = 'false'\n        os.environ['SAML_ENABLED'] = 'false'"
    )
    assert proc.returncode == 0, proc.stderr
    assert "BOOT_OK" in proc.stdout, proc.stdout
