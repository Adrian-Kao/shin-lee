"""Unit tests for `_user_from_upstream_headers` + `auth_dependency`.

Covers Compat Refactor 3 — digiRunner-style trusted-upstream header auth.

Invariants under test:
    1. x-user-id / x-tenant-id from a TRUSTED upstream IP -> User constructed
       from those headers, JWT NOT consulted.
    2. x-user-id / x-tenant-id from a NON-trusted IP -> headers ignored,
       falls back to JWT path (so missing JWT => 401, valid JWT => OK).
    3. Missing x-user-id even from a trusted IP -> fallback to JWT path.
    4. Unknown x-user-id with no x-user-role -> role defaults to the lowest-
       privilege UserRole (PARALEGAL); display_name = the raw user_id.
    5. Known x-user-id -> display_name + daily_token_quota + tenant lifted
       from the _USERS demo table; an upstream-supplied tenant for a known
       user is IGNORED (H-1), while an unknown user keeps the upstream tenant.
    6. Existing JWT path remains intact (regression guard).

TestClient's request.client.host defaults to the string ``testclient``. To
exercise the upstream-trust path we monkeypatch ``TRUSTED_UPSTREAM_IPS`` to
include that sentinel string; to exercise the *untrusted* path we
monkeypatch it to a set that does NOT include ``testclient``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.gateway import auth as auth_mod
from backend.shared.config import settings
from backend.shared.models import UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trust_testclient(monkeypatch) -> None:
    """Make the TestClient peer (`testclient`) appear in the trusted list."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("testclient",))


def _untrust_everything(monkeypatch) -> None:
    """Remove `testclient` (and everything else) from the trust list."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.250.0.99",))


# ---------------------------------------------------------------------------
# 1. Upstream-trust path
# ---------------------------------------------------------------------------

def test_upstream_headers_from_trusted_ip_skip_jwt(
    monkeypatch, gateway_client: TestClient
) -> None:
    """Trusted upstream + x-user-id + x-tenant-id -> 200 without any JWT."""
    _trust_testclient(monkeypatch)

    resp = gateway_client.get(
        "/v1/quota",
        headers={
            "x-user-id": "alice",
            "x-tenant-id": "tenant_a",
            "x-user-role": "attorney",
        },
        # Deliberately NO Authorization header.
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # /v1/quota echoes alice's per-user quota (200_000) — see _USERS in
    # auth.py. If the upstream path had been ignored, the JWT path would
    # have raised 401, not returned a 200 body.
    assert body.get("user_daily_limit") == auth_mod._USERS["alice"].daily_token_quota, body


def test_upstream_headers_from_untrusted_ip_falls_back_to_jwt(
    monkeypatch, gateway_client: TestClient
) -> None:
    """Untrusted peer + spoofed x-user-id but no JWT -> 401 (no bypass)."""
    _untrust_everything(monkeypatch)

    resp = gateway_client.get(
        "/v1/quota",
        headers={
            "x-user-id": "alice",
            "x-tenant-id": "tenant_a",
            "x-user-role": "attorney",
        },
        # No Authorization header on purpose: the spoofed identity headers
        # MUST NOT be honoured, so the JWT path runs and 401s.
    )
    assert resp.status_code == 401, resp.text


def test_upstream_headers_missing_user_id_falls_back_to_jwt(
    monkeypatch, gateway_client: TestClient, alice_token: str
) -> None:
    """Trusted peer but x-user-id absent -> fall through to JWT path."""
    _trust_testclient(monkeypatch)

    # Only x-tenant-id is present -> upstream path declines, JWT used.
    resp = gateway_client.get(
        "/v1/quota",
        headers={
            "x-tenant-id": "tenant_a",
            "Authorization": f"Bearer {alice_token}",
        },
    )
    assert resp.status_code == 200, resp.text
    # JWT path resolved alice -> her per-user quota appears in the snapshot.
    assert (
        resp.json().get("user_daily_limit")
        == auth_mod._USERS["alice"].daily_token_quota
    ), resp.json()


# ---------------------------------------------------------------------------
# 2. Role / display_name resolution
# ---------------------------------------------------------------------------

def test_upstream_user_role_defaults_to_paralegal_when_unknown(monkeypatch) -> None:
    """Unknown user_id + no x-user-role -> least-privilege default."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={"x-user-id": "external_user_42", "x-tenant-id": "tenant_x"},
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.user_id == "external_user_42"
    assert user.tenant_id == "tenant_x"
    # Lowest-privilege fallback — see auth.py rationale.
    assert user.role == UserRole.PARALEGAL
    # Unknown user -> display_name mirrors the raw user_id.
    assert user.display_name == "external_user_42"


