"""Gateway main entrypoint (digiRunner mock).

Boots a FastAPI service on :8000. Layers, in request order:
    1. CORS for the SPA
    2. Auth (JWT + case access)             — Q12
    3. Rate limit / quota / circuit breaker — Q18
    4. Body redaction                        — Q10 (handled inside orchestrator)
    5. Orchestration                         — Q1 / Follow-up
    6. Audit log                             — Q13
"""
from __future__ import annotations

import base64
import hmac
import logging
import time
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.gateway import audit, audit_outbox, cache, masking, rate_limit
from backend.gateway.auth import (
    _get_password_hash,
    _get_user,
    _internal_headers,
    _verify_password,
    auth_dependency,
    authorize_case_access,
    issue_token,
    require_roles,
)
from backend.gateway.orchestrator import orchestrate_analysis
from backend.shared.config import settings
from backend.shared.models import AnalysisRequest, AnalysisResponse, User, UserRole
from backend.shared.observability import init_sentry

logger = logging.getLogger(__name__)


def _safe_audit_write(**kwargs: Any) -> None:
    """Write one audit row, swallowing any exception from the audit writer.

    Invariant #4 (CLAUDE.md §4) says every gateway request writes exactly one
    audit row — even errors. We enforce that with a ``try/finally`` in each
    handler; this wrapper is the second half of the guarantee: if the audit
    DB itself is broken (disk full / file locked / SQLite trigger refusal),
    we must NOT let that failure mask the real response or original
    exception the user is about to see.

    The failure is logged at error level (Sentry / log scraper will surface
    it) but never re-raised.

    Durability backstop (invariant #4): swallowing the failure outright would
    lose the audit row forever, which silently breaks the "exactly one row
    even on errors" contract. So on failure we ALSO hand the full payload to
    the durable outbox (``audit_outbox.enqueue``) — a fsync'd append-only
    JSONL file that survives the SQLite outage. ``replay_outbox()`` drains it
    back into the audit DB once the primary store recovers. The enqueue itself
    never re-raises, so the caller's response/error is still never masked.
    """
    try:
        audit.writer.write(**kwargs)
    except Exception:  # noqa: BLE001 — deliberately broad: see docstring
        logger.exception(
            "audit write failed for endpoint=%s user=%s case=%s — "
            "row queued to durable outbox; response/error returned to caller anyway",
            kwargs.get("endpoint"),
            getattr(kwargs.get("user"), "user_id", None),
            kwargs.get("case_id"),
        )
        # Write-ahead the row to the durable outbox so it is never lost.
        # enqueue() never re-raises, preserving the no-masking guarantee.
        audit_outbox.enqueue(**kwargs)


def _error_response_payload(error: BaseException) -> dict:
    """Render an exception into the audit-row response_payload shape.

    Keeps `str(error)` capped at 512 chars so a verbose exception (Pydantic
    validation errors can run thousands of characters) cannot bloat the
    hash-chained log.
    """
    return {
        "error": str(error)[:512],
        "exc_type": type(error).__name__,
        "status_code": getattr(error, "status_code", 500),
    }

# Day 5: init Sentry before FastAPI() so import-time exceptions are caught.
_SENTRY_ACTIVE = init_sentry("gateway")


# Day 2 upload: allowed content types. Anything else → 415.
_UPLOAD_PDF_MIME = "application/pdf"
_UPLOAD_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_ALLOWED_UPLOAD_MIMES = {_UPLOAD_PDF_MIME, _UPLOAD_DOCX_MIME}

# Page-break separator used to join multi-page extracted text. Picked so it
# survives copy-paste into the existing /v1/oa/analyze flow and is unlikely to
# collide with any real OA content.
_PAGE_SEPARATOR = "\n\n--- page break ---\n\n"

app = FastAPI(
    title="PatentMind digiRunner Gateway (mock)",
    version="0.1.0",
    description="厚 Gateway: auth + quota + redaction + audit + orchestration.",
)


# ---------------------------------------------------------------------------
# Security Chunk C — H-2. Max-body-size middleware.
#
# FastAPI / starlette accept request bodies as large as the ASGI server
# allows — uvicorn has no built-in limit. A 1GB JSON POST is buffered into
# memory and only rejected later when Pydantic walks the parsed dict and
# trips a `max_length` constraint. By then we've already paid the memory +
# CPU + latency cost.
#
# This middleware rejects on Content-Length BEFORE any body bytes are read.
# Multipart uploads (Content-Length typically present and accurate) and
# chunked bodies (Content-Length absent → fall through to per-handler
# limits like /v1/oa/upload's MAX_UPLOAD_MB) are both handled correctly.
# The default cap is 100MB which is generous enough for 30MB PDF uploads
# (cap = MAX_UPLOAD_MB) while bounding worst-case memory at one big request.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def max_body_size_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError:
            # Malformed Content-Length — let the inner stack handle it (it'll
            # likely 400). We don't want this middleware to be the source of
            # weird 413s on legitimate-but-corrupt headers.
            return await call_next(request)
        if length > settings.MAX_BODY_BYTES:
            # Identical 413 shape whether triggered here or by the upload
            # endpoint's per-file MAX_UPLOAD_MB cap, so the frontend's
            # generic "too large" handling fires.
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "detail": (
                        f"request body exceeds limit: {length} bytes > "
                        f"{settings.MAX_BODY_BYTES} bytes."
                    )
                },
            )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Security Chunk C — M-1. Security headers middleware.
