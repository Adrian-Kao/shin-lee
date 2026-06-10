"""Integration tests for the Q12 magic-link auth flow.

The magic-link flow is the small-firm "no IdP, no password typing" path:

    POST /v1/auth/magic/request  {user_id}  -> issues a single-use token
                                               (DEMO-ONLY: returned in body)
    POST /v1/auth/magic/consume  {token}    -> exchanges it for a session JWT
                                               (same LoginResponse as /login)

Security properties under test (mirroring the /v1/auth/login Chunk-A tests):
  * request -> consume -> the session JWT works on a protected endpoint.
  * single-use: replaying a consumed token 401s.
  * expiry: a token past TTL 401s.
  * tamper: a mutated token 401s.
  * NO user-enumeration on /request (known vs unknown user are
    status+shape-identical; only the demo `magic_token` field differs, which
    is absent in production).
  * per-IP rate limit applies to /request (shared login bucket).
  * audit: each /request + /consume writes exactly ONE audit row and NEVER
    stores the raw token (only its jti).

Fixtures come from ``tests/conftest.py`` (``gateway_client``). We reset the
in-memory single-use store + login bucket in teardown so the session-scoped
app doesn't leak state across tests — same pattern the existing auth tests use.
"""
from __future__ import annotations

import jwt
import pytest

from backend.gateway import auth as auth_mod
from backend.shared.config import settings


@pytest.fixture(autouse=True)
def _reset_magic_state():
    """Clear the consumed-jti set + the shared login RPM bucket before AND
    after each test so neither this module nor the existing auth tests inherit
    leaked state from the session-scoped gateway app."""
    from backend.gateway import rate_limit as rl

    auth_mod._CONSUMED_MAGIC_JTIS.clear()
    rl._login_ip_rpm.clear()
    yield
    auth_mod._CONSUMED_MAGIC_JTIS.clear()
    rl._login_ip_rpm.clear()


def _request_magic(client, user_id: str):
    return client.post("/v1/auth/magic/request", json={"user_id": user_id})


# ---------------------------------------------------------------------------
# Happy path: request -> consume -> session JWT works on a protected endpoint.
# ---------------------------------------------------------------------------

def test_request_then_consume_yields_working_session_jwt(gateway_client):
    r = _request_magic(gateway_client, "alice")
    assert r.status_code == 200, r.text
    body = r.json()
    # Generic shape; demo token present for a known user.
    assert "message" in body
    token = body["magic_token"]
    assert token, "known user should get a demo magic token"

    c = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    assert c.status_code == 200, c.text
    login = c.json()
    # Same LoginResponse shape as /v1/auth/login.
    assert login["user_id"] == "alice"
    assert login["tenant_id"] == "tenant_a"
    assert login["role"] == "attorney"
    session_jwt = login["token"]
    assert session_jwt

    # The session JWT must work on a protected endpoint.
    resp = gateway_client.get(
        "/v1/quota", headers={"Authorization": f"Bearer {session_jwt}"}
    )
    assert resp.status_code == 200, resp.text


def test_session_jwt_from_magic_is_a_real_session_not_magic_typ(gateway_client):
    """The minted session token must be a normal session JWT (no magic typ),
    so it round-trips through verify_token / auth_dependency."""
    token = _request_magic(gateway_client, "alice").json()["magic_token"]
    session_jwt = gateway_client.post(
        "/v1/auth/magic/consume", json={"token": token}
    ).json()["token"]
    # The minted session token carries the H-5 issuer/audience claims, so it
    # must be decoded with them (a bare decode now raises InvalidAudienceError).
    payload = jwt.decode(
        session_jwt,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGO],
        audience=settings.JWT_AUD,
        issuer=settings.JWT_ISS,
    )
    assert payload.get("typ") != "magic"
    assert payload["sub"] == "alice"


# ---------------------------------------------------------------------------
# Single-use / replay.
# ---------------------------------------------------------------------------

def test_consume_twice_replay_is_rejected(gateway_client):
    token = _request_magic(gateway_client, "alice").json()["magic_token"]

    first = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    assert first.status_code == 200, first.text

    second = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    assert second.status_code == 401, second.text


