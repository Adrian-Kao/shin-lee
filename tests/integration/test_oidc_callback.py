"""Q12 (Day 13F) — OIDC authorization-code callback hardening.

The named ``/v1/auth/oidc/callback`` stub is fleshed out into a testable,
MOCKABLE path. The identity provider is a dependency-injected, offline stub that
HMAC-signs an "authorization code" blob standing in for the real code->token
exchange + ID-token JWKS signature verification. The CSRF (state) + replay
(nonce) guards are provider-agnostic and live in the gateway, so they protect
every backend.

Threat model under test:
  * state is single-use CSRF — a forged callback (no matching state) is 401.
  * state is unguessable + TTL-bounded; a replayed state is 401.
  * nonce binds the ID token to the browser that began the flow — a code whose
    nonce does not match the flow's nonce is 401 (token-injection / replay).
  * issuer / audience pinned — a code from another IdP / for another client 401s.
  * expired code 401s; bad-signature (forged) code 401s.
  * a federated user gets an ordinary, REVOCABLE session JWT.
  * a federated user can NEVER self-assert AUDITOR / IT_ADMIN.
  * a known demo user's role/tenant come from _USERS, never the IdP hint.
  * exactly one audit row; the raw code is never stored.
"""

from __future__ import annotations

import time

import pytest

from backend.gateway import auth as auth_mod
from backend.shared.config import settings


@pytest.fixture(autouse=True)
def _reset_idp_state():
    """Clear OIDC state store + federated registry + login bucket around each
    test so neither this module nor the rest of the suite inherits leaked
    state from the session-scoped gateway app."""
    from backend.gateway import rate_limit as rl

    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()
    yield
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()


def _begin(client) -> tuple[str, str]:
    r = client.get("/v1/auth/oidc/begin")
    assert r.status_code == 200, r.text
    body = r.json()
    return body["state"], body["nonce"]


def _mint_code(*, sub, nonce, iss=None, aud=None, exp=None, tenant=None, role=None) -> str:
    return auth_mod.StubOIDCProvider.mint_code(
        settings.OIDC_STUB_SIGNING_SECRET,
        sub=sub,
        iss=iss if iss is not None else settings.OIDC_ISSUER,
        aud=aud if aud is not None else settings.OIDC_CLIENT_ID,
        nonce=nonce,
        exp=exp if exp is not None else int(time.time()) + 300,
        tenant=tenant,
        role=role,
    )