#
# Adds the six baseline response headers every browser-facing service should
# ship with. Applied via `@app.middleware("http")` so they fire on EVERY
# response — including 4xx error responses (clickjacking via a 404 page is
# still clickjacking) and CORS preflight OPTIONS responses.
#
# CSP rationale:
#   * `default-src 'self'`   — refuses arbitrary third-party loads.
#   * `script-src 'self' 'unsafe-inline'` — vite injects inline scripts in
#     dev for HMR + chunk preloads. Production builds extract everything to
#     hashed files, at which point the operator can tighten this to remove
#     'unsafe-inline'. Tracked in CLAUDE.md §P2 polish.
#   * `style-src 'self' 'unsafe-inline'` — same reasoning; Tailwind via CDN
#     ships inline `<style>`. Production PostCSS extraction lets this tighten.
#   * `img-src 'self' data:` — admits inline data: URIs (favicon, file
#     previews).
#   * `connect-src 'self'`   — the SPA talks to the same origin. If a
#     deployment fronts the API on a different host, this list must
#     widen — but for the demo single-origin (vite proxy → backend)
#     'self' is sufficient.
#   * `font-src 'self' data:` — Tailwind / Inter fonts via data:.
#   * `object-src 'none'`    — refuses Flash / Java embeds (legacy attack
#     surface; we have no use case).
#   * `frame-ancestors 'none'` — clickjacking-proof, paired with the
#     X-Frame-Options: DENY header for older browsers.
#   * `base-uri 'self'`      — refuses an injected `<base>` tag from
#     redirecting relative URLs to a hostile origin.
#   * `form-action 'self'`   — refuses an injected `<form action="...">`
#     posting to a hostile origin (we have no cross-origin forms).
#
# Permissions-Policy zeroes out geolocation / camera / mic / payment — none
# of which the patent-prosecution UX needs. If a future feature legitimately
# wants one of these, narrow the deny list (and document why).
#
# HSTS: 1-year max-age + includeSubDomains. We omit `preload` because that
# is an irrevocable browser-list commitment; opt in only when the
# deployment is unquestionably stable on https.
# ---------------------------------------------------------------------------
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": _CSP_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "geolocation=(), camera=(), microphone=(), payment=()"
    ),
}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        # Only set if not already present — lets a handler override a
        # specific header for a one-off (e.g. an iframe-friendly preview
        # page in the future). Today no handler overrides any of these.
        response.headers.setdefault(header, value)
    return response


# H-1: env-driven CORS with specific methods + headers (was `*` wildcards).
# `allow_credentials=True` matches the frontend's bearer-token + same-origin
# fetch pattern. Methods + headers explicitly whitelisted — no future request
# of an unexpected method (e.g. PATCH) sneaks through without a code change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOWED_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Case-Id",
        "X-Demo-Secret",
    ],
    allow_credentials=True,
    max_age=600,
)


# ---------- Login (POC simplified) ----------

class LoginRequest(BaseModel):
    # H-2: forbid unknown fields and cap each string at a sensible upper
    # bound. user_id is in _USERS (max ~10 chars in the demo set); password
    # is bounded to 256 chars which covers any IdP-issued token-style
    # credential without admitting a multi-MB body.
    model_config = {"extra": "forbid"}

    user_id: str = Field(..., max_length=64)  # POC: pass user_id directly. Production: IdP redirect.
    # Required unless an X-Demo-Secret header is supplied AND matches
    # settings.DEMO_LOGIN_SECRET. Default demo password is `demo-{user_id}`
    # (documented in .env.example).
    password: Optional[str] = Field(default=None, max_length=256)


class LoginResponse(BaseModel):
    token: str
    user_id: str
    tenant_id: str
    role: str
    display_name: str