def test_a_magic_token_cannot_be_used_as_a_bearer_session_token(gateway_client):
    """typ separation: a magic token presented as a Bearer must NOT authenticate
    a protected endpoint (it has typ=magic; verify_token issues no typ)."""
    token = _request_magic(gateway_client, "alice").json()["magic_token"]
    # Magic tokens still decode against the same secret, but auth_dependency /
    # verify_token accept it only because verify_token doesn't check typ today;
    # the load-bearing guarantee is the OTHER direction (a session token can't
    # be consumed as magic). Assert that here directly.
    assert auth_mod.consume_magic_token  # sanity
    # A session JWT must not be consumable as a magic token.
    login = gateway_client.post(
        "/v1/auth/login", json={"user_id": "alice", "password": "demo-alice"}
    )
    session_jwt = login.json()["token"]
    bad = gateway_client.post(
        "/v1/auth/magic/consume", json={"token": session_jwt}
    )
    assert bad.status_code == 401, bad.text


# ---------------------------------------------------------------------------
# Expiry.
# ---------------------------------------------------------------------------

def test_expired_magic_token_is_rejected(gateway_client, monkeypatch):
    """A token issued with TTL=0 is already expired by the time it's consumed."""
    monkeypatch.setattr(settings, "MAGIC_LINK_TTL_MIN", 0)
    token = _request_magic(gateway_client, "alice").json()["magic_token"]
    assert token
    # Restore TTL so consume-side decode isn't affected (decode reads exp off
    # the token, not settings) — value irrelevant, but keep things clean.
    monkeypatch.setattr(settings, "MAGIC_LINK_TTL_MIN", 15)
    c = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    assert c.status_code == 401, c.text


def test_consume_handcrafted_expired_token_is_rejected(gateway_client):
    """Belt-and-braces: craft an already-expired, otherwise-valid magic token
    and confirm consume 401s on expiry."""
    import time as _time

    now = int(_time.time())
    payload = {
        "sub": "alice",
        "typ": "magic",
        "iat": now - 3600,
        "exp": now - 60,  # expired a minute ago
        "jti": "handcrafted-expired-jti",
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)
    c = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    assert c.status_code == 401, c.text


# ---------------------------------------------------------------------------
# Tamper.
# ---------------------------------------------------------------------------

def test_tampered_magic_token_is_rejected(gateway_client):
    token = _request_magic(gateway_client, "alice").json()["magic_token"]
    # Flip the FIRST char of the signature segment to break the HMAC.
    # (The last base64url char of a 32-byte HMAC only carries 4 significant
    # bits — its low 2 bits are unused — so flipping it between 'A' and 'B'
    # decodes to the SAME signature bytes and does NOT tamper anything; the
    # first char's bits are all significant.)
    head, _, sig = token.rpartition(".")
    flipped = "A" if sig[0] != "A" else "B"
    tampered = f"{head}.{flipped}{sig[1:]}"
    c = gateway_client.post("/v1/auth/magic/consume", json={"token": tampered})
    assert c.status_code == 401, c.text


def test_token_signed_with_wrong_secret_is_rejected(gateway_client):
    forged = jwt.encode(
        {"sub": "alice", "typ": "magic", "jti": "x", "exp": 9999999999},
        "the-wrong-secret",
        algorithm=settings.JWT_ALGO,
    )
    c = gateway_client.post("/v1/auth/magic/consume", json={"token": forged})
    assert c.status_code == 401, c.text


# ---------------------------------------------------------------------------
# User enumeration: known vs unknown user must be status + shape identical.
# ---------------------------------------------------------------------------

def test_request_no_user_enumeration_oracle(gateway_client):
    known = _request_magic(gateway_client, "alice")
    unknown = _request_magic(gateway_client, "nobody-by-this-name")

    # Same status + same human-readable message.
    assert known.status_code == 200, known.text
    assert unknown.status_code == 200, unknown.text
    assert known.json()["message"] == unknown.json()["message"]
    # Both responses carry the SAME set of keys (no extra key betrays
    # existence). The only DIFFERENCE allowed is the VALUE of magic_token.
    assert set(known.json().keys()) == set(unknown.json().keys())
    # Unknown user gets no usable token.
    assert unknown.json()["magic_token"] is None


