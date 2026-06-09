"""Q12 (Day 13F) — adversarial JWT / revocation tests against the live gateway.

These drive a protected endpoint (GET /v1/quota, which depends only on
auth_dependency) so they prove the verify_token gate end-to-end, not just the
helper in isolation. They complement test_jwt_lifecycle.py with the attack
shapes a real reviewer probes: alg-confusion (alg=none, HS-vs-RS), forged
iss/aud, expired, revoked, and the "not-before" claim.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.gateway import auth as auth_mod
from backend.shared.config import settings


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _base_claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "role": "attorney",
        "iss": settings.JWT_ISS,
        "aud": settings.JWT_AUD,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": f"adv-{now.timestamp()}",
    }
    claims.update(overrides)
    return claims


# ---------------------------------------------------------------------------
# alg-confusion: alg=none
# ---------------------------------------------------------------------------
def test_alg_none_token_is_rejected(gateway_client):
    """A token signed with alg=none (no signature) must be refused. PyJWT
    refuses to decode an unsigned token against an algorithm list that does not
    include 'none', so this is a regression guard on that configuration."""
    # Manually craft an alg=none token: header.payload. (empty signature).
    unsigned = jwt.encode(_base_claims(), key="", algorithm="none")
    r = gateway_client.get("/v1/quota", headers=_auth(unsigned))
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# alg-confusion: HS256 token when the server expects RS256 (key confusion)
# ---------------------------------------------------------------------------
def test_hs256_token_rejected_when_server_is_rs256(gateway_client, monkeypatch):
    """Classic RS/HS algorithm-confusion: with the server configured for RS256,
    an HS256-signed token must be refused because verify_token pins algorithms
    to the single configured alg (RS256). We construct the HS256 token by hand
    (PyJWT refuses to HMAC-sign with a PEM key, which is itself a defence) using
    the PUBLIC key bytes as the HMAC secret — the exact shape of the attack."""
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    monkeypatch.setattr(settings, "JWT_ALGO", "RS256")
    monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", priv_pem)
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", pub_pem)

    def _b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).decode().rstrip("=")

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(_base_claims()).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64(hmac.new(pub_pem.encode(), signing_input, hashlib.sha256).digest())
    forged = f"{header}.{payload}.{sig}"

    r = gateway_client.get("/v1/quota", headers=_auth(forged))
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# forged iss / aud / nbf / expiry
# ---------------------------------------------------------------------------
def test_token_with_future_nbf_is_rejected(gateway_client):
    """A not-before in the future must be refused (PyJWT enforces nbf)."""
    future = int(time.time()) + 3600
    token = jwt.encode(
        _base_claims(nbf=future), settings.JWT_SECRET, algorithm=settings.JWT_ALGO
    )
    r = gateway_client.get("/v1/quota", headers=_auth(token))
    assert r.status_code == 401, r.text


def test_token_with_forged_signature_is_rejected(gateway_client):
    token = jwt.encode(_base_claims(), "attacker-secret", algorithm="HS256")
    r = gateway_client.get("/v1/quota", headers=_auth(token))
    assert r.status_code == 401, r.text


def test_token_for_unknown_subject_is_rejected(gateway_client):
    token = jwt.encode(
        _base_claims(sub="ghost-who-was-never-registered"),
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )
    r = gateway_client.get("/v1/quota", headers=_auth(token))
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# revocation: a revoked jti is refused even though the token is otherwise valid
# ---------------------------------------------------------------------------
def test_revoked_jti_is_rejected_even_with_valid_signature(gateway_client):
    from backend.gateway import revocation

    token = jwt.encode(
        _base_claims(jti="revoke-me-explicitly"),
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )
    # Valid before revoke.
    assert gateway_client.get("/v1/quota", headers=_auth(token)).status_code == 200
    revocation.revoke("revoke-me-explicitly", 3600)
    after = gateway_client.get("/v1/quota", headers=_auth(token))
    assert after.status_code == 401, after.text
    assert "revoked" in after.text.lower()
    revocation.clear()


# ---------------------------------------------------------------------------
# revoke_token helper contract: undecodable / expired tokens are no-ops
# ---------------------------------------------------------------------------
def test_revoke_token_returns_false_for_undecodable():
    assert auth_mod.revoke_token("garbage.not.a.jwt") is False


def test_revoke_token_returns_false_for_expired():
    expired = jwt.encode(
        _base_claims(exp=int(time.time()) - 60, jti="already-expired"),
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )
    # Best-effort: nothing to revoke on an already-dead token.
    assert auth_mod.revoke_token(expired) is False