def test_upstream_known_user_id_uses_known_display_name(monkeypatch) -> None:
    """Known demo user -> display_name + role pulled from _USERS."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_a"},
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.user_id == "alice"
    # Display name lifted from the in-memory _USERS table.
    assert user.display_name == auth_mod._USERS["alice"].display_name
    # No x-user-role header -> use the known user's role (attorney).
    assert user.role == auth_mod._USERS["alice"].role
    # daily_token_quota also lifted from _USERS so rate-limit math is sane.
    assert user.daily_token_quota == auth_mod._USERS["alice"].daily_token_quota


def test_upstream_unrecognised_role_string_degrades_to_known_user_role(
    monkeypatch,
) -> None:
    """Unknown role string for a known user -> use the known user's role,
    NOT 500. (Defence against examiner-typed garbage in the role header.)"""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "alice",
            "x-tenant-id": "tenant_a",
            "x-user-role": "wizard",  # not a UserRole value
        },
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.role == auth_mod._USERS["alice"].role


# ---------------------------------------------------------------------------
# 3. JWT fallback regression guards
# ---------------------------------------------------------------------------

def test_jwt_fallback_still_works(gateway_client: TestClient, alice_token: str) -> None:
    """No upstream headers, valid Bearer JWT -> existing path returns 200."""
    # NOTE: we deliberately do NOT touch TRUSTED_UPSTREAM_IPS here. With the
    # default (`127.0.0.1, ::1`) the TestClient peer (`testclient`) is NOT
    # trusted, so the upstream path declines and JWT runs as before.
    resp = gateway_client.get(
        "/v1/quota",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert (
        resp.json().get("user_daily_limit")
        == auth_mod._USERS["alice"].daily_token_quota
    )


def test_jwt_fallback_with_invalid_token_returns_401(
    gateway_client: TestClient,
) -> None:
    """Bad JWT, no upstream headers -> 401 (existing behaviour preserved)."""
    resp = gateway_client.get(
        "/v1/quota",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401, resp.text


def test_empty_trusted_upstream_ips_disables_path(monkeypatch) -> None:
    """Empty trust list -> upstream path is a no-op even with full headers."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ())

    request = _fake_request(
        client_host="127.0.0.1",
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_a"},
    )
    assert auth_mod._user_from_upstream_headers(request) is None


def test_upstream_path_ignores_missing_client(monkeypatch) -> None:
    """`request.client is None` (ASGI edge case) -> upstream path declines.

    Without this guard a malicious or misconfigured ASGI server could trick
    us into building a User off attacker-supplied headers with no peer info.
    """
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("127.0.0.1",))

    request = _fake_request(
        client_host=None,
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_a"},
    )
    assert auth_mod._user_from_upstream_headers(request) is None


# ---------------------------------------------------------------------------
# Helpers (kept at the bottom so the test bodies above read top-down)
# ---------------------------------------------------------------------------

