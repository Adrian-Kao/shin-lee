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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
_UPSTREAM_ASSERTABLE_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.ATTORNEY,
        UserRole.PARALEGAL,
    }
)

# Single source of truth for the least-privilege fallback role.
_UPSTREAM_DEFAULT_ROLE: UserRole = UserRole.PARALEGAL


# ---------------------------------------------------------------------------
# Password hashing (Security Chunk A — C-1, H-8; upgraded to argon2id, P1).
#
# New hashes are **argon2id** via ``argon2-cffi`` (the KDF the original
# POC-only docstring demanded before production). Storage format is the PHC
# string argon2-cffi emits (``$argon2id$v=19$m=...,t=...,p=...$salt$hash``).
#
# Backwards compatibility: the original POC scheme was
# ``sha256(salt+password)`` stored as ``"salt:hash"``. ``_verify_password``
# still accepts that legacy format (dispatching on the ``$argon2`` prefix),
# and the login path opportunistically re-hashes a legacy credential to
# argon2id after a successful verification (``_maybe_upgrade_hash``).
#
# Dependency posture: argon2-cffi is listed in backend/requirements.txt, but
# the POC MUST NOT fail to boot when it is absent (e.g. a stripped CI env).
# When the import fails we fall back to the legacy sha256+salt scheme and log
# a LOUD warning — acceptable only because the built-in accounts are the
# published `demo-{user_id}` demo users. Production with real passwords
# requires argon2 installed (or, in Path B, delegates login to the IdP and
# this codepath is unreachable). See docs/OPERATIONS_AND_ONBOARDING.md §2.8.
# ---------------------------------------------------------------------------
try:  # pragma: no cover — exercised indirectly; absence path tested via monkeypatch
    from argon2 import PasswordHasher as _Argon2PasswordHasher
    from argon2 import exceptions as _argon2_exceptions

    # Library defaults (argon2-cffi >= 21): time_cost=3, memory_cost=64MiB,
    # parallelism=4 — at/above the OWASP argon2id minimums. Keep defaults so a
    # library security bump propagates automatically.
    _ARGON2_HASHER: _Argon2PasswordHasher | None = _Argon2PasswordHasher()
except ImportError:  # pragma: no cover — covered by monkeypatched unit test
    _ARGON2_HASHER = None
    _argon2_exceptions = None  # type: ignore[assignment]

_ARGON2_PREFIX = "$argon2"


