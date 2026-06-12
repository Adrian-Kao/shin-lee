"""LIVE Keycloak round-trip (Q12 P0) — SKIPPED unless Keycloak answers.

Mirrors the Qdrant live-tier skip pattern (tests/integration/
test_rag_real_backend.py): if the realm's discovery document is not served at
``settings.OIDC_KEYCLOAK_ISSUER`` the whole module skips cleanly, so CI boxes
without docker stay green. Bring the IdP up with:

    docker compose up -d keycloak          # realm auto-imports
    bash scripts/smoke_keycloak.sh         # full headless code-flow smoke

What runs against the live realm:
  * discovery document sanity (issuer pin, endpoints present)
  * password-grant login for all four demo users (proves the realm import:
    users exist, passwords demo-<user>, client secret valid, direct access
    grants enabled)
  * REAL JWKS signature verification of the live ID token via
    KeycloakOIDCProvider.verify_id_token (nonce skipped — password grant
    carries none; the code-flow nonce path is covered offline + by the smoke
    script)
  * role / tenant protocol mappers emit what backend/gateway expects
"""

from __future__ import annotations

import httpx
import pytest

from backend.gateway.oidc_keycloak import (
    KeycloakOIDCProvider,
    extract_role_hint,
    extract_tenant_hint,
)
from backend.shared.config import settings

# Dev secret shipped in keycloak/realm-patentmind.json; a deployment that
# rotated it must export OIDC_KEYCLOAK_CLIENT_SECRET.
_DEV_CLIENT_SECRET = "patentmind-gateway-dev-secret-change-me"

_EXPECTED = {
    "alice": ("attorney", "tenant_a"),
    "bob": ("paralegal", "tenant_a"),
    "carol": ("it_admin", "tenant_b"),
    "audit_dave": ("auditor", "tenant_a"),
}


def _provider_or_skip() -> KeycloakOIDCProvider:
    issuer = settings.OIDC_KEYCLOAK_ISSUER
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=3.0)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - depends on env
        pytest.skip(f"Keycloak not reachable at {url}: {exc}")
    return KeycloakOIDCProvider(
        issuer=issuer,
        client_id=settings.OIDC_KEYCLOAK_CLIENT_ID,
        client_secret=settings.OIDC_KEYCLOAK_CLIENT_SECRET or _DEV_CLIENT_SECRET,
        redirect_uri=settings.OIDC_REDIRECT_URI,
    )


def _password_grant(provider: KeycloakOIDCProvider, username: str) -> dict:
    token_endpoint = provider.discovery()["token_endpoint"]
    resp = httpx.post(
        token_endpoint,
        data={
            "grant_type": "password",
            "client_id": settings.OIDC_KEYCLOAK_CLIENT_ID,
            "client_secret": settings.OIDC_KEYCLOAK_CLIENT_SECRET or _DEV_CLIENT_SECRET,
            "username": username,
            "password": f"demo-{username}",
            "scope": "openid",
        },
        timeout=10.0,
    )
    assert resp.status_code == 200, f"{username}: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def test_live_discovery_document_is_sane():
    provider = _provider_or_skip()
    doc = provider.discovery()
    assert doc["issuer"] == settings.OIDC_KEYCLOAK_ISSUER
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        assert doc[field].startswith("http")


@pytest.mark.parametrize("username", sorted(_EXPECTED))
def test_live_demo_user_id_token_verifies_and_maps(username):
    provider = _provider_or_skip()
    tokens = _password_grant(provider, username)
    id_token = tokens.get("id_token")
    assert id_token, "scope=openid must yield an id_token"

    # Real JWKS signature + iss/aud verification (nonce skipped: password
    # grant has no nonce; the nonce-bound code flow is covered offline).
    claims = provider.verify_id_token(id_token, expected_nonce=None)
    assert claims["preferred_username"] == username

    role, tenant = _EXPECTED[username]
    assert (
        extract_role_hint(claims, settings.OIDC_KEYCLOAK_CLIENT_ID, settings.OIDC_ROLE_CLAIM)
        == role
    )
    assert extract_tenant_hint(claims, settings.OIDC_TENANT_CLAIM) == tenant


def test_live_wrong_password_is_rejected():
    provider = _provider_or_skip()
    token_endpoint = provider.discovery()["token_endpoint"]
    resp = httpx.post(
        token_endpoint,
        data={
            "grant_type": "password",
            "client_id": settings.OIDC_KEYCLOAK_CLIENT_ID,
            "client_secret": settings.OIDC_KEYCLOAK_CLIENT_SECRET or _DEV_CLIENT_SECRET,
            "username": "alice",
            "password": "definitely-wrong",
            "scope": "openid",
        },
        timeout=10.0,
    )
    assert resp.status_code == 401