@app.post("/v1/auth/login", response_model=LoginResponse)
def login(
    req: LoginRequest,
    request: Request,
    x_demo_secret: Optional[str] = Header(default=None, alias="X-Demo-Secret"),
):
    """Issue a JWT after validating credentials (Security Chunk A — C-1, H-8).

    Two accepted paths (POC):

    1. **Username + password.** Default demo passwords are ``demo-{user_id}``
       (see ``.env.example``). Compared in constant time via
       ``hmac.compare_digest`` so byte-level timing cannot oracle which
       prefix matched.

    2. **X-Demo-Secret header.** Used by the SPA's "click Alice" landing
       page so stakeholder demos don't require typing. Only honoured when
       the ``DEMO_LOGIN_SECRET`` env var is set on the backend (otherwise
       any value the attacker supplies is useless). When set, a matching
       header authenticates the named user without a password — equivalent
       to a global service-side bypass that the operator opts into per
       deployment.

    Both unknown user and wrong password collapse to the **same** 401
    response (no body shape difference, no status difference) — closes
    H-8 user enumeration. Per-IP rate limit (LOGIN_RPM, default 10/min)
    closes the brute-force window — Day 8 post-review fix for the
    sole pre-auth endpoint.

    POC IdP modes (Q12) all converge here:
      - built-in:    POST /v1/auth/login (this endpoint)
      - OIDC:        /v1/auth/oidc/callback (TODO with Claude Code)
      - SAML:        /v1/auth/saml/acs (TODO)
      - magic link:  /v1/auth/magic/{token} (TODO)
    """
    # Pre-auth brute-force defence (Day 8 post-review Important #1):
    # bucket by client IP, default 10 attempts/min. Runs BEFORE the dummy
    # hash + sha256 round so a flood doesn't burn CPU on hash computation.
    client_ip = request.client.host if request.client else ""
    rate_limit.check_login_rpm(client_ip)

    user = _get_user(req.user_id)
    stored_hash = _get_password_hash(req.user_id)

    # Path 1: demo-secret header. Only relevant when an operator has set
    # DEMO_LOGIN_SECRET on the backend — otherwise the comparison is
    # short-circuited so an attacker supplying any header value learns
    # nothing about whether the feature exists.
    demo_secret_ok = bool(
        settings.DEMO_LOGIN_SECRET
        and x_demo_secret
        and hmac.compare_digest(x_demo_secret, settings.DEMO_LOGIN_SECRET)
    )

    # Path 2: username + password. We always run _verify_password regardless
    # of whether `user` is None, so the work-factor is identical for the
    # known-user-wrong-password and unknown-user paths (closes H-8 timing
    # oracle). We pass a dummy hash for the unknown-user case so the sha256
    # round still happens.
    candidate_hash = stored_hash or _DUMMY_HASH_FOR_TIMING
    password_ok = bool(
        req.password and _verify_password(req.password, candidate_hash)
    )

    # `user is not None` is required for BOTH paths: the demo-secret header
    # is a credential, not an identity selector, so it cannot conjure a
    # `user_id` that isn't in the table.
    authenticated = bool(user) and (demo_secret_ok or password_ok)
    if not authenticated:
        # Same status + message for unknown user AND bad password (H-8).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    return LoginResponse(
        token=issue_token(req.user_id),
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        display_name=user.display_name,
    )


# A fixed dummy hash used when the requested user_id is unknown. Picked so
# the sha256 round in `_verify_password` runs for the unknown-user case too
# — without it the unknown-user path returns hundreds of nanoseconds faster
# than the known-user-wrong-password path and an attacker can enumerate.
# The salt is fixed (not random per request) because the only goal is to
# make the work factor identical, not to actually authenticate anyone.
_DUMMY_HASH_FOR_TIMING = (
    "00000000000000000000000000000000:"
    "0000000000000000000000000000000000000000000000000000000000000000"
)


# ---------- Health / Quota dashboard (Q19) ----------

@app.get("/v1/health")
def health():
    return {
        "ok": True,
        "service": "gateway",
        "circuit_breaker": rate_limit.cost_circuit_state(),
        "cache_stats": cache.stats(),
        # Q13 durability backstop: number of audit rows whose primary write
        # failed and are queued in the durable outbox awaiting replay. >0 is
        # an ops signal that the audit DB is (or was) unhealthy.
        "audit_outbox_depth": audit_outbox.outbox_depth(),
    }


@app.get("/v1/quota")
def quota(user: User = Depends(auth_dependency)):
    return rate_limit.get_quota_snapshot(user)


# ---------- Main analysis endpoint ----------

