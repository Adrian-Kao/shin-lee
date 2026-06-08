"""Gateway auth (Q12).

Three IdP modes are supported in production: built-in / OIDC SAML / magic link.
POC simplifies to JWT — built-in login (`/v1/auth/login`) and the magic-link
flow (`issue_magic_token` / `consume_magic_token`, wired to
`/v1/auth/magic/request` + `/v1/auth/magic/consume`) are implemented here;
OIDC/SAML remain TODO. The **case_id check** is the part that matters
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

import hashlib
import hmac
import ipaddress
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from backend.gateway import revocation
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


# ---------------------------------------------------------------------------
# Password hashing (Security Chunk A — C-1, H-8).
#
# ⚠ POC ONLY — NOT PRODUCTION-SAFE FOR REAL USER PASSWORDS ⚠
#
# We use sha256 + 16-byte hex salt + hmac.compare_digest. This is FINE for
# the demo accounts (passwords `demo-{user_id}` are published in
# .env.example, so brute-force cost is moot). For real user passwords you
# MUST switch to a proper KDF — argon2id (preferred), bcrypt, or scrypt —
# because sha256 is rainbow-table-vulnerable for short passwords.
#
# When the demo accounts are replaced with real IdP-backed users
# (CLAUDE.md §5 P0 "OIDC integration"), the hash storage moves to the IdP
# and these helpers can be DELETED. Do NOT reuse this helper for new
# user-supplied passwords — the docstring is its only safety guard.
#
# Day 8 post-review (Important #3): warning made loud per Chunk A/B
# reviewer feedback so a future contributor can't quietly extend this
# to a real auth path.
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: Optional[str] = None) -> str:
    """Return ``'salt:hash'`` for storage.

    ``salt`` is 16-byte hex by default. Hex (not raw bytes) so the stored
    value is always pure-ASCII and round-trips through any text channel.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time compare via ``hmac.compare_digest``.

    Returns ``False`` (not an exception) for malformed/empty stored strings
    so the caller always gets a single uniform "wrong creds" path and there
    is no shape oracle the attacker can probe.
    """
    if not stored or ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    candidate = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# POC: in-memory user store. Production: replace with IdP middleware.
#
# Each entry pairs a `User` (the runtime context object that auth_dependency
# returns and that every downstream module type-hints against) with a
# `password_hash` for credentialed login. Default demo passwords are
# `demo-{user_id}` and are documented in `.env.example` — for stakeholder
# demos the operator usually sets `DEMO_LOGIN_SECRET` instead so the SPA can
# "click Alice" without typing.
# ---------------------------------------------------------------------------
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

# Password hashes for the demo users above. Kept as a sidecar map so the
# `User` Pydantic model (shared with the AI Engine, frontend, etc.) does
# NOT grow a `password_hash` field — that would leak the hash into every
# `User.model_dump()` call and into the JWT payload echo.
#
# Each hash is computed at import time so the docs ("default password is
# `demo-{uid}`") stay the single source of truth — change the password
# convention in one place and every hash regenerates.
_PASSWORD_HASHES: dict[str, str] = {
    uid: _hash_password(f"demo-{uid}") for uid in _USERS
}


def _get_user(user_id: str) -> Optional[User]:
    """Lookup helper — returns the demo user or None.

    Exists as a named function (rather than callers reaching into `_USERS`
    directly) so the login path has a single chokepoint to instrument /
    rate-limit / audit when this becomes a real user store.
    """
    return _USERS.get(user_id)


def _get_password_hash(user_id: str) -> Optional[str]:
    """Return the stored password hash, or ``None`` for unknown users."""
    return _PASSWORD_HASHES.get(user_id)


def _internal_headers() -> dict[str, str]:
    """Headers the gateway adds to every outbound httpx call to the AI Engine.

    Security Chunk A — C-2. AI Engine refuses any non-`/v1/health` request
    that lacks `X-Internal-Token`. The token is server-side only — never
    forwarded from a client header — so an attacker who reaches :8011
    directly cannot replay one captured from the SPA.

    Returns an empty dict when `INTERNAL_TOKEN` is unset, which matches the
    AI Engine middleware's "empty + mock = permit" rule for local pytest /
    in-process ASGITransport.
    """
    token = settings.INTERNAL_TOKEN
    if not token:
        return {}
    return {"X-Internal-Token": token}

# POC: which case_ids each user has access to.
# Production: query from case-management system per request.
_CASE_ACL: dict[str, set[str]] = {
    "alice": {"CASE-2025-001", "CASE-2025-002", "CASE-2025-003"},
    "bob": {"CASE-2025-001", "CASE-2025-002"},
    "carol": set(),  # IT admin doesn't access cases by default
    "audit_dave": {"*"},  # auditor sees all in their tenant
}



# H-5 (phase 3): algorithm-aware key selection. HS* is symmetric (one shared
# secret); RS*/ES*/PS* are asymmetric — sign with the private key, verify with
# the public key, so a leaked verifier (e.g. another service holding the public
# key) cannot mint tokens. Default stays HS256 for the POC; set JWT_ALGO=RS256 +
# JWT_PRIVATE_KEY / JWT_PUBLIC_KEY (PEM) to switch with zero call-site changes.
def _signing_key() -> str:
    return settings.JWT_SECRET if settings.JWT_ALGO.startswith("HS") else settings.JWT_PRIVATE_KEY


def _verifying_key() -> str:
    return settings.JWT_SECRET if settings.JWT_ALGO.startswith("HS") else settings.JWT_PUBLIC_KEY


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
        # H-5: issuer + audience pin the token to this service estate.
        "iss": settings.JWT_ISS,
        "aud": settings.JWT_AUD,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRES_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=settings.JWT_ALGO)


def verify_token(token: str) -> User:
    try:
        # H-5: enforce issuer + audience. A token lacking either claim (e.g. a
        # magic-link token, or one minted by another service sharing the
        # secret) raises InvalidTokenError → 401.
        payload = jwt.decode(
            token,
            _verifying_key(),
            algorithms=[settings.JWT_ALGO],
            audience=settings.JWT_AUD,
            issuer=settings.JWT_ISS,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")

    # A magic-link token must NEVER be accepted as a Bearer session token even
    # if it somehow carries the right aud/iss. (The module docstring above
    # claimed verify_token already rejected magic tokens; it did not — H-5 adds
    # the guard for real.)
    if payload.get("typ") == _MAGIC_TOKEN_TYP:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token: wrong type")

    # H-5: revocation (logout / leaked-token kill switch).
    jti = payload.get("jti")
    if jti is not None and revocation.is_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token revoked")

    user_id = payload.get("sub")
    if user_id not in _USERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return _USERS[user_id]


def revoke_token(token: str) -> bool:
    """Revoke a session token by recording its jti (H-5: logout / kill switch).

    Best-effort: a token we cannot decode (already expired / tampered / wrong
    aud-iss) needs no revoking, so we return ``False`` rather than raise — the
    caller's logout still succeeds idempotently. Returns ``True`` when a live
    jti was added to the revocation set.
    """
    try:
        payload = jwt.decode(
            token,
            _verifying_key(),
            algorithms=[settings.JWT_ALGO],
            audience=settings.JWT_AUD,
            issuer=settings.JWT_ISS,
        )
    except jwt.InvalidTokenError:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    # Expire the revocation entry when the token itself would expire — no point
    # holding a jti past its TTL (the token is rejected on expiry anyway), and
    # it keeps the store bounded.
    exp = payload.get("exp")
    ttl = int(exp - time.time()) if exp else settings.JWT_EXPIRES_MIN * 60
    if ttl <= 0:
        return False  # already expired — nothing to revoke
    revocation.revoke(jti, ttl)
    return True


# ---------------------------------------------------------------------------
# Q12 — Magic-link auth flow (fills the named `/auth/magic` stub).
#
# The small-firm path: a <10-person practice with no IdP and no appetite for
# password management. The user asks for a link, clicks it, and is logged in.
#
# Token scheme: we reuse the existing JWT machinery (same HS256 signature with
# `settings.JWT_SECRET`) so the token is tamper-evident and self-expiring with
# zero extra crypto. A magic token is distinguished from a session token by a
# `typ: "magic"` claim — `verify_token` only accepts session tokens (no `typ`
# claim or `typ != "magic"`), and `consume_magic_token` only accepts magic
# tokens, so a magic token can NEVER be presented as a Bearer session token and
# vice-versa. Each magic token carries a unique `jti`; once consumed that `jti`
# is recorded so a replay (clicking the same link twice, or an attacker who
# captured it from a log) is rejected.
#
# Single-use store: an in-memory set, POC-only. In production this MUST be
# Redis with a TTL equal to MAGIC_LINK_TTL_MIN (so the consumed-set is bounded
# and survives a gateway restart / multiple replicas). The in-memory set here
# is per-process: it is correct for a single-replica POC but would let a replay
# through on a second replica, which is exactly why prod needs the shared store.
# ---------------------------------------------------------------------------
_MAGIC_TOKEN_TYP = "magic"

# Consumed magic-token jtis. POC: in-memory, unbounded (entries are short-lived
# in practice because a jti is only useful until its token expires). Production:
# Redis SET with `EXPIRE jti <MAGIC_LINK_TTL_MIN*60>` so it self-prunes and is
# shared across replicas.
_CONSUMED_MAGIC_JTIS: set[str] = set()


def issue_magic_token(user_id: str) -> str:
    """Issue a short-TTL, single-use signed magic-link token for ``user_id``.

    Reuses the JWT machinery (HS256 over ``settings.JWT_SECRET``) with a
    distinct ``typ: "magic"`` claim and a unique ``jti``. TTL is
    ``settings.MAGIC_LINK_TTL_MIN`` minutes.

    Unknown ``user_id`` is handled exactly like ``issue_token`` /
    ``/v1/auth/login`` — it raises so the caller never mints a usable token for
    a non-existent user. The caller (``/v1/auth/magic/request``) catches this
    and returns the SAME generic 200 shape it returns for known users, so the
    endpoint is not a user-enumeration oracle (see H-8 handling on the login
    endpoint).
    """
    if user_id not in _USERS:
        # Mirror issue_token's contract: refuse unknown users. The request
        # endpoint converts this into a uniform "if the user exists…" response
        # so existence is never leaked.
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown user: {user_id}")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "typ": _MAGIC_TOKEN_TYP,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.MAGIC_LINK_TTL_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=settings.JWT_ALGO)


def magic_token_jti(token: str) -> Optional[str]:
    """Best-effort extract the ``jti`` of a magic token for AUDIT use only.

    Returns the ``jti`` claim without verifying signature/expiry (we only want
    a stable, non-secret correlation id for the audit row). Returns ``None`` if
    the token can't be parsed. NEVER pass the raw token to the audit writer —
    the jti is the safe correlation handle; the token itself is a credential.
    """
    try:
        payload = jwt.decode(
            token,
            _verifying_key(),
            algorithms=[settings.JWT_ALGO],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return None
    jti = payload.get("jti")
    return str(jti) if jti else None


def consume_magic_token(token: str) -> str:
    """Validate + single-use-consume a magic token; return its ``user_id``.

    Checks, in order: signature + expiry (via ``jwt.decode``), ``typ`` claim,
    known ``sub``, presence of ``jti``, and that the ``jti`` has not already
    been consumed. On the first successful consume the ``jti`` is recorded so a
    second attempt with the same token raises 401 (replay defence).

    Raises ``HTTPException(401)`` with a UNIFORM message on ANY failure
    (bad signature, expired, wrong typ, unknown user, missing jti, replay) so
    the caller cannot use the failure reason as an oracle.
    """
    uniform_401 = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "invalid or expired magic link"
    )
    try:
        payload = jwt.decode(
            token, _verifying_key(), algorithms=[settings.JWT_ALGO]
        )
    except jwt.InvalidTokenError:
        # Covers ExpiredSignatureError (subclass) + tamper/bad-signature.
        raise uniform_401

    if payload.get("typ") != _MAGIC_TOKEN_TYP:
        # A session token (or any non-magic token) must not be consumable here.
        raise uniform_401

    user_id = payload.get("sub")
    if user_id not in _USERS:
        raise uniform_401

    jti = payload.get("jti")
    if not jti:
        # A magic token with no jti has no single-use identity — refuse it
        # rather than allow an un-revocable, infinitely-replayable token.
        raise uniform_401

    # Single-use check + claim. Not atomic in this in-memory POC; production's
    # Redis store would use `SET jti 1 NX EX <ttl>` so the check-and-set is a
    # single atomic op immune to the consume-twice race.
    if jti in _CONSUMED_MAGIC_JTIS:
        raise uniform_401
    _CONSUMED_MAGIC_JTIS.add(jti)
    return user_id


def authorize_case_access(user: User, case_id: Optional[str]) -> None:
    """Q12: legal compliance — confirm user has access to this specific case.

    Raises 403 if not.  This is the conflict-of-interest 看錯案件 防呆.

    Important: the dependency-level call (``auth_dependency``) only inspects
    the X-Case-Id header and the ``case_id`` query string. It deliberately
    does NOT peek into the request body — Starlette consumes the body stream
    when Pydantic parses it, and an attempt to read it twice silently
    deadlocks the request. That means JSON POST handlers carrying ``case_id``
    in the body (``/v1/oa/analyze``, ``/v1/oa/upload``, ``/v1/audit/append``)
    MUST re-invoke ``authorize_case_access(user, body.case_id)`` themselves
    after Pydantic has parsed the body. Without that explicit re-check, a
    client omitting the X-Case-Id header (frontend always sends it; a
    malicious client doesn't have to) would silently bypass ACL — fix for
    C-3 in the security audit. The handler call is the load-bearing one;
    the dependency call only catches GET endpoints with no body.
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
        # H-1 fix: an upstream-supplied tenant is NEVER honoured for a known
        # user — the on-file tenant is authoritative, exactly like role above.
        # Otherwise a bug or an attacker on a trusted IP could re-scope alice
        # into tenant_b's cache namespace, audit rows and masking dictionary
        # under her known identity. Legitimate cross-tenant projects (if ever
        # added) must go through an explicit allow-list, not an arbitrary header.
        if tenant_id != known.tenant_id:
            logger.warning(
                "upstream-auth: SECURITY tenant mismatch for known user_id=%s "
                "(upstream=%s, _USERS=%s) — IGNORING upstream tenant, pinning on-file",
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

    # H-1: for a known user the on-file tenant wins; unknown users (already
    # forced to least-privilege role above) keep their upstream-supplied tenant.
    effective_tenant_id = known.tenant_id if known is not None else tenant_id
    display_name = known.display_name if known is not None else user_id
    daily_quota = known.daily_token_quota if known is not None else 100_000

    user = User(
        user_id=user_id,
        tenant_id=effective_tenant_id,
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

    # Case-level access check.
    #
    # We only consult X-Case-Id header / ?case_id= query string here. We do
    # NOT peek into the request body — the previous implementation tried to
    # do that via ``request.state._cached_body`` but that attribute was never
    # set anywhere in the codebase, so JSON POSTs that omitted X-Case-Id
    # silently passed ACL even when their body referenced a foreign case_id
    # (security finding C-3). Reading the body stream directly here would
    # block until the request times out, because Starlette only lets the
    # body be consumed once and Pydantic does that during handler binding.
    #
    # Handlers that take a body containing case_id MUST re-invoke
    # ``authorize_case_access(user, body.case_id)`` after Pydantic parses
    # the body. See ``/v1/oa/analyze``, ``/v1/oa/upload`` (X-Case-Id-only;
    # multipart bodies have no JSON case_id) and ``/v1/audit/append``.
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
    authorize_case_access(user, case_id)

    request.state.user = user
    request.state.case_id = case_id
    return user


# ---------------------------------------------------------------------------
# Role-gate dependency factory (Security Chunk C — H-6)
# ---------------------------------------------------------------------------
def require_roles(*allowed_roles: UserRole):
    """Build a FastAPI dependency that 403s when the caller's role is not
    in ``allowed_roles``.

    Usage::

        @app.post("/v1/oa/analyze")
        async def analyze_oa(
            body: AnalysisRequest,
            user: User = Depends(require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)),
        ):
            ...

    The returned dependency wraps ``auth_dependency`` so authentication and
    authorisation happen as a single concern from the endpoint's
    perspective — there is no risk of forgetting to wire auth alongside the
    role check, which would leave the endpoint open.

    Design choices:

    1. **Wraps auth_dependency** — the returned dependency depends on
       ``auth_dependency`` via FastAPI's ``Depends`` mechanism, so role
       checks always run AFTER authentication has succeeded. FastAPI
       caches dependency results per-request, so if an endpoint also wires
       ``Depends(auth_dependency)`` directly the inner call is reused (no
       double JWT decode, no double ACL check).

    2. **403 (not 401)** on role mismatch — the user is authenticated,
       they just lack permission. Status code consistency with the rest
       of the gateway's role gates (e.g. `_AUDIT_APPEND_ROLES` returns 403,
       /v1/audit/recent returns 403, etc.).

    3. **Error message names the user's role + lists allowed roles** —
       gives the operator a clear "who has access" signal without leaking
       case data. The role enum values are public information (they appear
       in the JWT payload).
    """
    from fastapi import Depends as _Depends

    allowed = frozenset(allowed_roles)

    async def _role_dependency(user: User = _Depends(auth_dependency)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user.role.value}' is not permitted on this endpoint. "
                f"Required: one of {sorted(r.value for r in allowed)}.",
            )
        return user

    # Set a function name so FastAPI's docs / debug surface the role list
    # rather than the generic "_role_dependency" closure name.
    _role_dependency.__name__ = (
        f"require_roles_{'_'.join(sorted(r.value for r in allowed))}"
    )
    return _role_dependency