def _callback(client, code, state):
    return client.post("/v1/auth/oidc/callback", json={"code": code, "state": state})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_oidc_happy_path_known_user_yields_working_session(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    r = _callback(gateway_client, code, state)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "alice"
    # Known user: role + tenant come from _USERS, not from the IdP.
    assert body["role"] == "attorney"
    assert body["tenant_id"] == "tenant_a"
    session_jwt = body["token"]
    # The session JWT works on a protected endpoint.
    resp = gateway_client.get("/v1/quota", headers={"Authorization": f"Bearer {session_jwt}"})
    assert resp.status_code == 200, resp.text


def test_oidc_federated_unknown_user_gets_least_privilege_session(gateway_client):
    state, nonce = _begin(gateway_client)
    # New joiner not in _USERS; the IdP asserts attorney (an allowed role).
    code = _mint_code(sub="ext-joiner", nonce=nonce, tenant="tenant_partner", role="attorney")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "ext-joiner"
    assert body["role"] == "attorney"
    assert body["tenant_id"] == "tenant_partner"
    # The federated session JWT must round-trip through verify_token.
    resp = gateway_client.get("/v1/quota", headers={"Authorization": f"Bearer {body['token']}"})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# CSRF: state
# ---------------------------------------------------------------------------
def test_oidc_callback_without_state_is_rejected(gateway_client):
    _state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    # Forged state never minted by the server.
    r = _callback(gateway_client, code, "forged-state-value")
    assert r.status_code == 401, r.text
    assert "oidc" in r.text.lower() or "failed" in r.text.lower()


def test_oidc_state_is_single_use(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    first = _callback(gateway_client, code, state)
    assert first.status_code == 200, first.text
    # Replaying the same (state, code) must fail — state was consumed.
    second = _callback(gateway_client, code, state)
    assert second.status_code == 401, second.text


def test_oidc_expired_state_is_rejected(gateway_client, monkeypatch):
    # Mint a state, then force it past its TTL by patching the store entry.
    state, nonce = _begin(gateway_client)
    auth_mod._OIDC_STATE_STORE[state] = (nonce, time.time() - 1)
    code = _mint_code(sub="alice", nonce=nonce)
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# nonce binding (replay / token injection)
# ---------------------------------------------------------------------------
def test_oidc_code_with_wrong_nonce_is_rejected(gateway_client):
    state, _nonce = _begin(gateway_client)
    # Attacker's code carries a DIFFERENT nonce than the flow's.
    code = _mint_code(sub="alice", nonce="attacker-supplied-nonce")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# issuer / audience pinning
# ---------------------------------------------------------------------------
def test_oidc_code_from_wrong_issuer_is_rejected(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce, iss="https://evil-idp.example.com")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


def test_oidc_code_for_wrong_audience_is_rejected(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce, aud="some-other-client")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# expiry / forged signature
# ---------------------------------------------------------------------------
def test_oidc_expired_code_is_rejected(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce, exp=int(time.time()) - 120)
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


def test_oidc_code_signed_with_wrong_secret_is_rejected(gateway_client):
    state, nonce = _begin(gateway_client)
    code = auth_mod.StubOIDCProvider.mint_code(
        "the-wrong-secret",
        sub="alice",
        iss=settings.OIDC_ISSUER,
        aud=settings.OIDC_CLIENT_ID,
        nonce=nonce,
        exp=int(time.time()) + 300,
    )
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


def test_oidc_malformed_code_is_rejected(gateway_client):
    state, _nonce = _begin(gateway_client)
    r = _callback(gateway_client, "not-a-dot-delimited-blob", state)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# privilege boundary: federated user cannot self-escalate
# ---------------------------------------------------------------------------
def test_oidc_unknown_user_cannot_claim_auditor(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="eve", nonce=nonce, tenant="tenant_a", role="auditor")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 200, r.text
    # Downgraded to paralegal — auditor cannot come from the IdP for an
    # unknown user. Prove it by the role in the response AND by failing to read
    # the audit log with the issued token.
    assert r.json()["role"] == "paralegal", r.text
    token = r.json()["token"]
    audit = gateway_client.get("/v1/audit/recent", headers={"Authorization": f"Bearer {token}"})
    assert audit.status_code == 403, audit.text


def test_oidc_unknown_user_cannot_claim_it_admin(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="mallory", nonce=nonce, tenant="tenant_a", role="it_admin")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "paralegal", r.text


def test_oidc_known_user_role_pins_to_USERS_not_idp_hint(gateway_client):
    """alice is attorney in _USERS; an IdP claiming it_admin must NOT promote
    her. Also her tenant must stay tenant_a even if the IdP claims tenant_b."""
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce, tenant="tenant_b", role="it_admin")
    r = _callback(gateway_client, code, state)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "attorney", r.text
    assert r.json()["tenant_id"] == "tenant_a", r.text


# ---------------------------------------------------------------------------
# session JWT from OIDC is revocable (shares the H-5 kill switch)
# ---------------------------------------------------------------------------
def test_oidc_session_is_revocable_via_logout(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    token = _callback(gateway_client, code, state).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert gateway_client.get("/v1/quota", headers=auth).status_code == 200
    assert gateway_client.post("/v1/auth/logout", headers=auth).json()["revoked"] is True
    assert gateway_client.get("/v1/quota", headers=auth).status_code == 401


# ---------------------------------------------------------------------------
# feature gate
# ---------------------------------------------------------------------------
def test_oidc_disabled_returns_uniform_401(gateway_client, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_ENABLED", True)
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    monkeypatch.setattr(settings, "OIDC_ENABLED", False)
    r = _callback(gateway_client, code, state)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# audit: exactly one row, raw code never stored
# ---------------------------------------------------------------------------
def _preauth_rows():
    from backend.gateway import audit as audit_mod

    return audit_mod.writer.list_for_tenant("_preauth_", limit=1000)


def test_oidc_callback_writes_exactly_one_audit_row(gateway_client):
    state, nonce = _begin(gateway_client)
    code = _mint_code(sub="alice", nonce=nonce)
    before = len(_preauth_rows())
    _callback(gateway_client, code, state)
    after = _preauth_rows()
    assert len(after) == before + 1
    assert after[0]["endpoint"] == "/v1/auth/oidc/callback"
    # The raw code must never appear in any serialised audit field.
    assert code not in repr(after), "raw OIDC code leaked into audit row"