@app.post("/v1/oa/analyze", response_model=AnalysisResponse)
async def analyze_oa(
    body: AnalysisRequest,
    request: Request,
    # H-6: role gate. ATTORNEY + PARALEGAL (paralegals assist attorneys —
    # core POC demo workflow). IT_ADMIN + AUDITOR are NOT permitted; they
    # have different concerns (connectors / dashboards / audit chain).
    # `require_roles` wraps `auth_dependency` so authentication still
    # happens first — no risk of unauth being accepted.
    user: User = Depends(require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)),
):
    """Q1 厚 Gateway core endpoint.

    Steps (with policy gates):
      0. Explicit case-ACL re-check on body.case_id (C-3 fix — see auth.py
         docstring; the dependency-level check only looks at headers).
      1. RPM check
      2. Request size hard cap
      3. Estimate token need; quota check
      4. Cache lookup (per Q9 namespacing)
      5. Orchestrate via AI Engine
      6. Record usage + circuit breaker check
      7. Audit log

    The whole flow runs inside a try/finally so an audit row is written even
    when an exception fires partway through (H-7 fix — invariant #4 in
    CLAUDE.md §4 requires "every gateway request writes exactly one audit
    row. Even cache hits. Even errors").
    """
    started = time.monotonic()
    policy_decisions: dict[str, bool] = {
        "authn_passed": True,
        # authz starts False — we have NOT yet validated the body.case_id
        # against the user's ACL. The dependency only checked X-Case-Id /
        # query param; a request that omits both lands here with the
        # dependency thinking case_id was missing (and passing). The
        # explicit re-check below is what actually closes the bypass.
        "authz_passed": False,
        "rate_limit_passed": False,
        "quota_passed": False,
        "circuit_open": False,
    }
    response: Optional[AnalysisResponse] = None
    cached_payload: Optional[dict] = None
    obs: dict = {}
    error: Optional[BaseException] = None
    try:
        # 0a. Confused-deputy guard: if BOTH the X-Case-Id header AND the
        # body.case_id are present, they MUST agree. Otherwise an attacker
        # could trick a header-based ACL into thinking the request is for
        # case A while the actual orchestration runs against case B. We
        # only check when both are present — handlers that previously sent
        # only one or the other (the frontend always sends both with the
        # same value; smoke tests sometimes send only body) keep working.
        header_case_id = (
            request.headers.get("X-Case-Id") or request.query_params.get("case_id")
        )
        if header_case_id and header_case_id != body.case_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"case_id mismatch: header={header_case_id!r} body={body.case_id!r}. "
                "X-Case-Id and body case_id must agree when both are supplied.",
            )

        # 0b. C-3: explicit ACL on the body-supplied case_id. Runs BEFORE any
        # rate-limit / quota work so a 403 doesn't burn the user's RPM token
        # for an attack we're already rejecting.
        authorize_case_access(user, body.case_id)
        policy_decisions["authz_passed"] = True

        # 1. RPM
        rate_limit.check_rpm(user)
        policy_decisions["rate_limit_passed"] = True

        # 2. Hard cap
        estimated_tokens = max(1, len(body.oa_text) // 3)
        rate_limit.check_request_size(estimated_tokens)

        # 3. Quota
        rate_limit.check_quotas(user, estimated_tokens)
        policy_decisions["quota_passed"] = True

        # 4. Cache (Q9) — M-7 fix: hash POST-redaction text, not raw input.
        # Pre-fix the cache key used `body.oa_text` directly. That meant:
        #   (a) Two attorneys typing the same OA shared a cache slot (the
        #       surrounding tenant/user/case namespacing prevented response
        #       leakage, but only because of that layer — the hash itself
        #       had no privacy property);
        #   (b) A typo (extra space, fullwidth digit, smart-quote) caused
        #       a miss that should have been a hit (NFKC + dictionary
        #       normalise away in the redaction step);
        #   (c) Including a redaction-version tag means a future ruleset
        #       bump (new PII rule, tenant dictionary refresh) automatically
        #       invalidates pre-bump cached responses rather than serving
        #       them under the new policy.
        # `masking.redact` is idempotent on placeholders (a `[EMAIL_XXXX]`
        # token doesn't match the email regex) so re-running it inside the
        # orchestrator is safe and keeps the orchestrator's own redaction
        # invariant (Q3 + Q10) intact.
        redacted_for_cache, _ = masking.redact(body.oa_text, user.tenant_id)
        prompt_hash = cache.hash_prompt(
            redacted_for_cache + body.target_patent_no,
            "orchestrator-v1",
            redaction_version=settings.REDACTION_VERSION,
        )
        cached = cache.get_response(user.tenant_id, user.user_id, body.case_id, prompt_hash)
        if cached:
            cached_payload = cached
            response = AnalysisResponse(**cached)
            return response

        # 5. Circuit breaker
        if rate_limit.cost_circuit_state()["tripped"]:
            policy_decisions["circuit_open"] = True
            # POC behavior: still serve, but the LLM router will degrade to cheap model.
            # In production: optionally 503 here for graceful shedding.

        # 6. Orchestrate — forward the circuit-breaker state so the AI Engine
        # degrades the draft model to the cheap tier when the cost breaker
        # has tripped (Q18 / invariant #8).
        response, obs = await orchestrate_analysis(
            user, body, circuit_open=policy_decisions.get("circuit_open", False)
        )

        # 7. Record usage
        rate_limit.record_usage(
            user,
            prompt_tokens=obs["prompt_tokens"],
            completion_tokens=obs["completion_tokens"],
            cost_usd=obs["estimated_cost_usd"],
        )

        # 8. Cache write
        cache.set_response(user.tenant_id, user.user_id, body.case_id, prompt_hash, response.model_dump(mode="json"))

        return response
    except BaseException as exc:  # noqa: BLE001 — must reach the finally
        error = exc
        policy_decisions["error"] = True
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        # Pick the right audit shape based on which path the request took.
        if error is not None:
            response_payload = _error_response_payload(error)
            model_used = None
            prompt_tokens = 0
            completion_tokens = 0
            masked_rules: list[str] = []
            pd = {**policy_decisions, "cache_hit": False}
        elif cached_payload is not None:
            response_payload = cached_payload
            model_used = "cache"
            prompt_tokens = 0
            completion_tokens = 0
            masked_rules = []
            pd = {**policy_decisions, "cache_hit": True}
        else:
            # response is non-None on the success path because orchestrate ran.
            assert response is not None, "internal: success path produced no response"
            response_payload = response.model_dump(mode="json")
            model_used = obs.get("model_used")
            prompt_tokens = obs.get("prompt_tokens", 0)
            completion_tokens = obs.get("completion_tokens", 0)
            masked_rules = obs.get("mask_rules", [])
            pd = {**policy_decisions, "cache_hit": False}
        _safe_audit_write(
            user=user,
            case_id=body.case_id,
            endpoint="/v1/oa/analyze",
            request_payload=body.model_dump(),
            response_payload=response_payload,
            masked_rules=masked_rules,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            policy_decisions=pd,
        )


# ---------- Day 2 upload endpoint ----------

@app.post("/v1/oa/upload")
async def upload_oa(
    request: Request,
    file: UploadFile = File(...),
    # H-6: same role gate as /v1/oa/analyze — paralegals assist attorneys
    # by uploading OAs that the attorney then analyses. IT_ADMIN + AUDITOR
    # are refused with 403 before any upload bytes are read.
    user: User = Depends(require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)),
):
    """Day 2: accept a PDF/DOCX, return extracted text for use by /v1/oa/analyze.

    Layering rules respected:
      - Auth + case ACL: re-checked here on the X-Case-Id header. The auth
        dependency already checked it; we re-call ``authorize_case_access``
        anyway for C-3 belt-and-braces (and to populate ``authz_passed``
        explicitly so the audit row reflects the gate).
      - Confidential routing: this endpoint REFUSES confidential cases. They
        must use manual text paste — uploading would push pages through cloud
        Vision OCR which is forbidden by security policy (Q15).
      - Gateway never calls the LLM directly: bytes are base64-encoded and
        forwarded to the AI Engine `/v1/ai/extract_text` endpoint.
      - Redaction: NOT applied here. The extracted text is returned to the
        attorney; redaction happens at /v1/oa/analyze time as before.
      - Audit: writes a row recording file size + page count + ocr count +
        cost — NEVER the extracted text itself. Per invariant #4 (H-7 fix)
        the audit row is written even on error paths via the try/finally
        below.
      - Rate limit + cost circuit: 1 request, cost = vision OCR usage.
    """
    started = time.monotonic()
    policy_decisions = {
        "authn_passed": True,
        "authz_passed": False,
        "rate_limit_passed": False,
        "upload_size_passed": False,
        "upload_type_passed": False,
        "confidential_blocked": False,
    }

    # Pull case_id explicitly: multipart bodies are streams so auth_dependency
    # can't autodetect it from body the way it does for JSON POSTs. (And per
    # C-3 fix, the dependency never peeks at the body at all now.)
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")

    # Pre-set audit shape so the finally block always has something coherent
    # to write — even if we error out before reading the file body.
    response_payload: Any = None
    model_used: Optional[str] = None
    prompt_tokens = 0
    completion_tokens = 0
    file_size = 0
    error: Optional[BaseException] = None
    file_content_type = getattr(file, "content_type", None)
    file_name = getattr(file, "filename", None)

    try:
        if not case_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "X-Case-Id header required for upload",
            )
        # C-3 belt-and-braces: explicit ACL re-check. Already enforced by
        # auth_dependency for header case_id, but we want ``authz_passed``
        # to reflect a real check on this endpoint.
        authorize_case_access(user, case_id)
        policy_decisions["authz_passed"] = True

        # Block confidential cases at the EDGE. Defense in depth: pdf_parser
        # will also refuse, but we want to reject before reading the upload
        # body so large privileged scans never even enter our process memory.
        if case_id.upper().endswith("-CONF"):
            policy_decisions["confidential_blocked"] = True
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Confidential cases must use manual text entry; upload routes "
                "through cloud OCR which is forbidden by security policy.",
            )

        # Validate content type FIRST so we don't slurp a 30MB binary just to
        # discover it's the wrong format.
        if file.content_type not in _ALLOWED_UPLOAD_MIMES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"unsupported content type: {file.content_type!r}. "
                f"Allowed: {sorted(_ALLOWED_UPLOAD_MIMES)}.",
            )
        policy_decisions["upload_type_passed"] = True

        # RPM check before any heavy work.
        rate_limit.check_rpm(user)
        policy_decisions["rate_limit_passed"] = True

        # Read the file into memory and enforce the byte cap. Reading in one
        # shot is fine because the cap is single-digit MB by default; we
        # explicitly avoid streaming-to-disk per the "bytes never touch disk"
        # requirement.
        file_bytes = await file.read()
        file_size = len(file_bytes)
        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        if file_size > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"upload exceeds limit: {file_size} bytes > "
                f"{max_bytes} bytes ({settings.MAX_UPLOAD_MB} MB).",
            )
        policy_decisions["upload_size_passed"] = True

        # Forward to AI engine. Base64 keeps the AI engine surface JSON-only
        # and matches the orchestrator's existing httpx.AsyncClient pattern.
        payload = {
            "file_bytes_b64": base64.b64encode(file_bytes).decode("ascii"),
            "content_type": file.content_type,
            "max_pages": 100,
            "security_level": "public",  # we already blocked -CONF above
        }
        ai_url = f"{settings.AI_ENGINE_URL.rstrip('/')}/v1/ai/extract_text"
        async with httpx.AsyncClient(timeout=120.0) as client:
            # OCR over a 100-page scan can take ~60s through Haiku, so the
            # timeout intentionally exceeds the orchestrator's 60s.
            try:
                # Security Chunk A — C-2. AI Engine refuses requests lacking
                # X-Internal-Token. Gateway is the only legitimate caller.
                ai_resp = await client.post(ai_url, json=payload, headers=_internal_headers())
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"AI engine unreachable: {exc}",
                )

        if ai_resp.status_code >= 400:
            # Mirror the AI engine status when meaningful, otherwise 502.
            # We surface the detail body so the frontend can show a useful
            # error (e.g. "PDF is password-protected").
            try:
                detail = ai_resp.json().get("detail", ai_resp.text)
            except Exception:
                detail = ai_resp.text
            if ai_resp.status_code in (400, 413, 415, 422):
                raise HTTPException(ai_resp.status_code, detail)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"AI engine error: {detail}")

        body = ai_resp.json()
        usage = body.get("usage") or {}
        cost_usd = float(usage.get("estimated_cost_usd", 0.0) or 0.0)
        page_count = int(body.get("page_count", 0))
        ocr_pages_used = body.get("ocr_pages", []) or []

        extracted_text = _PAGE_SEPARATOR.join(body.get("pages", []) or [])

        # Account for cost + quota. Cost counts toward the daily circuit
        # breaker.
        prompt_tokens = int(usage.get("input_tokens", 0) or 0)
        completion_tokens = int(usage.get("output_tokens", 0) or 0)
        rate_limit.record_usage(
            user,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )

        response_payload = {
            "page_count": page_count,
            "ocr_pages_count": len(ocr_pages_used),
            "char_count": int(body.get("char_count", 0) or 0),
            "cost_usd": cost_usd,
        }
        model_used = settings.LLM_MODEL_CHEAP if ocr_pages_used else "none"

        return {
            "extracted_text": extracted_text,
            "page_count": page_count,
            "ocr_pages_used": ocr_pages_used,
            "char_count": int(body.get("char_count", 0) or 0),
            "warnings": body.get("warnings", []) or [],
            "cost_meta": {
                "estimated_cost_usd": cost_usd,
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
                "cache_creation_input_tokens": int(
                    usage.get("cache_creation_input_tokens", 0) or 0
                ),
            },
        }
    except BaseException as exc:  # noqa: BLE001 — must reach the finally
        error = exc
        policy_decisions["error"] = True
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        if error is not None:
            audit_response_payload = _error_response_payload(error)
            audit_model_used = None
        else:
            audit_response_payload = response_payload
            audit_model_used = model_used
        _safe_audit_write(
            user=user,
            # case_id may be None if the X-Case-Id header was missing (we
            # still record the row so the operator can see the attempt).
            case_id=case_id,
            endpoint="/v1/oa/upload",
            request_payload={
                "file_size_bytes": file_size,
                "content_type": file_content_type,
                "filename": file_name,
            },
            response_payload=audit_response_payload,
            masked_rules=[],
            model_used=audit_model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=duration_ms,
            policy_decisions=policy_decisions,
        )