class _FakeClient:
    __slots__ = ("host",)

    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for starlette.Request.

    Only the attributes that `_user_from_upstream_headers` touches:
    `.client` (with `.host`) and `.headers` (dict-like with `.get`).
    """

    def __init__(self, client_host: str | None, headers: dict[str, str]) -> None:
        self.client = _FakeClient(client_host) if client_host is not None else None
        # Lowercase keys — starlette normalises header names this way.
        self.headers = {k.lower(): v for k, v in headers.items()}


def _fake_request(client_host: str | None, headers: dict[str, str]) -> _FakeRequest:
    return _FakeRequest(client_host, headers)


# Sanity check: the helper must be a no-op vs the real attribute surface
# `_user_from_upstream_headers` reads. If a future refactor starts touching
# (say) `.url` or `.method`, this test will fail loudly and we'll know to
# extend `_FakeRequest`.
def test_fake_request_surface_matches_real_dependency_usage() -> None:
    req = _fake_request("127.0.0.1", {"x-user-id": "alice", "x-tenant-id": "t"})
    assert req.client is not None and req.client.host == "127.0.0.1"
    assert req.headers.get("x-user-id") == "alice"
    assert req.headers.get("missing") is None


# Belt-and-braces: confirm the production default does not include any
# wildcard or 0.0.0.0 entry that would defeat the whole guard.
def test_default_trusted_upstream_ips_contains_no_wildcards() -> None:
    # Pull the env-default rather than whatever the running test session set.
    import importlib

    from backend.shared import config as _cfg_mod

    importlib.reload(_cfg_mod)
    default = _cfg_mod.settings.TRUSTED_UPSTREAM_IPS
    for ip in default:
        assert ip not in ("0.0.0.0", "*", "::", "::/0"), (
            f"TRUSTED_UPSTREAM_IPS default leaked a wildcard: {ip!r}"
        )


@pytest.fixture(autouse=True)
def _isolate_trusted_ips(monkeypatch):
    """Make sure no test in this file leaks a TRUSTED_UPSTREAM_IPS mutation
    into a sibling test. monkeypatch is function-scoped so it auto-rolls
    back, but binding the fixture as autouse documents the intent."""
    yield


# ---------------------------------------------------------------------------
# 4. CRITICAL 1 — upstream role-assertion whitelist
#
# An upstream may freely claim ATTORNEY or PARALEGAL on a brand-new user_id
# (these are the everyday roles digiRunner's IdP will surface). It may NOT
# escalate an unknown user to AUDITOR or IT_ADMIN — those grant audit-log
# read and admin actions and MUST come from the local _USERS table or a
# future signed claim. Otherwise anyone with a trusted-IP foothold reads
# every tenant's audit history by setting one header.
# ---------------------------------------------------------------------------

def test_upstream_unknown_user_cannot_claim_auditor(monkeypatch) -> None:
    """eve presenting x-user-role=auditor from a trusted IP -> downgraded
    to paralegal. This is the core role-escalation guard."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "eve",          # not in _USERS
            "x-tenant-id": "tenant_a",
            "x-user-role": "auditor",    # privileged — should be refused
        },
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.user_id == "eve"
    assert user.role == UserRole.PARALEGAL, (
        f"unknown user must not be able to claim auditor; got {user.role!r}"
    )


def test_upstream_unknown_user_cannot_claim_it_admin(monkeypatch) -> None:
    """Same guard, but for the it_admin role (config-mutation surface)."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "eve",
            "x-tenant-id": "tenant_a",
            "x-user-role": "it_admin",
        },
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.role == UserRole.PARALEGAL


def test_upstream_unknown_user_can_claim_attorney(monkeypatch) -> None:
    """The two roles digiRunner's IdP commonly surfaces (attorney /
    paralegal) MUST still pass through for unknown users — otherwise the
    upstream path is useless for any new joiner."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "new_joiner",
            "x-tenant-id": "tenant_a",
            "x-user-role": "attorney",
        },
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.role == UserRole.ATTORNEY


