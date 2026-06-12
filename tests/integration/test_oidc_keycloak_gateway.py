"""Q12 P0 — gateway wiring for OIDC_MODE=keycloak, fully offline.

Drives the real /v1/auth/oidc/begin + /callback handlers with the Keycloak
provider backed by an httpx.MockTransport (mock IdP, real PyJWT RS256
verification). Asserts the two contractual outcomes the task cares about:

  1. begin returns the REAL realm authorize URL (from discovery), callback
     does code->token + JWKS verification and signs OUR OWN gateway JWT
     (the Keycloak token is never the session token).
  2. Invariant #6 survives federation: the case ACL is enforced on the
     resulting session exactly as for a password login — alice via Keycloak
     still cannot touch a case outside her ACL.
"""

from __future__ import annotations

import json
import time

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.gateway import auth as auth_mod
from backend.gateway import oidc_keycloak as kc_mod
from backend.shared.config import settings

ISSUER = "http://keycloak.test/realms/patentmind"
CLIENT_ID = "patentmind-gateway"
KID = "kid-gw"

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    d = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(_PRIV.public_key()))
    d.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [d]}


def _id_token(*, username: str, nonce: str, tenant: str, role: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": f"uuid-{username}",
            "preferred_username": username,
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "tenant_id": tenant,
            "resource_access": {CLIENT_ID: {"roles": [role]}},
        },
        _PRIV,
        algorithm="RS256",
        headers={"kid": KID},
    )


@pytest.fixture()
def keycloak_mode(monkeypatch):
    """Flip the gateway into keycloak mode with a mock-transport provider.

    ``state['id_token']`` controls what the fake token endpoint returns.
    """
    state = {"id_token": None}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                },
            )
        if url.endswith("/certs"):
            return httpx.Response(200, json=_jwks())
        if url.endswith("/token"):
            return httpx.Response(
                200,
                json={"access_token": "at", "token_type": "Bearer", "id_token": state["id_token"]},
            )
        return httpx.Response(404)

    provider = kc_mod.KeycloakOIDCProvider(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret="gw-secret",
        redirect_uri="http://localhost:5173/auth/oidc/callback",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(settings, "OIDC_MODE", "keycloak")
    # Both main.py (begin) and auth.py (callback) import this factory lazily,
    # so one monkeypatch covers both call sites.
    monkeypatch.setattr(kc_mod, "get_keycloak_provider", lambda: provider)

    from backend.gateway import rate_limit as rl

    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()
    yield state
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()


def test_begin_returns_real_realm_authorize_url(gateway_client, keycloak_mode):
    r = gateway_client.get("/v1/auth/oidc/begin")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorize_url"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    assert f"state={body['state']}" in body["authorize_url"]
    assert f"nonce={body['nonce']}" in body["authorize_url"]
    assert "redirect_uri=" in body["authorize_url"]


def test_full_code_flow_issues_gateway_jwt_and_acl_still_bites(
    gateway_client, keycloak_mode
):
    # begin -> the gateway minted a state bound to a nonce.
    begin = gateway_client.get("/v1/auth/oidc/begin").json()
    keycloak_mode["id_token"] = _id_token(
        username="alice", nonce=begin["nonce"], tenant="tenant_a", role="attorney"
    )

    # callback -> OUR session JWT (HS256, our iss/aud), not the Keycloak token.
    r = gateway_client.post(
        "/v1/auth/oidc/callback", json={"code": "opaque-kc-code", "state": begin["state"]}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "alice"
    assert body["role"] == "attorney"
    assert body["tenant_id"] == "tenant_a"
    claims = pyjwt.decode(
        body["token"],
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGO],
        audience=settings.JWT_AUD,
        issuer=settings.JWT_ISS,
    )
    assert claims["sub"] == "alice"  # gateway-signed session, not Keycloak's

    # Invariant #6: the federated session hits the SAME case ACL. alice has no
    # access to CASE-2025-999 -> 403 before any orchestration happens.
    denied = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {body['token']}"},
        json={
            "oa_text": "claim 1 rejected under 35 USC 103",
            "case_id": "CASE-2025-999",
            "target_patent_no": "US1234567",
        },
    )
    assert denied.status_code == 403, denied.text


def test_replayed_state_is_rejected_in_keycloak_mode(gateway_client, keycloak_mode):
    begin = gateway_client.get("/v1/auth/oidc/begin").json()
    keycloak_mode["id_token"] = _id_token(
        username="alice", nonce=begin["nonce"], tenant="tenant_a", role="attorney"
    )
    first = gateway_client.post(
        "/v1/auth/oidc/callback", json={"code": "c", "state": begin["state"]}
    )
    assert first.status_code == 200
    replay = gateway_client.post(
        "/v1/auth/oidc/callback", json={"code": "c", "state": begin["state"]}
    )
    assert replay.status_code == 401  # single-use state, uniform 401


def test_unknown_federated_user_is_least_privilege(gateway_client, keycloak_mode):
    begin = gateway_client.get("/v1/auth/oidc/begin").json()
    keycloak_mode["id_token"] = _id_token(
        username="mallory", nonce=begin["nonce"], tenant="tenant_a", role="auditor"
    )
    r = gateway_client.post(
        "/v1/auth/oidc/callback", json={"code": "c", "state": begin["state"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "paralegal"  # auditor hint downgraded