# ---------- Audit query endpoints (for the Auditor role) ----------

@app.get("/v1/audit/recent")
def audit_recent(limit: int = 50, user: User = Depends(auth_dependency)):
    if user.role.value not in ("auditor", "it_admin"):
        raise HTTPException(403, "auditor or it_admin role required")
    return audit.writer.list_for_tenant(user.tenant_id, limit=limit)


@app.get("/v1/audit/verify")
def audit_verify(
    scope: str = "tenant",
    user: User = Depends(auth_dependency),
):
    """Walk the audit chain, recompute hashes, report broken rows (Q13
    tamper evidence).

    Query parameter ``scope``:

    * ``tenant`` (default) — walks only the caller's tenant. Existing
      behaviour, role-gated to AUDITOR + IT_ADMIN.
    * ``global``           — walks every tenant's chain, runs the
      tenant-whitelist + prev-hash-existence checks (H-4 fix). Restricted
      to AUDITOR only because a global view crosses tenant boundaries —
      IT_ADMIN's role description is per-tenant connectors / dashboards,
      not cross-tenant compliance. An attacker who escalated to IT_ADMIN
      should not be able to enumerate every tenant's case_ids via this
      endpoint.
    """
    if user.role.value not in ("auditor", "it_admin"):
        raise HTTPException(403, "auditor or it_admin role required")
    if scope == "global":
        # Tighter gate for the cross-tenant view — auditor only.
        if user.role.value != "auditor":
            raise HTTPException(403, "auditor role required for scope=global")
        return audit.writer.verify_global_chain()
    if scope != "tenant":
        raise HTTPException(400, f"unknown scope {scope!r}; expected 'tenant' or 'global'")
    return audit.writer.verify_chain(user.tenant_id)