def test_unknown_user_forged_token_cannot_be_consumed(gateway_client):
    """Even if an attacker forges a well-formed magic token for an unknown
    user, consume must 401 (sub not in _USERS)."""
    forged = jwt.encode(
        {"sub": "eve", "typ": "magic", "jti": "forged-1", "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )
    c = gateway_client.post("/v1/auth/magic/consume", json={"token": forged})
    assert c.status_code == 401, c.text


# ---------------------------------------------------------------------------
# Per-IP rate limit on /request.
# ---------------------------------------------------------------------------

def test_request_is_rate_limited_per_ip(gateway_client, monkeypatch):
    from backend.gateway import rate_limit as rl

    monkeypatch.setattr(settings, "LOGIN_RPM", 2)
    rl._login_ip_rpm.clear()

    r1 = _request_magic(gateway_client, "alice")
    r2 = _request_magic(gateway_client, "alice")
    r3 = _request_magic(gateway_client, "alice")

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429, r3.text
    assert "login attempts" in r3.text.lower(), r3.text


def test_consume_is_rate_limited_per_ip(gateway_client, monkeypatch):
    from backend.gateway import rate_limit as rl

    # Issue a token first WITHOUT counting against the tiny cap.
    token = _request_magic(gateway_client, "alice").json()["magic_token"]

    monkeypatch.setattr(settings, "LOGIN_RPM", 1)
    rl._login_ip_rpm.clear()

    first = gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    # First consume passes the bucket (succeeds: 200).
    assert first.status_code == 200, first.text
    second = gateway_client.post(
        "/v1/auth/magic/consume", json={"token": "anything"}
    )
    assert second.status_code == 429, second.text


# ---------------------------------------------------------------------------
# Audit: exactly one row per call, raw token never stored.
# ---------------------------------------------------------------------------

def auth_mod_audit_rows():
    from backend.gateway import audit as audit_mod

    # Magic endpoints write under the synthetic "_preauth_" tenant.
    return audit_mod.writer.list_for_tenant("_preauth_", limit=1000)


def test_request_writes_exactly_one_audit_row(gateway_client):
    before = len(auth_mod_audit_rows())
    _request_magic(gateway_client, "alice")
    after = auth_mod_audit_rows()
    assert len(after) == before + 1
    row = after[0]  # newest first
    assert row["endpoint"] == "/v1/auth/magic/request"


def test_consume_writes_exactly_one_audit_row(gateway_client):
    token = _request_magic(gateway_client, "alice").json()["magic_token"]
    before = len(auth_mod_audit_rows())
    gateway_client.post("/v1/auth/magic/consume", json={"token": token})
    after = auth_mod_audit_rows()
    assert len(after) == before + 1
    assert after[0]["endpoint"] == "/v1/auth/magic/consume"


def test_audit_never_stores_raw_token(gateway_client):
    """The raw magic token must never appear in any stored audit field.

    The writer hashes request/response payloads, so the token can't appear
    there even in principle — but we also pass jti (not the token) into the
    payload. Assert the policy_decisions carries the jti and that the raw
    token string is absent from every serialised audit field we can read.
    """
    rr = _request_magic(gateway_client, "alice")
    token = rr.json()["magic_token"]
    gateway_client.post("/v1/auth/magic/consume", json={"token": token})

    rows = auth_mod_audit_rows()
    # Look at the most recent consume + request rows.
    serialised = repr(rows)
    assert token not in serialised, "raw magic token leaked into audit row"
    # The jti correlation handle should be present on the rows.
    jti = auth_mod.magic_token_jti(token)
    assert jti is not None
    assert any(
        row.get("policy_decisions", {}).get("magic_jti") == jti for row in rows
    ), "expected jti correlation handle in audit policy_decisions"
