"""H-5 — JWT lifecycle hardening: issuer/audience pinning, jti revocation
(logout kill switch), and magic-token / session-token separation.

All tests drive the real gateway via the in-process TestClient and a protected
endpoint (`GET /v1/quota`, which only depends on `auth_dependency`). They prove
the verify_token gate, not just the helper in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from backend.shared.config import settings


def _encode(claims: dict) -> str:
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)


def _base_claims(**overrides) -> dict:
    now = datetime.now(UTC)
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "role": "attorney",
        "iss": settings.JWT_ISS,
        "aud": settings.JWT_AUD,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "test-jti-1",
    }
    claims.update(overrides)
    return claims


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_valid_session_token_is_accepted(gateway_client, alice_token):
    # Sanity: a token minted by the real login flow passes (carries iss/aud/jti).
    resp = gateway_client.get("/v1/quota", headers=_auth(alice_token))
    assert resp.status_code == 200, resp.text


def test_token_without_audience_is_rejected(gateway_client):
    claims = _base_claims()
    claims.pop("aud")
    resp = gateway_client.get("/v1/quota", headers=_auth(_encode(claims)))
    assert resp.status_code == 401, resp.text


def test_token_with_wrong_issuer_is_rejected(gateway_client):
    token = _encode(_base_claims(iss="some-other-service"))
    resp = gateway_client.get("/v1/quota", headers=_auth(token))
    assert resp.status_code == 401, resp.text


def test_magic_typ_token_cannot_be_used_as_session(gateway_client):
    # Even WITH correct aud/iss, a typ=magic token must be refused on the
    # session path (defence in depth — the typ guard).
    token = _encode(_base_claims(typ="magic"))
    resp = gateway_client.get("/v1/quota", headers=_auth(token))
    assert resp.status_code == 401, resp.text
    assert "type" in resp.text.lower() or "invalid" in resp.text.lower()


def test_logout_revokes_the_token(gateway_client, alice_token):
    # Before logout: accepted.
    assert gateway_client.get("/v1/quota", headers=_auth(alice_token)).status_code == 200

    # Logout revokes this token's jti.
    out = gateway_client.post("/v1/auth/logout", headers=_auth(alice_token))
    assert out.status_code == 200, out.text
    assert out.json().get("revoked") is True

    # After logout: the SAME token is refused for the rest of its TTL.
    after = gateway_client.get("/v1/quota", headers=_auth(alice_token))
    assert after.status_code == 401, after.text
    assert "revoked" in after.text.lower()


def test_logout_is_idempotent(gateway_client):
    # A fresh token, logged out twice: first revokes, second is a no-op but the
    # endpoint itself still requires a (currently-valid) token to authenticate.
    login = gateway_client.post(
        "/v1/auth/login", json={"user_id": "alice", "password": "demo-alice"}
    )
    token = login.json()["token"]
    first = gateway_client.post("/v1/auth/logout", headers=_auth(token))
    assert first.status_code == 200 and first.json()["revoked"] is True
    # The token is now revoked, so a second logout can't authenticate → 401.
    second = gateway_client.post("/v1/auth/logout", headers=_auth(token))
    assert second.status_code == 401, second.text