# ---------- Redaction (first-class for digiRunner pre-LLM transform plugins) ----------

class RedactionPreviewRequest(BaseModel):
    # H-2: same cap as AnalysisRequest.oa_text — redaction preview is what
    # the SPA shows BEFORE submitting the OA for analysis, so the upper
    # bound has to match. extra=forbid prevents a future client from
    # smuggling tenant_id / user_id (which would be ignored anyway since
    # those come from auth context, but better to fail loudly).
    model_config = {"extra": "forbid"}

    text: str = Field(..., max_length=5 * 1024 * 1024)


def _do_redact(req: RedactionPreviewRequest, user: User, request: Request, endpoint: str) -> dict:
    """Shared implementation for /v1/redact and its deprecated alias.

    Writes exactly one audit row per call (invariant #4) — the input text is
    NEVER stored, only its hash + the rule ids that fired. The whole flow
    runs inside a try/finally so the audit row is written even on error
    paths (H-7 fix).
    """
    started = time.monotonic()
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")

    policy_decisions: dict[str, bool] = {
        "authn_passed": True,
        "authz_passed": False,
    }
    rules: list[str] = []
    redacted: str = ""
    result_payload: Optional[dict] = None
    error: Optional[BaseException] = None
    try:
        if not case_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "X-Case-Id header required for redaction (tenant routing)",
            )
        # auth_dependency already enforced ACL when case_id was on the
        # header, but we re-check explicitly so the audit row's authz flag
        # is meaningful and the C-3 invariant ("body-derived case_ids are
        # re-checked at handler") generalises uniformly to all endpoints.
        authorize_case_access(user, case_id)
        policy_decisions["authz_passed"] = True

        redacted, rules = masking.redact(req.text, user.tenant_id)
        result_payload = {"rules_triggered": rules, "redacted_chars": len(redacted)}
        return {"redacted": redacted, "rules_triggered": rules}
    except BaseException as exc:  # noqa: BLE001 — must reach the finally
        error = exc
        policy_decisions["error"] = True
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        audit_response_payload: Any = (
            _error_response_payload(error) if error is not None else result_payload
        )
        _safe_audit_write(
            user=user,
            case_id=case_id,
            endpoint=endpoint,
            # Never store raw text in audit — only its length + content hash
            # via the writer's _hash_payload mechanism.
            request_payload={"text_chars": len(req.text)},
            response_payload=audit_response_payload,
            masked_rules=rules,
            model_used=None,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            policy_decisions=policy_decisions,
        )