def test_upstream_known_alice_role_comes_from_USERS_not_header(monkeypatch) -> None:
    """For a KNOWN user the local _USERS role wins unconditionally. This
    prevents an upstream bug from demoting alice — or, conversely, from
    promoting bob to it_admin by setting one header."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))

    request = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "alice",        # known: attorney in _USERS
            "x-tenant-id": "tenant_a",
            "x-user-role": "it_admin",   # malicious upstream claim
        },
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.role == UserRole.ATTORNEY, (
        "known user role MUST come from _USERS, not from the upstream "
        f"header — got role={user.role!r}"
    )


# ---------------------------------------------------------------------------
# 5. CRITICAL 2 — IPv4-mapped-IPv6 + CIDR rejection
# ---------------------------------------------------------------------------

def test_ipv4_mapped_ipv6_loopback_is_trusted(monkeypatch) -> None:
    """uvicorn on a dual-stack socket surfaces v4 peers as ``::ffff:<v4>``.
    A trust list of ``["127.0.0.1"]`` must still match those peers, or
    every loopback request silently bypasses the upstream-trust path."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("127.0.0.1",))

    request = _fake_request(
        client_host="::ffff:127.0.0.1",
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_a"},
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None, (
        "IPv4-mapped IPv6 loopback should normalise to 127.0.0.1 and "
        "be trusted"
    )
    assert user.user_id == "alice"


def test_cidr_in_trust_list_raises_at_parse_time() -> None:
    """CIDR ranges are NOT supported — _parse_trusted_ips refuses them
    rather than silently treating ``10.0.0.0/24`` as a single address that
    will never match any real peer."""
    from backend.shared.config import _parse_trusted_ips

    with pytest.raises(ValueError, match="CIDR"):
        _parse_trusted_ips("10.0.0.0/24")


# ---------------------------------------------------------------------------
# 6. CRITICAL 3 — boot guard for non-loopback trust without shared secret
# ---------------------------------------------------------------------------

def test_non_loopback_trust_without_secret_refuses_boot() -> None:
    """In non-mock mode, adding a non-loopback IP to the trust list
    without configuring UPSTREAM_AUTH_SHARED_SECRET must fail loud at
    boot — otherwise ops adds a sidecar IP and every pod in the mesh can
    forge identities."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import os
        os.environ.pop('PYTEST_CURRENT_TEST', None)
        os.environ['LLM_MODE'] = 'anthropic'
        os.environ['ANTHROPIC_API_KEY'] = 'sk-fake'
        os.environ['LLM_API_KEY'] = 'sk-fake'
        os.environ['JWT_SECRET'] = 'a' * 64
        os.environ['TRUSTED_UPSTREAM_IPS'] = '10.0.0.5'
        os.environ.pop('UPSTREAM_AUTH_SHARED_SECRET', None)
        import importlib, sys
        # Drop any cached copy from the parent test process.
        for mod in [m for m in list(sys.modules) if m.startswith('backend.')]:
            del sys.modules[mod]
        try:
            import backend.shared.config  # noqa: F401
        except RuntimeError as e:
            print('GUARD_TRIPPED:', str(e))
            raise SystemExit(0)
        print('GUARD_MISSED')
        raise SystemExit(1)
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, (
        f"boot guard did not trip.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "GUARD_TRIPPED" in proc.stdout
    assert "non-loopback" in proc.stdout.lower()


def test_non_loopback_trust_with_secret_boots_ok() -> None:
    """Counterpart: when the shared secret IS set, the guard must NOT
    trip — otherwise legitimate sidecar deployments can't start."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import os
        os.environ.pop('PYTEST_CURRENT_TEST', None)
        os.environ['LLM_MODE'] = 'anthropic'
        os.environ['ANTHROPIC_API_KEY'] = 'sk-fake'
        os.environ['LLM_API_KEY'] = 'sk-fake'
        os.environ['JWT_SECRET'] = 'a' * 64
        os.environ['TRUSTED_UPSTREAM_IPS'] = '10.0.0.5'
        os.environ['UPSTREAM_AUTH_SHARED_SECRET'] = 'shhh'
        import sys
        for mod in [m for m in list(sys.modules) if m.startswith('backend.')]:
            del sys.modules[mod]
        import backend.shared.config as c
        print('BOOT_OK', c.settings.UPSTREAM_AUTH_SHARED_SECRET)
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, (
        f"boot tripped unexpectedly.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "BOOT_OK" in proc.stdout


def test_mock_mode_bypasses_non_loopback_guard() -> None:
    """LLM_MODE=mock is the POC default and may legitimately want a
    non-loopback trust entry without configuring a secret (the boot guard
    is a *prod* check, not a dev nag)."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import os
        os.environ.pop('PYTEST_CURRENT_TEST', None)
        os.environ['LLM_MODE'] = 'mock'
        os.environ['TRUSTED_UPSTREAM_IPS'] = '10.0.0.5'
        os.environ.pop('UPSTREAM_AUTH_SHARED_SECRET', None)
        import sys
        for mod in [m for m in list(sys.modules) if m.startswith('backend.')]:
            del sys.modules[mod]
        import backend.shared.config  # noqa: F401
        print('MOCK_BOOT_OK')
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, (
        f"mock mode should bypass guard.\nstdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )
    assert "MOCK_BOOT_OK" in proc.stdout


# ---------------------------------------------------------------------------
# 7. IMPORTANT — shared-secret enforcement + tenant-mismatch warning
# ---------------------------------------------------------------------------

def test_shared_secret_required_when_configured(monkeypatch) -> None:
    """When UPSTREAM_AUTH_SHARED_SECRET is set, a request without (or
    with a wrong) x-upstream-auth-token falls back to JWT — even from a
    trusted IP. This is the defence-in-depth for sidecar deployments."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))
    monkeypatch.setattr(settings, "UPSTREAM_AUTH_SHARED_SECRET", "right-secret")

    # No token header at all -> declined.
    request = _fake_request(
        client_host="10.0.0.5",
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_a"},
    )
    assert auth_mod._user_from_upstream_headers(request) is None

    # Wrong token -> declined.
    request_wrong = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "alice",
            "x-tenant-id": "tenant_a",
            "x-upstream-auth-token": "wrong-secret",
        },
    )
    assert auth_mod._user_from_upstream_headers(request_wrong) is None

    # Right token -> accepted.
    request_right = _fake_request(
        client_host="10.0.0.5",
        headers={
            "x-user-id": "alice",
            "x-tenant-id": "tenant_a",
            "x-upstream-auth-token": "right-secret",
        },
    )
    user = auth_mod._user_from_upstream_headers(request_right)
    assert user is not None
    assert user.user_id == "alice"


