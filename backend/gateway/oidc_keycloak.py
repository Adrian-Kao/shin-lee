"""Real Keycloak OIDC provider (Q12 P0 — replaces the stub IdP).

Wired by ``backend/gateway/auth.py:get_oidc_provider()`` when
``OIDC_MODE=keycloak``. Implements the same ``OIDCProvider`` seam the stub
uses, so the gateway handlers (state/nonce CSRF, uniform-401 collapse, audit
row, role/tenant privilege boundary in ``_resolve_idp_user``) are UNCHANGED —
this module only swaps the "validate an authorization code" step for the real
thing:

    1. Discovery   — {issuer}/.well-known/openid-configuration (cached; the
                     doc's `issuer` must equal the configured issuer).
    2. Exchange    — POST code + redirect_uri + client credentials to the
                     token_endpoint (client_secret_post).
    3. Verify      — ID-token signature against the realm JWKS (PyJWT RS256;
                     JWKS fetched over the same HTTP client and cached, with
                     one refetch on unknown `kid` to survive key rotation),
                     plus iss / aud / exp / iat / nonce pinning.
    4. Map         — claims -> ``IdpIdentity`` (subject / tenant / role
                     HINTS). Final role/tenant authority stays server-side in
                     ``auth._resolve_idp_user``: known users pin to ``_USERS``
                     (so the case ACL — invariant #6 — is untouched), unknown
                     users can never self-assert AUDITOR / IT_ADMIN.

Identity-mapping decisions (documented for the realm operator):

* **subject** = ``preferred_username`` (fallback ``sub``). Keycloak's ``sub``
  is a realm-scoped UUID; the gateway's user table, case ACL and audit chain
  key on stable usernames (alice / bob / carol / audit_dave), so the realm's
  usernames ARE the join key. A realm that can't guarantee unique usernames
  must add a protocol mapper that overrides ``preferred_username``.
* **role hint** precedence: flat ``OIDC_ROLE_CLAIM`` claim (protocol mapper)
  -> ``resource_access.<client>.roles`` (client roles — what the shipped
  realm import uses) -> ``realm_access.roles``. Within a list, the FIRST
  match in priority order ``attorney > paralegal > auditor > it_admin`` wins:
  everyday assertable roles outrank privileged ones so a user holding e.g.
  [attorney, auditor] still gets a usable attorney hint (an unknown user's
  auditor hint would be downgraded to paralegal by ``_resolve_idp_user``
  anyway — privileged roles only ever come from the server-side ``_USERS``).
* **tenant hint** = ``OIDC_TENANT_CLAIM`` claim (user-attribute protocol
  mapper; fallback claim name ``tenant``). Honoured only for unknown users —
  known users pin to their on-file tenant.

Every failure raises ``IdpError`` (network, non-200, bad signature, claim
mismatch …); the gateway handler collapses all of them to a uniform 401 and
logs the specific reason server-side, exactly like the stub path.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from urllib.parse import urlencode

import httpx
import jwt

# Safe at module level: auth.py only imports THIS module lazily (inside
# get_oidc_provider), so there is no import cycle.
from backend.gateway.auth import IdpError, IdpIdentity, OIDCProvider
from backend.shared.config import settings

logger = logging.getLogger(__name__)

# Signature algorithms we accept on the ID token. Keycloak signs RS256 by
# default; the realm can be switched to ES256/PS256 without touching this.
# "none" / HS* are NEVER accepted (HS would let anyone who knows the client
# secret — or worse, an attacker exploiting the classic alg-confusion bug —
# forge identities).
_ACCEPTED_ALGS = ("RS256", "ES256", "PS256", "RS384", "RS512")

# Role-hint priority (see module docstring): everyday assertable roles first.
_ROLE_PRIORITY = ("attorney", "paralegal", "auditor", "it_admin")

# How long a cached discovery document / JWKS is trusted before refetch.
_DISCOVERY_TTL_SEC = 3600.0


def _idp_error(msg: str) -> Exception:
    return IdpError(msg)


def extract_role_hint(claims: dict, client_id: str, role_claim: str = "role") -> str | None:
    """Map ID-token claims to a role hint (one of the four gateway roles).

    Precedence: flat ``role_claim`` (str or list) -> client roles under
    ``resource_access[client_id].roles`` -> ``realm_access.roles``. The first
    source that yields ANY recognised role wins; within a source, priority is
    ``_ROLE_PRIORITY``. Unrecognised role strings are ignored (never an
    error — a Keycloak user may carry unrelated realm roles like
    ``offline_access``). Returns ``None`` when nothing matches, which the
    caller resolves to the least-privilege default downstream.
    """
    sources: list[list[str]] = []
    flat = claims.get(role_claim)
    if isinstance(flat, str):
        sources.append([flat])
    elif isinstance(flat, list):
        sources.append([r for r in flat if isinstance(r, str)])
    resource_access = claims.get("resource_access")
    if isinstance(resource_access, dict):
        client_block = resource_access.get(client_id)
        if isinstance(client_block, dict) and isinstance(client_block.get("roles"), list):
            sources.append([r for r in client_block["roles"] if isinstance(r, str)])
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict) and isinstance(realm_access.get("roles"), list):
        sources.append([r for r in realm_access["roles"] if isinstance(r, str)])

    for roles in sources:
        present = {r.strip().lower() for r in roles}
        for candidate in _ROLE_PRIORITY:
            if candidate in present:
                return candidate
    return None


def extract_tenant_hint(claims: dict, tenant_claim: str = "tenant_id") -> str | None:
    """Tenant hint from the configured claim, falling back to ``tenant``.

    Keycloak protocol mappers for single-valued user attributes can still emit
    a one-element list depending on mapper config — accept both shapes.
    """
    for name in (tenant_claim, "tenant"):
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
            return value[0].strip()
    return None


class KeycloakOIDCProvider(OIDCProvider):
    """``OIDCProvider`` backed by a real Keycloak realm.

    Network surface is the injected ``http_client`` (tests pass an
    ``httpx.Client(transport=httpx.MockTransport(...))`` so the unit suite
    runs fully offline; production uses a real client with
    ``OIDC_HTTP_TIMEOUT_SEC``).
    """

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client: httpx.Client | None = None,
        role_claim: str | None = None,
        tenant_claim: str | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http_client or httpx.Client(timeout=settings.OIDC_HTTP_TIMEOUT_SEC)
        self._role_claim = role_claim or settings.OIDC_ROLE_CLAIM
        self._tenant_claim = tenant_claim or settings.OIDC_TENANT_CLAIM
        self._lock = threading.Lock()
        self._discovery: dict | None = None
        self._discovery_at = 0.0
        self._jwks: jwt.PyJWKSet | None = None
        self._jwks_at = 0.0

    # ------------------------------------------------------------------
    # Discovery + JWKS (cached, TTL-bounded)
    # ------------------------------------------------------------------
    def discovery(self) -> dict:
        """Fetch (or return cached) the realm's discovery document."""
        with self._lock:
            if self._discovery is not None and time.time() - self._discovery_at < _DISCOVERY_TTL_SEC:
                return self._discovery
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
            doc = resp.json()
        except Exception as exc:  # noqa: BLE001 — every flavour is the same outcome
            raise _idp_error(f"keycloak: discovery fetch failed ({url}): {exc}") from exc
        # The discovery doc is attacker-relevant input if DNS/proxy is ever
        # wrong — pin its self-declared issuer to the configured one before
        # trusting any endpoint URL inside it.
        if doc.get("issuer") != self._issuer:
            raise _idp_error(
                f"keycloak: discovery issuer mismatch (got {doc.get('issuer')!r}, "
                f"want {self._issuer!r})"
            )
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(doc.get(field), str) or not doc[field]:
                raise _idp_error(f"keycloak: discovery document missing {field}")
        with self._lock:
            self._discovery = doc
            self._discovery_at = time.time()
        return doc

    def _get_jwks(self, *, force_refresh: bool = False) -> jwt.PyJWKSet:
        with self._lock:
            fresh = self._jwks is not None and time.time() - self._jwks_at < _DISCOVERY_TTL_SEC
            if fresh and not force_refresh:
                return self._jwks  # type: ignore[return-value]
        jwks_uri = self.discovery()["jwks_uri"]
        try:
            resp = self._http.get(jwks_uri)
            resp.raise_for_status()
            jwks = jwt.PyJWKSet.from_dict(resp.json())
        except Exception as exc:  # noqa: BLE001
            raise _idp_error(f"keycloak: JWKS fetch failed ({jwks_uri}): {exc}") from exc
        with self._lock:
            self._jwks = jwks
            self._jwks_at = time.time()
        return jwks

    def _signing_key_for(self, id_token: str):
        """Resolve the JWK matching the token's ``kid``; refetch once on miss
        so an in-flight Keycloak key rotation doesn't strand logins for the
        cache TTL."""
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise _idp_error(f"keycloak: undecodable ID token header: {exc}") from exc
        kid = header.get("kid")
        if not kid:
            raise _idp_error("keycloak: ID token has no kid")

        def _find(jwks: jwt.PyJWKSet):
            for key in jwks.keys:
                if key.key_id == kid:
                    return key
            return None

        key = _find(self._get_jwks())
        if key is None:
            key = _find(self._get_jwks(force_refresh=True))
        if key is None:
            raise _idp_error(f"keycloak: no JWKS key matches kid={kid!r}")
        return key.key

    # ------------------------------------------------------------------
    # Authorize URL (consumed by /v1/auth/oidc/begin)
    # ------------------------------------------------------------------
    def authorize_url(self, *, state: str, nonce: str) -> str:
        """Real authorize endpoint URL carrying state + nonce + redirect_uri."""
        endpoint = self.discovery()["authorization_endpoint"]
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{endpoint}?{query}"

    # ------------------------------------------------------------------
    # Code -> token -> verified identity (consumed by the callback handler)
    # ------------------------------------------------------------------
    def exchange_code(self, code: str, expected_nonce: str) -> IdpIdentity:
        """OIDCProvider seam: authorization code -> validated ``IdpIdentity``."""
        if not code:
            raise _idp_error("keycloak: empty authorization code")
        if not self._client_secret:
            # Confidential client without a secret can never exchange — loud
            # server-side reason, uniform 401 to the caller.
            raise _idp_error("keycloak: OIDC_KEYCLOAK_CLIENT_SECRET is not configured")
        token_endpoint = self.discovery()["token_endpoint"]
        try:
            resp = self._http.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise _idp_error(f"keycloak: token exchange failed: {exc}") from exc
        if resp.status_code != 200:
            # Body is IdP-controlled; log a bounded slice, never echo to caller.
            raise _idp_error(
                f"keycloak: token endpoint returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            id_token = resp.json().get("id_token")
        except Exception as exc:  # noqa: BLE001
            raise _idp_error(f"keycloak: non-JSON token response: {exc}") from exc
        if not id_token:
            raise _idp_error("keycloak: token response has no id_token (is scope=openid set?)")

        claims = self.verify_id_token(id_token, expected_nonce=expected_nonce)

        subject = claims.get("preferred_username") or claims.get("sub")
        if not subject:
            raise _idp_error("keycloak: ID token has neither preferred_username nor sub")
        return IdpIdentity(
            subject=str(subject),
            issuer=str(claims["iss"]),
            tenant_hint=extract_tenant_hint(claims, self._tenant_claim),
            role_hint=extract_role_hint(claims, self._client_id, self._role_claim),
        )

    def verify_id_token(self, id_token: str, *, expected_nonce: str | None) -> dict:
        """JWKS signature + iss/aud/exp/iat/nonce validation -> claims dict.

        ``expected_nonce=None`` skips ONLY the nonce binding — used by the live
        smoke/diagnostic path where the token came from a password grant (no
        nonce in that flow). ``exchange_code`` always passes the real nonce.
        """
        key = self._signing_key_for(id_token)
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=list(_ACCEPTED_ALGS),
                audience=self._client_id,
                issuer=self._issuer,
                leeway=settings.IDP_CLOCK_SKEW_SEC,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise _idp_error(f"keycloak: ID token rejected: {exc}") from exc
        if expected_nonce is not None:
            nonce = claims.get("nonce")
            if not nonce or not hmac.compare_digest(str(nonce), str(expected_nonce)):
                raise _idp_error("keycloak: nonce mismatch")
        # azp (authorized party) must be us when present — defends against an
        # ID token minted for another client that happens to list us in aud.
        azp = claims.get("azp")
        if azp is not None and azp != self._client_id:
            raise _idp_error(f"keycloak: azp mismatch (got {azp!r})")
        return claims


# ---------------------------------------------------------------------------
# Module-level provider cache so the discovery/JWKS caches survive across
# requests. Keyed on the settings tuple so a test that monkeypatches settings
# gets a fresh provider instead of a stale cache.
# ---------------------------------------------------------------------------
_PROVIDER_CACHE: dict[tuple, KeycloakOIDCProvider] = {}
_PROVIDER_LOCK = threading.Lock()


def get_keycloak_provider() -> KeycloakOIDCProvider:
    key = (
        settings.OIDC_KEYCLOAK_ISSUER,
        settings.OIDC_KEYCLOAK_CLIENT_ID,
        settings.OIDC_KEYCLOAK_CLIENT_SECRET,
        settings.OIDC_REDIRECT_URI,
        settings.OIDC_ROLE_CLAIM,
        settings.OIDC_TENANT_CLAIM,
    )
    with _PROVIDER_LOCK:
        provider = _PROVIDER_CACHE.get(key)
        if provider is None:
            provider = KeycloakOIDCProvider(
                issuer=settings.OIDC_KEYCLOAK_ISSUER,
                client_id=settings.OIDC_KEYCLOAK_CLIENT_ID,
                client_secret=settings.OIDC_KEYCLOAK_CLIENT_SECRET,
                redirect_uri=settings.OIDC_REDIRECT_URI,
            )
            _PROVIDER_CACHE.clear()  # at most one live provider config at a time
            _PROVIDER_CACHE[key] = provider
        return provider
