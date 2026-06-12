"""Q12 P0 — real Keycloak OIDC provider (OIDC_MODE=keycloak), fully offline.

No docker, no network: discovery / JWKS / token endpoint are served by an
``httpx.MockTransport``; ID tokens are RS256-signed with an in-test RSA key.
This is the ALWAYS-RUN coverage for the keycloak path:

  * discovery pinning (self-declared issuer must match config)
  * code->token exchange wiring (client_secret_post, redirect_uri echo)
  * ID-token JWKS signature verification (PyJWT), incl. key-rotation refetch
  * iss / aud / exp / nonce / azp pinning + algorithm allow-list (no HS/none)
  * role mapping: flat claim > resource_access.<client>.roles > realm_access,
    priority attorney > paralegal > auditor > it_admin, unknown roles ignored
  * tenant mapping: configured claim, str or one-element-list shapes
  * privilege boundary: known users pin to _USERS; unknown users can never
    self-assert AUDITOR / IT_ADMIN (same as the stub + upstream-header doors)
  * OIDC_MODE routing in get_oidc_provider()

The LIVE Keycloak round-trip (docker) lives in
tests/integration/test_keycloak_live.py and skips when Keycloak is down.
"""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.gateway import auth as auth_mod
from backend.gateway import oidc_keycloak as kc_mod
from backend.gateway.auth import IdpError
from backend.gateway.oidc_keycloak import (
    KeycloakOIDCProvider,
    extract_role_hint,
    extract_tenant_hint,
)
from backend.shared.config import settings
from backend.shared.models import UserRole

ISSUER = "http://keycloak.test/realms/patentmind"
CLIENT_ID = "patentmind-gateway"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "http://localhost:5173/auth/oidc/callback"
KID = "test-kid-1"

# One RSA pair for the whole module (2048-bit gen is ~100ms; fine once).
_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ATTACKER_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(pub, kid: str) -> dict:
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(pub))
    d.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return d


def _jwks(kid: str = KID, pub=None) -> dict:
    return {"keys": [_jwk(pub or _PRIV.public_key(), kid)]}


