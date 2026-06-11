"""H-5 phase 3 — asymmetric (RS256) JWT signing.

The point of asymmetric signing: a service that only needs to VERIFY tokens
holds the PUBLIC key, which cannot MINT tokens. Only the gateway holds the
private key. These tests exercise issue_token / verify_token directly with an
in-test RSA key pair, so no server or fixed key material is needed.
"""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from backend.gateway import auth as auth_mod
from backend.shared.config import settings


def _gen_rsa_pem() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv, pub


def _use_rs256(monkeypatch, priv: str, pub: str) -> None:
    monkeypatch.setattr(settings, "JWT_ALGO", "RS256")
    monkeypatch.setattr(settings, "JWT_PRIVATE_KEY", priv)
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", pub)


def test_rs256_issue_and_verify_roundtrip(monkeypatch):
    priv, pub = _gen_rsa_pem()
    _use_rs256(monkeypatch, priv, pub)

    token = auth_mod.issue_token("alice")
    # Sanity: the token really is RS256-signed.
    assert jwt.get_unverified_header(token)["alg"] == "RS256"

    user = auth_mod.verify_token(token)
    assert user.user_id == "alice"


def test_rs256_token_from_a_foreign_key_is_rejected(monkeypatch):
    priv1, _pub1 = _gen_rsa_pem()
    _priv2, pub2 = _gen_rsa_pem()
    # Server signs with key1's private but verifies against key2's public.
    _use_rs256(monkeypatch, priv1, pub2)

    token = auth_mod.issue_token("alice")  # signed by priv1
    with pytest.raises(HTTPException) as ei:
        auth_mod.verify_token(token)  # verified by mismatched pub2 → bad signature
    assert ei.value.status_code == 401


def test_public_key_alone_cannot_mint_tokens(monkeypatch):
    # The core asymmetric guarantee: a holder of only the PUBLIC key cannot sign.
    priv, pub = _gen_rsa_pem()
    _use_rs256(monkeypatch, pub, pub)  # signer mistakenly given the public key
    # The exact exception type is a cryptography/PyJWT implementation detail
    # (ValueError vs TypeError vs AttributeError depending on version); the
    # guarantee under test is only that signing with a public key FAILS.
    with pytest.raises(Exception):  # noqa: B017
        auth_mod.issue_token("alice")


def test_hs256_default_still_works(monkeypatch):
    # Default symmetric path is untouched (conftest sets a real test secret).
    monkeypatch.setattr(settings, "JWT_ALGO", "HS256")
    token = auth_mod.issue_token("alice")
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert auth_mod.verify_token(token).user_id == "alice"