def _legacy_hash_password(password: str, salt: str | None = None) -> str:
    """LEGACY (pre-argon2) scheme: ``'salt:sha256(salt+password)'``.

    Kept ONLY so (a) old stored hashes keep verifying and (b) the gateway can
    still boot when argon2-cffi is absent. Never call this directly for new
    passwords — go through ``_hash_password``.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _hash_password(password: str, salt: str | None = None) -> str:
    """Hash ``password`` for storage.

    argon2id (PHC string) whenever argon2-cffi is importable. ``salt`` is only
    honoured on the legacy fallback path (argon2 manages its own salt); a
    caller passing an explicit salt gets the legacy format — that parameter
    exists solely for deterministic legacy-fixture construction in tests.
    """
    if _ARGON2_HASHER is not None and salt is None:
        return _ARGON2_HASHER.hash(password)
    if _ARGON2_HASHER is None and salt is None:
        logger.warning(
            "auth: argon2-cffi NOT installed — falling back to the legacy "
            "sha256+salt password scheme. Acceptable for the published demo "
            "accounts only; install argon2-cffi before storing real passwords."
        )
    return _legacy_hash_password(password, salt)


def _verify_password(password: str, stored: str) -> bool:
    """Verify ``password`` against either hash format.

    * ``$argon2…`` → argon2id verification (constant-work KDF).
    * ``salt:hash`` → legacy sha256 compare via ``hmac.compare_digest``.

    Returns ``False`` (never raises) for malformed/empty stored strings or
    any verification failure, so the caller always gets a single uniform
    "wrong creds" path and there is no shape oracle the attacker can probe.
    """
    if not stored:
        return False
    if stored.startswith(_ARGON2_PREFIX):
        if _ARGON2_HASHER is None:
            logger.warning(
                "auth: stored hash is argon2 but argon2-cffi is not installed — "
                "cannot verify; refusing login for this credential."
            )
            return False
        try:
            return _ARGON2_HASHER.verify(stored, password)
        except _argon2_exceptions.VerifyMismatchError:
            return False
        except Exception:  # noqa: BLE001 — malformed hash / internal error
            return False
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    candidate = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return hmac.compare_digest(candidate, expected)


def _needs_rehash(stored: str) -> bool:
    """True when a stored hash should be upgraded on next successful login.

    Covers (a) the legacy ``salt:hash`` format and (b) an argon2 hash whose
    parameters are below the hasher's current policy (argon2-cffi
    ``check_needs_rehash``). Always False when argon2 is unavailable — there
    is nothing better to upgrade to.
    """
    if _ARGON2_HASHER is None or not stored:
        return False
    if not stored.startswith(_ARGON2_PREFIX):
        return True
    try:
        return _ARGON2_HASHER.check_needs_rehash(stored)
    except Exception:  # noqa: BLE001
        return False


def _maybe_upgrade_hash(user_id: str, password: str) -> bool:
    """Opportunistic re-hash after a SUCCESSFUL password verification.

    Call ONLY with a password that just verified — this function trusts the
    caller on that and re-derives a fresh argon2id hash for storage. Returns
    True when the stored hash was upgraded. No-op (False) when argon2 is
    unavailable, the user is unknown, or the hash is already current.
    """
    stored = _PASSWORD_HASHES.get(user_id)
    if stored is None or not _needs_rehash(stored):
        return False
    _PASSWORD_HASHES[user_id] = _ARGON2_HASHER.hash(password)
    logger.info("auth: upgraded stored password hash to argon2id for user_id=%s", user_id)
    return True


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
_PASSWORD_HASHES: dict[str, str] = {uid: _hash_password(f"demo-{uid}") for uid in _USERS}

# A fixed dummy hash used by the login endpoint when the requested user_id is
# unknown, so `_verify_password` performs the SAME work for the unknown-user
# case as for known-user-wrong-password (H-8 timing oracle). Derived through
# `_hash_password` so its format ALWAYS matches the scheme real users are
# stored under — argon2id when available, legacy sha256 otherwise. (A
# format mismatch would reopen the oracle: argon2 verification costs ~10⁵×
# a sha256 round.) The password is fixed/garbage because the only goal is
# identical work factor, not authenticating anyone.
_DUMMY_HASH_FOR_TIMING: str = _hash_password("!patentmind-dummy-timing-equalisation!")


# ---------------------------------------------------------------------------
# Agent F (Day 13F) — runtime registry for FEDERATED users (OIDC / SAML).
#
# A user who logs in via an enterprise IdP but is NOT in the demo ``_USERS``
# table still needs a session: issue_token signs their JWT and verify_token must
# accept it on subsequent requests. We register the resolved (least-privilege)
# User here so verify_token can resolve ``sub`` -> User without a hard-coded
# row. The role/tenant were already pinned by ``_resolve_idp_user`` (a federated
# user can never self-assert AUDITOR/IT_ADMIN), so this registry only ever holds
# safe, server-decided identities. POC: in-memory; production: a real user
# directory keyed off the IdP subject.
# ---------------------------------------------------------------------------
_FEDERATED_USERS: dict[str, User] = {}


def _register_federated_user(user: User) -> None:
    """Record a federated User so verify_token can resolve it on later requests.

    A demo user (already in ``_USERS``) is never shadowed — ``_USERS`` always
    wins in ``_lookup_user`` — so this can't be used to override alice's role.
    """
    if user.user_id in _USERS:
        return  # never shadow a server-controlled demo identity
    _FEDERATED_USERS[user.user_id] = user


def _lookup_user(user_id: str) -> User | None:
    """Resolve a user_id to a User, preferring the server-controlled ``_USERS``
    table and falling back to the federated registry. ``_USERS`` always wins."""
    return _USERS.get(user_id) or _FEDERATED_USERS.get(user_id)


def _get_user(user_id: str) -> User | None:
    """Lookup helper — returns the demo user or None.

    Exists as a named function (rather than callers reaching into `_USERS`
    directly) so the login path has a single chokepoint to instrument /
    rate-limit / audit when this becomes a real user store.
    """
    return _USERS.get(user_id)


def _get_password_hash(user_id: str) -> str | None:
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
    """Sign a short-lived JWT for a demo or federated user.

    The user must be resolvable via ``_lookup_user`` (the ``_USERS`` demo table
    OR the federated registry populated by the OIDC/SAML callbacks). An
    unresolvable user_id raises 404 so a caller can never mint a usable token for
    an identity the server has not vouched for.
    """
    user = _lookup_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown user: {user_id}")
    now = datetime.now(UTC)
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
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e

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
    user = _lookup_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return user


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
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "typ": _MAGIC_TOKEN_TYP,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.MAGIC_LINK_TTL_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=settings.JWT_ALGO)


def magic_token_jti(token: str) -> str | None:
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
    uniform_401 = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired magic link")
    try:
        payload = jwt.decode(token, _verifying_key(), algorithms=[settings.JWT_ALGO])
    except jwt.InvalidTokenError as exc:
        # Covers ExpiredSignatureError (subclass) + tamper/bad-signature.
        raise uniform_401 from exc

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


# ===========================================================================
# Agent F — enterprise IdP: OIDC authorization-code + SAML ACS (Q12, Day 13F)
# ===========================================================================
#
# The named stubs (`/v1/auth/oidc/callback`, `/v1/auth/saml/acs`) are fleshed
# out here into testable, MOCKABLE paths. Two design rules keep the suite
# offline AND the security real:
#
#   1. The identity provider is dependency-injected behind a small protocol
#      (``OIDCProvider`` / ``SAMLProvider``). Tests inject a stub that validates
#      a SIGNED assertion (HMAC) — the same control-flow a real provider runs,
#      minus the network call to Keycloak/Okta/ADFS and the JWKS/XML-DSig
#      crypto. Production sets ``OIDC_PROVIDER=authlib`` / ``SAML_PROVIDER=
#      python3-saml`` and the callback handlers are UNCHANGED — they only ever
#      see a validated ``IdpIdentity``.
#
#   2. The CSRF (state/nonce) + replay guards live in THIS module, provider-
#      agnostic, so they protect every backend. A real IdP integration cannot
#      forget them.
#
# What's still a stub (documented for the next contributor):
#   * OIDC stub HMAC-signs the "authorization code" instead of doing a real
#     code->token exchange + ID-token JWKS signature verification.
#   * SAML stub HMAC-signs the assertion blob instead of verifying XML-DSig.
#   Both are the ONLY shortcuts; state/nonce/replay/audience/expiry are real.
# ---------------------------------------------------------------------------


class IdpError(Exception):
    """Raised by an IdP provider when an assertion / code fails validation.

    The gateway handler catches this and collapses it to a UNIFORM 401 so the
    failure reason (bad signature vs expired vs wrong audience) is never an
    oracle to the caller. The message is logged server-side for the operator.
    """


@dataclass(frozen=True)
class IdpIdentity:
    """The validated identity a provider hands back to the callback handler.

    Deliberately minimal: a provider returns WHO the IdP authenticated, never a
    role/tenant the caller could influence. Role/tenant resolution then runs
    through the SAME server-controlled rules as the upstream-header path
    (``_resolve_idp_user``) — a federated user can NEVER self-assert AUDITOR /
    IT_ADMIN, exactly like the digiRunner header path.
    """

    subject: str  # IdP 'sub' (OIDC) / NameID (SAML)
    issuer: str  # which IdP asserted this
    tenant_hint: str | None = None  # IdP-supplied tenant (honoured only for
    #                                    unknown users; known users pin on-file)
    role_hint: str | None = None  # IdP-supplied role (subject to the same
    #                                    assertable-role whitelist as upstream)


# ---------------------------------------------------------------------------
# OIDC provider protocol + offline stub.
# ---------------------------------------------------------------------------
class OIDCProvider:
    """Protocol: exchange an authorization code for a validated identity.

    The real implementation (Authlib) would POST the code to the IdP token
    endpoint, receive an ID token (JWT), verify its signature against the IdP
    JWKS, and check iss/aud/exp/nonce. The stub below does the moral equivalent
    against an HMAC-signed code blob so the test suite needs no network or key
    material.
    """

    def exchange_code(
        self, code: str, expected_nonce: str
    ) -> IdpIdentity:  # pragma: no cover - interface
        raise NotImplementedError


class StubOIDCProvider(OIDCProvider):
    """Offline OIDC provider.

    A valid "authorization code" is ``base64url(payload_json).hmac`` where the
    HMAC is over the payload using ``OIDC_STUB_SIGNING_SECRET``. The payload is
    the claim set a real ID token would carry::

        {"sub", "iss", "aud", "nonce", "exp", "tenant", "role"}

    Validation mirrors a real ID-token check: constant-time signature compare,
    issuer pin, audience pin, expiry (with clock skew), and nonce binding
    (replay/CSRF: the nonce must equal the one the gateway minted for this
    flow). Any failure raises ``IdpError`` with a specific reason for the log.
    """

    def __init__(self, secret: str, *, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    @staticmethod
    def mint_code(
        secret: str,
        *,
        sub: str,
        iss: str,
        aud: str,
        nonce: str,
        exp: int,
        tenant: str | None = None,
        role: str | None = None,
    ) -> str:
        """Test/helper: build a signed authorization code blob.

        Production never calls this — the real IdP issues the code. It exists so
        the suite (and a local demo) can produce a valid code without a live IdP.
        """
        import base64
        import json

        payload = {"sub": sub, "iss": iss, "aud": aud, "nonce": nonce, "exp": exp}
        if tenant is not None:
            payload["tenant"] = tenant
        if role is not None:
            payload["role"] = role
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        b64 = base64.urlsafe_b64encode(body).decode().rstrip("=")
        sig = hmac.new(secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
        return f"{b64}.{sig}"

    def exchange_code(self, code: str, expected_nonce: str) -> IdpIdentity:
        import base64
        import json

        if not code or code.count(".") != 1:
            raise IdpError("oidc: malformed authorization code")
        b64, sig = code.split(".", 1)
        expected_sig = hmac.new(self._secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
        # Constant-time compare — never leak how many bytes of the sig matched.
        if not hmac.compare_digest(sig, expected_sig):
            raise IdpError("oidc: bad code signature")
        try:
            padded = b64 + "=" * (-len(b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        except Exception as exc:  # noqa: BLE001
            raise IdpError(f"oidc: undecodable code payload: {exc}") from exc

        # issuer pin — a code from a different IdP must not authenticate here.
        if payload.get("iss") != self._issuer:
            raise IdpError("oidc: issuer mismatch")
        # audience pin — the ID token must be addressed to THIS client.
        if payload.get("aud") != self._audience:
            raise IdpError("oidc: audience mismatch")
        # expiry, with clock-skew tolerance.
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or exp + settings.IDP_CLOCK_SKEW_SEC < time.time():
            raise IdpError("oidc: code expired")
        # nonce binding — the ID token nonce MUST equal the one the gateway
        # planted in the auth request for this exact flow. Defeats replay and
        # token-injection (an attacker's stolen code carries the victim's nonce,
        # not the attacker's session nonce).
        nonce = payload.get("nonce")
        if (
            not nonce
            or not expected_nonce
            or not hmac.compare_digest(str(nonce), str(expected_nonce))
        ):
            raise IdpError("oidc: nonce mismatch")
        sub = payload.get("sub")
        if not sub:
            raise IdpError("oidc: missing subject")
        return IdpIdentity(
            subject=str(sub),
            issuer=str(payload["iss"]),
            tenant_hint=payload.get("tenant"),
            role_hint=payload.get("role"),
        )


# ---------------------------------------------------------------------------
# SAML provider protocol + offline stub.
# ---------------------------------------------------------------------------
class SAMLProvider:
    """Protocol: validate a SAML Response/assertion -> validated identity.

    Real impl (python3-saml) verifies XML-DSig against the IdP cert, checks the
    Audience, the NotBefore/NotOnOrAfter window, and the InResponseTo. The stub
    does the moral equivalent over an HMAC-signed assertion blob.
    """

    def validate_assertion(
        self, assertion: str
    ) -> tuple[IdpIdentity, str, int]:  # pragma: no cover - interface
        """Return (identity, assertion_id, not_on_or_after_epoch)."""
        raise NotImplementedError


class StubSAMLProvider(SAMLProvider):
    """Offline SAML provider.

    A valid assertion is ``base64url(payload_json).hmac`` over
    ``SAML_STUB_SIGNING_SECRET``. The payload carries::

        {"id", "subject", "issuer", "audience", "not_before", "not_on_or_after",
         "tenant", "role"}

    Validation mirrors a real assertion check: signature, audience pin, the
    NotBefore/NotOnOrAfter window (with clock skew). The single-use REPLAY guard
    (keyed on ``id``) lives in the handler so it shares the TTL store with the
    rest of the gateway and is provider-agnostic.
    """

    def __init__(self, secret: str, *, audience: str) -> None:
        self._secret = secret
        self._audience = audience

    @staticmethod
    def mint_assertion(
        secret: str,
        *,
        assertion_id: str,
        subject: str,
        issuer: str,
        audience: str,
        not_before: int,
        not_on_or_after: int,
        tenant: str | None = None,
        role: str | None = None,
    ) -> str:
        import base64
        import json

        payload = {
            "id": assertion_id,
            "subject": subject,
            "issuer": issuer,
            "audience": audience,
            "not_before": not_before,
            "not_on_or_after": not_on_or_after,
        }
        if tenant is not None:
            payload["tenant"] = tenant
        if role is not None:
            payload["role"] = role
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        b64 = base64.urlsafe_b64encode(body).decode().rstrip("=")
        sig = hmac.new(secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
        return f"{b64}.{sig}"

    def validate_assertion(self, assertion: str) -> tuple[IdpIdentity, str, int]:
        import base64
        import json

        if not assertion or assertion.count(".") != 1:
            raise IdpError("saml: malformed assertion")
        b64, sig = assertion.split(".", 1)
        expected_sig = hmac.new(self._secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise IdpError("saml: bad assertion signature")
        try:
            padded = b64 + "=" * (-len(b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        except Exception as exc:  # noqa: BLE001
            raise IdpError(f"saml: undecodable assertion: {exc}") from exc

        if payload.get("audience") != self._audience:
            raise IdpError("saml: audience mismatch")
        now = time.time()
        skew = settings.IDP_CLOCK_SKEW_SEC
        nb = payload.get("not_before")
        noa = payload.get("not_on_or_after")
        if not isinstance(nb, (int, float)) or not isinstance(noa, (int, float)):
            raise IdpError("saml: missing time window")
        if now + skew < nb:
            raise IdpError("saml: assertion not yet valid")
        if now - skew >= noa:
            raise IdpError("saml: assertion expired")
        assertion_id = payload.get("id")
        subject = payload.get("subject")
        if not assertion_id or not subject:
            raise IdpError("saml: missing id/subject")
        identity = IdpIdentity(
            subject=str(subject),
            issuer=str(payload.get("issuer", "")),
            tenant_hint=payload.get("tenant"),
            role_hint=payload.get("role"),
        )
        return identity, str(assertion_id), int(noa)


# ---------------------------------------------------------------------------
# Provider factories — dependency-injection seam. Tests monkeypatch these (or
# pass an explicit provider) to swap the stub for a fake; production switches
# on the *_PROVIDER setting.
# ---------------------------------------------------------------------------
def get_oidc_provider() -> OIDCProvider:
    # OIDC_MODE is the deployment-shape selector (stub | keycloak). The legacy
    # OIDC_PROVIDER knob still gates WHICH stub implementation backs stub mode.
    if settings.OIDC_MODE == "keycloak":
        # Imported lazily: oidc_keycloak imports IdpError/IdpIdentity from us.
        from backend.gateway.oidc_keycloak import get_keycloak_provider

        return get_keycloak_provider()
    if settings.OIDC_MODE != "stub":
        raise IdpError(
            f"oidc: unknown OIDC_MODE '{settings.OIDC_MODE}' (expected stub | keycloak)."
        )
    if settings.OIDC_PROVIDER == "stub":
        return StubOIDCProvider(
            settings.OIDC_STUB_SIGNING_SECRET,
            issuer=settings.OIDC_ISSUER,
            audience=settings.OIDC_CLIENT_ID,
        )
    raise IdpError(
        f"oidc: provider '{settings.OIDC_PROVIDER}' not wired in this build "
        "(set OIDC_PROVIDER=stub for the POC, or implement the Authlib path)."
    )


def get_saml_provider() -> SAMLProvider:
    if settings.SAML_PROVIDER == "stub":
        return StubSAMLProvider(settings.SAML_STUB_SIGNING_SECRET, audience=settings.SAML_AUDIENCE)
    raise IdpError(
        f"saml: provider '{settings.SAML_PROVIDER}' not wired in this build "
        "(set SAML_PROVIDER=stub for the POC, or implement python3-saml)."
    )


# ---------------------------------------------------------------------------
# OIDC CSRF state store (state -> nonce, TTL-bounded, single-use).
#
# Begin-flow mints a random `state` (returned to the browser, round-trips
# through the IdP) bound to a random `nonce` (planted in the OIDC auth request,
# echoed in the ID token). On callback the handler looks the state up: a missing
# state => CSRF / forged callback => reject. The lookup is SINGLE-USE so a
# captured state cannot be replayed. POC: in-memory; production: Redis with EX.
# ---------------------------------------------------------------------------
_OIDC_STATE_STORE: dict[str, tuple[str, float]] = {}  # state -> (nonce, expiry)


def begin_oidc_login() -> tuple[str, str]:
    """Mint a (state, nonce) pair for an OIDC authorization request.

    The caller redirects the browser to the IdP with ``state`` + ``nonce`` in
    the query; both come back (state in the callback query, nonce inside the ID
    token) and are checked on /callback. Returns ``(state, nonce)``.
    """
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    _OIDC_STATE_STORE[state] = (nonce, time.time() + settings.OIDC_STATE_TTL_SEC)
    return state, nonce


def consume_oidc_state(state: str | None) -> str:
    """Validate + single-use-consume an OIDC ``state``; return its bound nonce.

    Raises ``IdpError`` if the state is missing, unknown, or expired — every one
    of which is a CSRF / forged-callback signal. On success the entry is removed
    so the same state cannot be replayed.
    """
    if not state:
        raise IdpError("oidc: missing state (CSRF)")
    entry = _OIDC_STATE_STORE.pop(state, None)
    if entry is None:
        raise IdpError("oidc: unknown state (CSRF / replay)")
    nonce, expiry = entry
    if expiry < time.time():
        raise IdpError("oidc: state expired")
    return nonce


# ---------------------------------------------------------------------------
# SAML replay store (assertion_id -> expiry). Single-use, TTL-bounded.
# ---------------------------------------------------------------------------
_SAML_CONSUMED_ASSERTIONS: dict[str, float] = {}


def _saml_assertion_seen(assertion_id: str, not_on_or_after: int) -> bool:
    """Record an assertion id as consumed; return True if it was ALREADY seen.

    TTL is the assertion's own NotOnOrAfter plus the replay TTL so the record
    outlives the assertion's validity window (a replay inside the window is
    caught; once the assertion itself expires, validate_assertion rejects it
    anyway and the record can be pruned). Lazy-prunes expired entries.
    """
    now = time.time()
    # Lazy prune so the store stays bounded without a background sweeper.
    if len(_SAML_CONSUMED_ASSERTIONS) > 0:
        for k in [k for k, exp in _SAML_CONSUMED_ASSERTIONS.items() if exp < now]:
            _SAML_CONSUMED_ASSERTIONS.pop(k, None)
    if assertion_id in _SAML_CONSUMED_ASSERTIONS:
        return True
    _SAML_CONSUMED_ASSERTIONS[assertion_id] = (
        max(not_on_or_after, now) + settings.SAML_REPLAY_TTL_SEC
    )
    return False


def _clear_idp_state() -> None:
    """Test-harness reset for the OIDC state + SAML replay stores."""
    _OIDC_STATE_STORE.clear()
    _SAML_CONSUMED_ASSERTIONS.clear()


# ---------------------------------------------------------------------------
# Role/tenant resolution for a federated identity.
#
# This is the SAME server-controlled policy the digiRunner upstream-header path
# uses (_UPSTREAM_ASSERTABLE_ROLES + known-user-pins-on-file), reused so a
# federated user can NEVER self-assert AUDITOR / IT_ADMIN and a known user's
# role/tenant always come from _USERS. One policy, three doors (upstream header,
# OIDC, SAML) — no second place to get the privilege boundary wrong.
# ---------------------------------------------------------------------------
def _resolve_idp_user(identity: IdpIdentity) -> User:
    """Map a validated ``IdpIdentity`` to a runtime ``User``.

    Known subject -> role/tenant/quota lifted from ``_USERS`` (IdP hints
    ignored). Unknown subject -> least-privilege defaults; ``role_hint`` is
    honoured ONLY if it is in ``_UPSTREAM_ASSERTABLE_ROLES`` (ATTORNEY /
    PARALEGAL), otherwise silently downgraded to PARALEGAL.
    """
    known = _USERS.get(identity.subject)
    if known is not None:
        if identity.tenant_hint and identity.tenant_hint != known.tenant_id:
            logger.warning(
                "idp-auth: SECURITY tenant mismatch for known user_id=%s "
                "(idp=%s, _USERS=%s) — IGNORING idp tenant, pinning on-file",
                identity.subject,
                identity.tenant_hint,
                known.tenant_id,
            )
        return known

    role = _UPSTREAM_DEFAULT_ROLE
    if identity.role_hint:
        try:
            candidate = UserRole(identity.role_hint)
        except ValueError:
            candidate = _UPSTREAM_DEFAULT_ROLE
        role = candidate if candidate in _UPSTREAM_ASSERTABLE_ROLES else _UPSTREAM_DEFAULT_ROLE
    tenant_id = identity.tenant_hint or "tenant_federated"
    return User(
        user_id=identity.subject,
        tenant_id=tenant_id,
        role=role,
        display_name=identity.subject,
        daily_token_quota=100_000,
    )


def authenticate_oidc_callback(
    code: str | None,
    state: str | None,
    provider: OIDCProvider | None = None,
) -> User:
    """Complete an OIDC authorization-code callback -> session ``User``.

    Order of checks (each a distinct threat):
      1. OIDC enabled?                      (feature gate)
      2. state present + known + unexpired  (CSRF / forged callback) — SINGLE-USE
      3. code signature/iss/aud/exp/nonce   (provider, real crypto in prod)
      4. role/tenant via _resolve_idp_user  (privilege boundary)

    Raises ``IdpError`` on any failure; the handler collapses that to a uniform
    401 so the specific reason is not a caller-visible oracle.
    """
    if not settings.OIDC_ENABLED:
        raise IdpError("oidc: disabled")
    # State first — a forged callback (no matching state) is rejected before we
    # spend any work validating an attacker-supplied code.
    nonce = consume_oidc_state(state)
    prov = provider or get_oidc_provider()
    identity = prov.exchange_code(code or "", nonce)
    user = _resolve_idp_user(identity)
    _register_federated_user(user)
    return user


def authenticate_saml_acs(
    saml_response: str | None,
    provider: SAMLProvider | None = None,
) -> User:
    """Complete a SAML ACS POST -> session ``User``.

    Order: feature gate -> signature/audience/time-window (provider) ->
    single-use REPLAY check on the assertion id -> role/tenant resolution.
    Raises ``IdpError`` on any failure (uniform 401 at the handler).
    """
    if not settings.SAML_ENABLED:
        raise IdpError("saml: disabled")
    prov = provider or get_saml_provider()
    identity, assertion_id, not_on_or_after = prov.validate_assertion(saml_response or "")
    # Replay: a previously-consumed assertion id (even within its time window)
    # must be refused. Checked AFTER signature/time so an attacker can't use the
    # replay store as an assertion-id oracle with unsigned input.
    if _saml_assertion_seen(assertion_id, not_on_or_after):
        raise IdpError("saml: assertion replay")
    user = _resolve_idp_user(identity)
    _register_federated_user(user)
    return user


def authorize_case_access(user: User, case_id: str | None) -> None:
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


def _normalise_client_ip(client_host: str | None) -> ipaddress._BaseAddress | None:
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


def _is_trusted_peer(client_host: str | None) -> bool:
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


def _user_from_upstream_headers(request: Request) -> User | None:
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
                "upstream-auth: shared-secret mismatch from client=%s — declining upstream path",
                client_ip,
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
                user_id,
                tenant_id,
                known.tenant_id,
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
        user.user_id,
        user.tenant_id,
        user.role.value,
        client_ip,
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
            user.user_id,
            user.tenant_id,
            user.role.value,
            _client_ip,
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
    _role_dependency.__name__ = f"require_roles_{'_'.join(sorted(r.value for r in allowed))}"
    return _role_dependency