@app.post("/v1/redact")
def redact(
    req: RedactionPreviewRequest,
    request: Request,
    # H-6: ATTORNEY + PARALEGAL — preview-before-submit lives in the OA
    # analysis workflow which both roles use. IT_ADMIN + AUDITOR have no
    # legitimate reason to call this (and AUDITOR doing so would smear
    # their tenant's audit chain with redaction rows under the auditor's
    # identity).
    user: User = Depends(require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)),
):
    """First-class redaction endpoint.

    Intended for digiRunner pre-LLM transform plugins that need to scrub user
    input before forwarding to the LLM gateway. Same shape as the legacy
    /v1/debug/redaction_preview alias (which now delegates here).

    Requires:
      - Authorization: Bearer <token>
      - X-Case-Id: <case_id>  (for tenant routing inside masking + ACL check)
      - Role: ATTORNEY or PARALEGAL.
    """
    return _do_redact(req, user, request, endpoint="/v1/redact")


@app.post("/v1/debug/redaction_preview", deprecated=True)
def redaction_preview(
    req: RedactionPreviewRequest,
    request: Request,
    response: Response,
    # H-6: same role gate as /v1/redact — the deprecated alias must enforce
    # the same authorisation as the first-class endpoint, otherwise it'd be
    # a permission backdoor.
    user: User = Depends(require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)),
):
    """DEPRECATED alias for /v1/redact — kept so the existing frontend and
    smoke-test paths don't break. New callers should use /v1/redact.
    """
    # RFC 9745 (Sept 2024 final): Deprecation MUST be a Structured-Field
    # Date — bare "true" was the obsolete RFC 8594 draft style. We use the
    # deprecation moment (2026-06-01 00:00 UTC, the day this alias was
    # introduced) and pair it with a Sunset header (RFC 8594) at +12 months.
    response.headers["Deprecation"] = "@1748736000"  # 2026-06-01T00:00:00Z
    response.headers["Sunset"] = "Mon, 01 Jun 2026 00:00:00 GMT"  # +12mo target
    response.headers["Link"] = '</v1/redact>; rel="successor-version"'
    return _do_redact(req, user, request, endpoint="/v1/debug/redaction_preview")


# ---------- Audit append (for digiRunner post-LLM hooks) ----------