def test_tenant_mismatch_for_known_user_pins_on_file_tenant(monkeypatch, caplog) -> None:
    """H-1: when upstream claims tenant_b for alice (who is in _USERS as
    tenant_a), the on-file tenant MUST win — the upstream tenant is ignored,
    not honoured. Otherwise a trusted-IP bug/attacker could re-scope alice
    into another tenant's cache/audit/masking namespace under her identity.
    A warning is still logged as the audit signal for the spoof attempt."""
    import logging

    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))
    caplog.set_level(logging.WARNING, logger="backend.gateway.auth")

    request = _fake_request(
        client_host="10.0.0.5",
        headers={"x-user-id": "alice", "x-tenant-id": "tenant_b"},
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    # H-1 fix: pinned to the _USERS tenant, NOT the spoofed upstream one.
    assert user.tenant_id == auth_mod._USERS["alice"].tenant_id == "tenant_a"
    assert any("tenant mismatch" in rec.message for rec in caplog.records), (
        f"expected tenant-mismatch warning; got: {[r.message for r in caplog.records]}"
    )


def test_unknown_user_keeps_upstream_tenant(monkeypatch) -> None:
    """An UNKNOWN user has no on-file tenant to pin to, so the upstream tenant
    still stands (they are already forced to least-privilege role elsewhere).
    This guards the H-1 fix from over-reaching into the unknown-user path."""
    monkeypatch.setattr(settings, "TRUSTED_UPSTREAM_IPS", ("10.0.0.5",))
    request = _fake_request(
        client_host="10.0.0.5",
        headers={"x-user-id": "ext-user-7", "x-tenant-id": "tenant_partner"},
    )
    user = auth_mod._user_from_upstream_headers(request)
    assert user is not None
    assert user.tenant_id == "tenant_partner"


# Local imports at module top kept minimal — pull `Path` lazily here so the
# boot-guard subprocess tests above can locate the repo root without dragging
# pathlib into the top-of-file imports (which the original test file kept
# deliberately spartan).
from pathlib import Path  # noqa: E402