def _id_token(
    *,
    sub: str = "uuid-alice",
    preferred_username: str | None = "alice",
    iss: str = ISSUER,
    aud=CLIENT_ID,
    nonce: str | None = "the-nonce",
    exp: int | None = None,
    azp: str | None = CLIENT_ID,
    key=_PRIV,
    alg: str = "RS256",
    kid: str = KID,
    **extra,
) -> str:
    now = int(time.time())
    claims: dict = {"sub": sub, "iss": iss, "aud": aud, "iat": now, "exp": exp or now + 300}
    if preferred_username is not None:
        claims["preferred_username"] = preferred_username
    if nonce is not None:
        claims["nonce"] = nonce
    if azp is not None:
        claims["azp"] = azp
    claims.update(extra)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _make_provider(**overrides):
    """Provider + mutable transport state. ``state['id_token']`` is what the
    token endpoint returns; tests set it per scenario."""
    state = {
        "id_token": None,
        "jwks": _jwks(),
        "discovery_issuer": ISSUER,
        "token_status": 200,
        "token_requests": [],
        "jwks_fetches": 0,
        "omit_id_token": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": state["discovery_issuer"],
                    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                },
            )
        if url.endswith("/protocol/openid-connect/certs"):
            state["jwks_fetches"] += 1
            return httpx.Response(200, json=state["jwks"])
        if url.endswith("/protocol/openid-connect/token"):
            state["token_requests"].append(dict(httpx.QueryParams(request.content.decode())))
            if state["token_status"] != 200:
                return httpx.Response(state["token_status"], json={"error": "invalid_grant"})
            body = {"access_token": "at", "token_type": "Bearer"}
            if not state["omit_id_token"]:
                body["id_token"] = state["id_token"]
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    kwargs = dict(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    kwargs.update(overrides)
    return KeycloakOIDCProvider(**kwargs), state


# ---------------------------------------------------------------------------
# Discovery + authorize URL
# ---------------------------------------------------------------------------
def test_authorize_url_comes_from_discovery_and_carries_flow_params():
    provider, _ = _make_provider()
    url = provider.authorize_url(state="st4te", nonce="n0nce")
    assert url.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    assert "response_type=code" in url
    assert f"client_id={CLIENT_ID}" in url
    assert "state=st4te" in url
    assert "nonce=n0nce" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fauth%2Foidc%2Fcallback" in url


def test_discovery_issuer_mismatch_is_rejected():
    provider, state = _make_provider()
    state["discovery_issuer"] = "http://evil.test/realms/patentmind"
    with pytest.raises(IdpError, match="issuer mismatch"):
        provider.discovery()


# ---------------------------------------------------------------------------
# Code -> token exchange + ID-token verification
# ---------------------------------------------------------------------------
def test_exchange_code_happy_path_maps_identity():
    provider, state = _make_provider()
    state["id_token"] = _id_token(
        tenant_id="tenant_a",
        resource_access={CLIENT_ID: {"roles": ["attorney"]}},
    )
    identity = provider.exchange_code("opaque-code", "the-nonce")
    assert identity.subject == "alice"  # preferred_username, NOT the uuid sub
    assert identity.issuer == ISSUER
    assert identity.tenant_hint == "tenant_a"
    assert identity.role_hint == "attorney"
    # The exchange leg must be client_secret_post with the byte-identical
    # redirect_uri (Keycloak enforces it).
    req = state["token_requests"][0]
    assert req["grant_type"] == "authorization_code"
    assert req["code"] == "opaque-code"
    assert req["client_id"] == CLIENT_ID
    assert req["client_secret"] == CLIENT_SECRET
    assert req["redirect_uri"] == REDIRECT_URI


def test_subject_falls_back_to_sub_without_preferred_username():
    provider, state = _make_provider()
    state["id_token"] = _id_token(preferred_username=None)
    assert provider.exchange_code("c", "the-nonce").subject == "uuid-alice"


def test_audience_mismatch_rejected():
    provider, state = _make_provider()
    state["id_token"] = _id_token(aud="some-other-client", azp=None)
    with pytest.raises(IdpError, match="ID token rejected"):
        provider.exchange_code("c", "the-nonce")


def test_issuer_mismatch_rejected():
    provider, state = _make_provider()
    state["id_token"] = _id_token(iss="http://evil.test/realms/patentmind")
    with pytest.raises(IdpError, match="ID token rejected"):
        provider.exchange_code("c", "the-nonce")


def test_expired_token_rejected():
    provider, state = _make_provider()
    # Well past exp + the 30s clock-skew leeway.
    state["id_token"] = _id_token(exp=int(time.time()) - 120)
    with pytest.raises(IdpError, match="ID token rejected"):
        provider.exchange_code("c", "the-nonce")


def test_nonce_mismatch_rejected():
    provider, state = _make_provider()
    state["id_token"] = _id_token(nonce="someone-elses-nonce")
    with pytest.raises(IdpError, match="nonce mismatch"):
        provider.exchange_code("c", "the-nonce")


def test_missing_nonce_rejected():
    provider, state = _make_provider()
    state["id_token"] = _id_token(nonce=None)
    with pytest.raises(IdpError, match="nonce mismatch"):
        provider.exchange_code("c", "the-nonce")


def test_forged_signature_rejected():
    provider, state = _make_provider()
    # Signed by an attacker key but claiming the legit kid.
    state["id_token"] = _id_token(key=_ATTACKER_PRIV)
    with pytest.raises(IdpError, match="ID token rejected"):
        provider.exchange_code("c", "the-nonce")


def test_hs256_alg_confusion_rejected():
    provider, state = _make_provider()
    # Classic alg-confusion: HMAC-sign with a guessable string; the verifier
    # must refuse symmetric algorithms outright, never try them.
    state["id_token"] = jwt.encode(
        {
            "sub": "x",
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": "the-nonce",
        },
        "guessable-secret",
        algorithm="HS256",
        headers={"kid": KID},
    )
    with pytest.raises(IdpError):
        provider.exchange_code("c", "the-nonce")


def test_azp_mismatch_rejected():
    provider, state = _make_provider()
    state["id_token"] = _id_token(azp="another-client")
    with pytest.raises(IdpError, match="azp mismatch"):
        provider.exchange_code("c", "the-nonce")


def test_token_endpoint_error_rejected():
    provider, state = _make_provider()
    state["token_status"] = 400
    with pytest.raises(IdpError, match="token endpoint returned 400"):
        provider.exchange_code("c", "the-nonce")


def test_missing_id_token_rejected():
    provider, state = _make_provider()
    state["omit_id_token"] = True
    with pytest.raises(IdpError, match="no id_token"):
        provider.exchange_code("c", "the-nonce")


def test_empty_client_secret_rejected_before_any_network():
    provider, state = _make_provider(client_secret="")
    state["id_token"] = _id_token()
    with pytest.raises(IdpError, match="OIDC_KEYCLOAK_CLIENT_SECRET"):
        provider.exchange_code("c", "the-nonce")
    assert state["token_requests"] == []  # never reached the token endpoint


def test_jwks_key_rotation_triggers_one_refetch():
    provider, state = _make_provider()
    # Prime the JWKS cache with a stale key set (old kid only).
    provider._jwks = jwt.PyJWKSet.from_dict(_jwks(kid="old-kid"))
    provider._jwks_at = time.time()
    state["id_token"] = _id_token()  # signed with KID, not in the stale cache
    identity = provider.exchange_code("c", "the-nonce")
    assert identity.subject == "alice"
    assert state["jwks_fetches"] == 1  # exactly one forced refetch


def test_unknown_kid_after_refetch_rejected():
    provider, state = _make_provider()
    state["jwks"] = _jwks(kid="totally-different-kid")
    state["id_token"] = _id_token()
    with pytest.raises(IdpError, match="no JWKS key matches"):
        provider.exchange_code("c", "the-nonce")


# ---------------------------------------------------------------------------
# Role / tenant claim mapping
# ---------------------------------------------------------------------------
def test_flat_role_claim_wins_over_resource_access():
    claims = {
        "role": "paralegal",
        "resource_access": {CLIENT_ID: {"roles": ["attorney"]}},
    }
    assert extract_role_hint(claims, CLIENT_ID) == "paralegal"


def test_flat_role_claim_accepts_list():
    assert extract_role_hint({"role": ["auditor", "attorney"]}, CLIENT_ID) == "attorney"


def test_client_roles_win_over_realm_roles():
    claims = {
        "resource_access": {CLIENT_ID: {"roles": ["paralegal"]}},
        "realm_access": {"roles": ["attorney"]},
    }
    assert extract_role_hint(claims, CLIENT_ID) == "paralegal"


def test_realm_roles_are_the_last_fallback():
    assert extract_role_hint({"realm_access": {"roles": ["it_admin"]}}, CLIENT_ID) == "it_admin"


def test_role_priority_everyday_roles_outrank_privileged():
    # attorney > auditor within one source: a user holding both still gets a
    # USABLE hint (an unknown user's auditor hint would be downgraded anyway).
    claims = {"resource_access": {CLIENT_ID: {"roles": ["auditor", "attorney"]}}}
    assert extract_role_hint(claims, CLIENT_ID) == "attorney"


def test_unrecognised_roles_ignored():
    claims = {
        "realm_access": {"roles": ["offline_access", "uma_authorization", "default-roles-x"]}
    }
    assert extract_role_hint(claims, CLIENT_ID) is None


def test_other_clients_roles_are_not_ours():
    claims = {"resource_access": {"some-other-client": {"roles": ["attorney"]}}}
    assert extract_role_hint(claims, CLIENT_ID) is None


def test_role_matching_is_case_insensitive_and_trimmed():
    assert extract_role_hint({"role": "  Attorney "}, CLIENT_ID) == "attorney"


def test_tenant_hint_string_and_list_shapes():
    assert extract_tenant_hint({"tenant_id": "tenant_a"}) == "tenant_a"
    # Keycloak attribute mappers can emit one-element lists.
    assert extract_tenant_hint({"tenant_id": ["tenant_b"]}) == "tenant_b"
    assert extract_tenant_hint({"tenant": "tenant_c"}) == "tenant_c"
    assert extract_tenant_hint({}) is None
    assert extract_tenant_hint({"tenant_id": ""}) is None


# ---------------------------------------------------------------------------
# Privilege boundary: the keycloak path feeds the SAME _resolve_idp_user as
# the stub / upstream-header doors.
# ---------------------------------------------------------------------------
@pytest.fixture()
def _idp_state():
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    yield
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()


def test_known_user_pins_to_users_table_despite_idp_hints(_idp_state):
    """alice's ID token claiming auditor/tenant_b changes NOTHING — role,
    tenant and therefore the case ACL (invariant #6) stay server-side."""
    provider, st = _make_provider()
    state, nonce = auth_mod.begin_oidc_login()
    st["id_token"] = _id_token(
        preferred_username="alice",
        nonce=nonce,
        tenant_id="tenant_b",
        resource_access={CLIENT_ID: {"roles": ["auditor"]}},
    )
    user = auth_mod.authenticate_oidc_callback("code", state, provider=provider)
    assert user.user_id == "alice"
    assert user.role is UserRole.ATTORNEY
    assert user.tenant_id == "tenant_a"


def test_unknown_user_cannot_self_assert_auditor(_idp_state):
    provider, st = _make_provider()
    state, nonce = auth_mod.begin_oidc_login()
    st["id_token"] = _id_token(
        sub="uuid-mallory",
        preferred_username="mallory",
        nonce=nonce,
        tenant_id="tenant_a",
        resource_access={CLIENT_ID: {"roles": ["auditor"]}},
    )
    user = auth_mod.authenticate_oidc_callback("code", state, provider=provider)
    assert user.user_id == "mallory"
    assert user.role is UserRole.PARALEGAL  # downgraded, never auditor
    assert user.tenant_id == "tenant_a"


def test_unknown_user_may_assert_attorney(_idp_state):
    provider, st = _make_provider()
    state, nonce = auth_mod.begin_oidc_login()
    st["id_token"] = _id_token(
        sub="uuid-norah",
        preferred_username="norah",
        nonce=nonce,
        tenant_id="tenant_b",
        resource_access={CLIENT_ID: {"roles": ["attorney"]}},
    )
    user = auth_mod.authenticate_oidc_callback("code", state, provider=provider)
    assert user.role is UserRole.ATTORNEY
    assert user.tenant_id == "tenant_b"


# ---------------------------------------------------------------------------
# Mode routing
# ---------------------------------------------------------------------------
def test_get_oidc_provider_routes_on_mode(monkeypatch):
    monkeypatch.setattr(settings, "OIDC_MODE", "keycloak")
    monkeypatch.setattr(settings, "OIDC_KEYCLOAK_CLIENT_SECRET", "s")
    kc_mod._PROVIDER_CACHE.clear()
    provider = auth_mod.get_oidc_provider()
    assert isinstance(provider, KeycloakOIDCProvider)

    monkeypatch.setattr(settings, "OIDC_MODE", "stub")
    assert isinstance(auth_mod.get_oidc_provider(), auth_mod.StubOIDCProvider)

    monkeypatch.setattr(settings, "OIDC_MODE", "bogus")
    with pytest.raises(IdpError, match="unknown OIDC_MODE"):
        auth_mod.get_oidc_provider()


def test_provider_cache_invalidates_on_settings_change(monkeypatch):
    monkeypatch.setattr(settings, "OIDC_MODE", "keycloak")
    monkeypatch.setattr(settings, "OIDC_KEYCLOAK_CLIENT_SECRET", "s1")
    kc_mod._PROVIDER_CACHE.clear()
    p1 = auth_mod.get_oidc_provider()
    assert auth_mod.get_oidc_provider() is p1  # cached
    monkeypatch.setattr(settings, "OIDC_KEYCLOAK_CLIENT_SECRET", "s2")
    assert auth_mod.get_oidc_provider() is not p1  # new config -> new provider
    kc_mod._PROVIDER_CACHE.clear()
