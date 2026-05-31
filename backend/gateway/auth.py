"""Gateway auth (Q12).

Three IdP modes are supported in production: built-in / OIDC SAML / magic link.
POC simplifies to JWT — but the **case_id check** is the part that matters
most and that we keep verbatim:

    Every API call must carry case_id.
    The user must have access to that case.
    This avoids conflict-of-interest 看錯案件.

This is a real legal compliance requirement, not generic auth.

--------------------------------------------------------------------------
Compat Refactor 3 — digiRunner-style upstream-trust auth
--------------------------------------------------------------------------

Production deployment places digiRunner in front of this gateway:

    client -> digiRunner (OIDC / SAML / OAuth validation) -> gateway

digiRunner validates the IdP exchange at its own layer, then forwards the
validated identity to us via headers:

    x-user-id      validated user id (required for upstream path)
    x-tenant-id    validated tenant id (required for upstream path)
    x-user-role    optional UserRole.value (defaults to PARALEGAL — least
                   privilege — when missing or unrecognised)

Security model: these headers are HONOURED ONLY when the immediate TCP peer
(`request.client.host`) is in `settings.TRUSTED_UPSTREAM_IPS`. Any request
from outside that list is forced down the JWT path even if it includes
spoofed `x-user-id` headers — so the only attacker who can fake an identity
is one already inside the trusted network segment (and at that point they
own the box anyway).

We deliberately consult `request.client.host` rather than
`X-Forwarded-For`: the latter is itself a header and is therefore spoofable
by the very same attacker we are trying to block. `request.client.host` is
the kernel-observed peer address, which the attacker cannot forge from off
the wire. The trade-off is that this assumes digiRunner is the immediate
upstream — if a second proxy is inserted between digiRunner and us, the
deployment must either (a) terminate that proxy on the trusted-IP list or
(b) swap to a verified-X-Forwarded-For scheme.

The JWT path remains as a fallback for two scenarios:
  1. Local development (no digiRunner running — `python -m uvicorn ...`).
  2. The /v1/auth/login demo flow used during prospect demos.

--------------------------------------------------------------------------
Role-assertion whitelist (Compat Refactor 3 follow-up)
--------------------------------------------------------------------------

The upstream may freely assert ATTORNEY or PARALEGAL on an unknown user
(those are the everyday roles digiRunner's IdP will surface). It may NOT
assert AUDITOR or IT_ADMIN on an unknown user_id — those privileged roles
must come from the local ``_USERS`` table (server-controlled). Without
this restriction, anyone with a foothold on a trusted IP could claim
auditor by setting a single header and read the entire append-only audit
log of every tenant.

For known users (those listed in ``_USERS``), the local table wins
unconditionally — the upstream role header is ignored. This means alice
is always an attorney even if digiRunner forgets to set the header (or a
bug there sets it to ``it_admin``).

--------------------------------------------------------------------------
Synthetic user_id quota DoS
--------------------------------------------------------------------------

The upstream can mint arbitrary user_ids on the fly (e.g. an attacker on
the trusted segment iterating user-N for large N). Each synthetic user
gets a fresh ``daily_token_quota`` bucket in rate_limit.py, which a naive
caller might exploit to bypass the per-user cap.

This is bounded by the per-tenant monthly cap (``TENANT_MONTHLY_TOKENS``),
which is checked on the same path before any LLM call. The tenant-level
cap is the real safety net here — per-user quotas are a UX nicety, not a
security boundary against an attacker already inside a trusted IP. If
that threat model expands, the right fix is to require a signed claim
(JWT in ``x-upstream-auth-token``) rather than to inflate the user-quota
machinery.
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from backend.shared.config import _parse_trusted_ips, settings
from backend.shared.models import User, UserRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roles that an UPSTREAM (digiRunner) may assert via x-user-role header.
# AUDITOR / IT_ADMIN are intentionally EXCLUDED — they must come from the
# local _USERS table (or a future signed-claim mechanism). Otherwise anyone
# with a trusted-IP foothold can claim auditor role and read the audit log.
# ---------------------------------------------------------------------------
_UPSTREAM_ASSERTABLE_ROLES: frozenset[UserRole] = frozenset({
    UserRole.ATTORNEY,
    UserRole.PARALEGAL,
})

# Single source of truth for the least-privilege fallback role.
_UPSTREAM_DEFAULT_ROLE: UserRole = UserRole.PARALEGAL

# POC: in-memory user store. Production: replace with IdP middleware.
_USERS: dict[str, User] = {
    "alice": User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice Chen (Attorney)",
        daily_token_quota=200_000,
    ),
    "bob": User(
        user_id="bob",
        tenant_id="tenant_a",
        role=UserRole.PARALEGAL,
        display_name="Bob Lin (Paralegal)",
        daily_token_quota=50_000,
    ),
    "carol": User(
        user_id="carol",
        tenant_id="tenant_b",
        role=UserRole.IT_ADMIN,
        display_name="Carol Wang (IT Admin)",
        daily_token_quota=10_000,
    ),
    "audit_dave": User(
        user_id="audit_dave",
        tenant_id="tenant_a",
        role=UserRole.AUDITOR,
        display_name="Dave Yu (Auditor)",
        daily_token_quota=5_000,
    ),
}

# POC: which case_ids each user has access to.
# Production: query from case-management system per request.
_CASE_ACL: dict[str, set[str]] = {
    "alice": {"CASE-2025-001", "CASE-2025-002", "CASE-2025-003"},
    "bob": {"CASE-2025-001", "CASE-2025-002"},
    "carol": set(),  # IT admin doesn't access cases by default
    "audit_dave": {"*"},  # auditor sees all in their tenant
}


def issue_token(user_id: str) -> str:
    """Sign a short-lived JWT for the user."""
    if user_id not in _USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown user: {user_id}")
    user = _USERS[user_id]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.user_id,
        "tenant_id": user.tenant_id,
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRES_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)


def verify_token(token: str) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")

    user_id = payload.get("sub")
    if user_id not in _USERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return _USERS[user_id]


def authorize_case_access(user: User, case_id: Optional[str]) -> None:
    """Q12: legal compliance — confirm user has access to this specific case.

    Raises 403 if not.  This is the conflict-of-interest 看錯案件 防呆.
    """
    if not case_id:
        # Some endpoints (e.g. /health) don't need case_id.
        return
    allowed = _CASE_ACL.get(user.user_id, set())
    if "*" in allowed or case_id in allowed:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"user {user.user_id} has no access to {case_id}. "
        "If this is a new case, an authorised attorney must grant access first.",
    )


def _normalise_client_ip(client_host: Optional[str]) -> Optional[ipaddress._BaseAddress]:
    """Return ``client_host`` as an ``ipaddress.IPv4Address`` /
    ``IPv6Address``, collapsing IPv4-mapped-IPv6 (``::ffff:127.0.0.1``)
    down to its IPv4 form so trust-list comparisons work on dual-stack
    sockets. Returns ``None`` if the value cannot be parsed (which the
    caller treats as untrusted).

    uvicorn on a dual-stack listener surfaces v4 peers as ``::ffff:<v4>``,
    so without this normalisation a trust list of ``["127.0.0.1"]`` would
    silently reject the perfectly-legitimate loopback peer.
    """
    if not client_host:
        return None
    try:
        addr = ipaddress.ip_address(client_host)
    except ValueError:
        # Non-IP strings such as TestClient's "testclient" sentinel fall
        # through to the string-based fallback path in the caller.
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_trusted_peer(client_host: Optional[str]) -> bool:
    """Decide whether ``client_host`` is in the trust list, accommodating
    both real IPs (compared as ``ip_address`` objects to handle the
    IPv4-mapped-IPv6 case) and the synthetic TestClient string
    ``testclient`` (compared as a literal string). Tests monkeypatch
    ``settings.TRUSTED_UPSTREAM_IPS`` directly, so we re-derive the
    parsed set on every call rather than caching it module-side.
    """
    if not client_host:
        return False
    raw_trust = settings.TRUSTED_UPSTREAM_IPS
    if not raw_trust:
        return False
    # String-literal match first — covers `testclient` and any other
    # non-IP sentinel that tests / opaque ASGI transports may surface.
    if client_host in raw_trust:
        return True
    # IP-address match — parse the trust list lazily so monkeypatched
    # values are honoured. Anything malformed in the trust list raises
    # ValueError here, which would surface as 500; the boot-time check in
    # config.py prevents that from happening in normal startup paths.
    try:
        parsed_trust = _parse_trusted_ips(raw_trust)
    except ValueError:
        return False
    normalised = _normalise_client_ip(client_host)
    if normalised is None:
        return False
    return normalised in parsed_trust


def _user_from_upstream_headers(request: Request) -> Optional[User]:
    """Compat Refactor 3: build a User from digiRunner-injected headers.

    Returns the User when the request comes from a trusted upstream IP AND
    carries the minimum identity headers (x-user-id + x-tenant-id).

    Returns None in every other case — including when the upstream IS
    trusted but the headers are absent — so the caller transparently falls
    back to JWT auth (which handles local dev + the demo login flow).

    Security invariant: the IP-trust check happens BEFORE any header is
    read, so a request from an untrusted IP cannot influence the returned
    User even by sending x-user-id headers.

    Role-resolution rules (see module docstring for rationale):
      * Known user_id (in ``_USERS``): role always comes from the local
        table; the upstream ``x-user-role`` header is ignored.
      * Unknown user_id: only ATTORNEY / PARALEGAL may be asserted from
        upstream; any privileged role (AUDITOR / IT_ADMIN) is silently
        downgraded to PARALEGAL.

    If ``settings.UPSTREAM_AUTH_SHARED_SECRET`` is non-empty, the request
    must also carry a matching ``x-upstream-auth-token`` header or this
    function returns ``None`` (= falls back to JWT path).
    """
    trusted_ips = settings.TRUSTED_UPSTREAM_IPS
    if not trusted_ips:
        return None
    client_ip = request.client.host if request.client else None
    if not _is_trusted_peer(client_ip):
        return None

    # Defence-in-depth shared secret. We compare via hmac.compare_digest
    # to avoid leaking match-length via timing. The header is read AFTER
    # the IP trust check so an untrusted peer can't probe for the secret.
    expected_secret = settings.UPSTREAM_AUTH_SHARED_SECRET
    if expected_secret:
        presented = request.headers.get("x-upstream-auth-token", "")
        if not hmac.compare_digest(presented, expected_secret):
            logger.warning(
                "upstream-auth: shared-secret mismatch from client=%s — "
                "declining upstream path", client_ip,
            )
            return None

    user_id = request.headers.get("x-user-id")
    tenant_id = request.headers.get("x-tenant-id")
    if not (user_id and tenant_id):
        return None

    role_header = request.headers.get("x-user-role")
    known = _USERS.get(user_id)

    # Resolve role.
    if known is not None:
        # Server-controlled assignment wins for known users. This prevents
        # an upstream bug or attacker from demoting alice from attorney
        # to paralegal — or from promoting bob to it_admin.
        role = known.role
        # Cross-tenant audit signal: if upstream claims a different tenant
        # for a known user than what we have on file, log a warning. We
        # don't *block* (that would break legitimate cross-tenant projects
        # if those ever get added) but we do want a trail.
        if tenant_id != known.tenant_id:
            logger.warning(
                "upstream-auth: tenant mismatch for known user_id=%s "
                "(upstream=%s, _USERS=%s) — honouring upstream tenant",
                user_id, tenant_id, known.tenant_id,
            )
    elif role_header:
        try:
            role = UserRole(role_header)
        except ValueError:
            # Unknown role string — degrade to least privilege rather than
            # 500ing the request.
            role = _UPSTREAM_DEFAULT_ROLE
        # Privileged roles must not come from upstream for unknown users.
        # Silently downgrade rather than 401 — an attacker probing the
        # role enum should not learn which strings are "privileged".
        if role not in _UPSTREAM_ASSERTABLE_ROLES:
            role = _UPSTREAM_DEFAULT_ROLE
    else:
        role = _UPSTREAM_DEFAULT_ROLE

    display_name = known.display_name if known is not None else user_id
    daily_quota = known.daily_token_quota if known is not None else 100_000

    user = User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        display_name=display_name,
        daily_token_quota=daily_quota,
    )
    logger.info(
        "upstream-auth: user=%s tenant=%s role=%s client=%s auth_source=upstream",
        user.user_id, user.tenant_id, user.role.value, client_ip,
    )
    return user


async def auth_dependency(request: Request) -> User:
    """FastAPI dependency: extract token, verify, attach user to request.state.

    Auth resolution order (Compat Refactor 3):
      1. Upstream-trust path — request from a `TRUSTED_UPSTREAM_IPS` peer
         carrying `x-user-id` + `x-tenant-id`. Used when digiRunner
         (or any other validated reverse proxy) sits in front of us.
      2. JWT Bearer path — current behaviour, used for local dev and the
         demo login flow.
    """
    upstream_user = _user_from_upstream_headers(request)
    if upstream_user is not None:
        user = upstream_user
    else:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        token = auth_header[7:]
        user = verify_token(token)
        _client_ip = request.client.host if request.client else None
        logger.info(
            "upstream-auth: user=%s tenant=%s role=%s client=%s auth_source=jwt",
            user.user_id, user.tenant_id, user.role.value, _client_ip,
        )

    # Case-level access check
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
    if not case_id and request.method == "POST":
        body = getattr(request.state, "_cached_body", None)
        if body and isinstance(body, dict):
            case_id = body.get("case_id")
    authorize_case_access(user, case_id)

    request.state.user = user
    request.state.case_id = case_id
    return user