class AuditAppendRequest(BaseModel):
    """Body schema for POST /v1/audit/append.

    SECURITY INVARIANT: this schema deliberately omits `user_id` and
    `tenant_id`. Those are tagged from the gateway-trusted auth context so an
    upstream caller cannot forge audit rows on behalf of another user.

    `extra="forbid"` makes that invariant load-bearing: a body containing
    `user_id`/`tenant_id` (or any other unexpected key) is rejected with 422
    rather than silently dropped, so a future copy-paste error setting
    `extra="allow"` can't quietly turn this into audit forgery.
    """
    # `model_used` happens to start with "model_", which Pydantic v2 reserves
    # by default; explicitly disable the protected-namespace check so the
    # import doesn't emit a warning. `extra="forbid"` enforces the documented
    # security invariant — see class docstring.
    model_config = {"protected_namespaces": (), "extra": "forbid"}

    # Caps prevent unbounded strings from ballooning the hash-chained log.
    case_id: str = Field(..., max_length=256)
    endpoint: str = Field(..., max_length=256)
    model_used: Optional[str] = Field(default=None, max_length=128)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    masked_field_rules: list[str] = Field(default_factory=list)
    policy_decisions: dict[str, bool] = Field(default_factory=dict)
    error: Optional[str] = Field(default=None, max_length=2048)


# Roles permitted to call /v1/audit/append. PARALEGAL is excluded — the audit
# chain is auditor / it_admin territory; attorneys may need to record analysis
# events for cases they handle. Phase 2.4 should add a dedicated SERVICE_ACCOUNT
# role and tighten this further.
_AUDIT_APPEND_ROLES: frozenset[UserRole] = frozenset({
    UserRole.ATTORNEY,
    UserRole.IT_ADMIN,
    UserRole.AUDITOR,
})


@app.post("/v1/audit/append")
def audit_append(
    req: AuditAppendRequest,
    user: User = Depends(auth_dependency),
):
    """Append one row to the tenant's audit hash-chain.

    Used by digiRunner post-LLM hooks to record the LLM result + cost +
    policy decisions after a transform plugin invoked /v1/redact and the
    request was forwarded to an external LLM gateway outside our orchestrator.

    Caller-supplied fields (case_id, endpoint, model_used, token counts,
    latency, masked rules, policy decisions, error) are recorded verbatim.
    `user_id` and `tenant_id` come from the AUTH CONTEXT — NOT from the
    request body — so an upstream cannot impersonate another user.

    Permission model:
      - Role gate: only ATTORNEY / IT_ADMIN / AUDITOR (paralegal blocked —
        they shouldn't be filing audit-chain entries directly).
      - Case ACL: enforced via authorize_case_access — even an attorney can
        only append rows for cases they have ACL on. This blocks a logged-in
        user from polluting the hash-chained log with rows referencing
        case_ids they don't own (caught by Day 8B review — see commit msg).
    """
    started = time.monotonic()
    # Build the "real" audit row (the one requested by the caller) up front
    # so the finally block can emit it on success, or fall through to an
    # error row on failure. We never want to write TWO rows for a single
    # request — invariant #4 says "exactly one".
    error: Optional[BaseException] = None
    appended_ok = False
    try:
        if user.role not in _AUDIT_APPEND_ROLES:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user.role.value}' is not permitted to append audit rows.",
            )
        # C-3: Re-check ACL on the body-supplied case_id. auth_dependency
        # only inspected X-Case-Id (the body was opaque to it).
        authorize_case_access(user, req.case_id)

        # `policy_decisions` is typed `dict[str, bool]` on the writer, so we
        # keep a boolean flag for "did an error happen" and preserve the raw
        # error string in `response_payload`.
        policy_decisions = dict(req.policy_decisions)
        if req.error:
            policy_decisions["error"] = True

        _safe_audit_write(
            user=user,                       # gateway-trusted; supplies user_id + tenant_id
            case_id=req.case_id,
            endpoint=req.endpoint,
            request_payload={"source": "audit_append"},
            response_payload={"error": req.error} if req.error else None,
            masked_rules=req.masked_field_rules,
            model_used=req.model_used,
            prompt_tokens=req.prompt_tokens,
            completion_tokens=req.completion_tokens,
            latency_ms=req.latency_ms,
            policy_decisions=policy_decisions,
        )
        appended_ok = True
        return {"appended": True}
    except BaseException as exc:  # noqa: BLE001 — must reach the finally
        error = exc
        raise
    finally:
        # Only write an error row when the caller-supplied append failed
        # BEFORE we wrote it ourselves (e.g. role gate rejected, ACL
        # rejected). If the append itself succeeded the row above is the
        # one audit row for this request — don't write a second.
        if not appended_ok:
            _safe_audit_write(
                user=user,
                case_id=req.case_id,
                endpoint="/v1/audit/append",
                request_payload={"source": "audit_append", "intended_endpoint": req.endpoint},
                response_payload=_error_response_payload(error) if error is not None else None,
                masked_rules=[],
                model_used=None,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                policy_decisions={"authn_passed": True, "error": True},
            )


if __name__ == "__main__":
    import uvicorn
    # M-9: bind 127.0.0.1 by default (was 0.0.0.0 — exposed on every LAN
    # interface). Production runs behind digiRunner / nginx; the
    # reverse-proxy IS the public edge, not this process. Override via
    # `LISTEN_HOST=0.0.0.0` for a deployment where this binary IS the edge.
    uvicorn.run("backend.gateway.main:app", host=settings.LISTEN_HOST, port=settings.GATEWAY_PORT, reload=False)
