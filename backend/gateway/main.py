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
import time
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.gateway import audit, cache, masking, rate_limit
from backend.gateway.auth import auth_dependency, authorize_case_access, issue_token
from backend.gateway.orchestrator import orchestrate_analysis
from backend.shared.config import settings
from backend.shared.models import AnalysisRequest, AnalysisResponse, User, UserRole
from backend.shared.observability import init_sentry

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Login (POC simplified) ----------

class LoginRequest(BaseModel):
    user_id: str  # POC: pass user_id directly. Production: IdP redirect.


class LoginResponse(BaseModel):
    token: str
    user_id: str
    tenant_id: str
    role: str
    display_name: str


@app.post("/v1/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    """Issue a JWT for one of the demo users.

    POC IdP modes (Q12) all converge here:
      - built-in:    POST /v1/auth/login (this endpoint)
      - OIDC:        /v1/auth/oidc/callback (TODO with Claude Code)
      - SAML:        /v1/auth/saml/acs (TODO)
      - magic link:  /v1/auth/magic/{token} (TODO)
    """
    from backend.gateway.auth import _USERS
    if req.user_id not in _USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {req.user_id} not found")
    user = _USERS[req.user_id]
    return LoginResponse(
        token=issue_token(req.user_id),
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        display_name=user.display_name,
    )


# ---------- Health / Quota dashboard (Q19) ----------

@app.get("/v1/health")
def health():
    return {
        "ok": True,
        "service": "gateway",
        "circuit_breaker": rate_limit.cost_circuit_state(),
        "cache_stats": cache.stats(),
    }


@app.get("/v1/quota")
def quota(user: User = Depends(auth_dependency)):
    return rate_limit.get_quota_snapshot(user)


# ---------- Main analysis endpoint ----------

@app.post("/v1/oa/analyze", response_model=AnalysisResponse)
async def analyze_oa(
    body: AnalysisRequest,
    request: Request,
    user: User = Depends(auth_dependency),
):
    """Q1 厚 Gateway core endpoint.

    Steps (with policy gates):
      1. RPM check
      2. Request size hard cap
      3. Estimate token need; quota check
      4. Cache lookup (per Q9 namespacing)
      5. Orchestrate via AI Engine
      6. Record usage + circuit breaker check
      7. Audit log
    """
    started = time.monotonic()
    policy_decisions = {
        "authn_passed": True,
        "authz_passed": True,  # auth_dependency already validated case_id
        "rate_limit_passed": False,
        "quota_passed": False,
        "circuit_open": False,
    }

    # 1. RPM
    rate_limit.check_rpm(user)
    policy_decisions["rate_limit_passed"] = True

    # 2. Hard cap
    estimated_tokens = max(1, len(body.oa_text) // 3)
    rate_limit.check_request_size(estimated_tokens)

    # 3. Quota
    rate_limit.check_quotas(user, estimated_tokens)
    policy_decisions["quota_passed"] = True

    # 4. Cache (Q9)
    prompt_hash = cache.hash_prompt(body.oa_text + body.target_patent_no, "orchestrator-v1")
    cached = cache.get_response(user.tenant_id, user.user_id, body.case_id, prompt_hash)
    if cached:
        # POC: still write audit row even on cache hit
        audit.writer.write(
            user=user,
            case_id=body.case_id,
            endpoint="/v1/oa/analyze",
            request_payload=body.model_dump(),
            response_payload=cached,
            masked_rules=[],
            model_used="cache",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            policy_decisions={**policy_decisions, "cache_hit": True},
        )
        return AnalysisResponse(**cached)

    # 5. Circuit breaker
    if rate_limit.cost_circuit_state()["tripped"]:
        policy_decisions["circuit_open"] = True
        # POC behavior: still serve, but the LLM router will degrade to cheap model.
        # In production: optionally 503 here for graceful shedding.

    # 6. Orchestrate
    response, obs = await orchestrate_analysis(user, body)

    # 7. Record usage
    rate_limit.record_usage(
        user,
        prompt_tokens=obs["prompt_tokens"],
        completion_tokens=obs["completion_tokens"],
        cost_usd=obs["estimated_cost_usd"],
    )

    # 8. Cache write
    cache.set_response(user.tenant_id, user.user_id, body.case_id, prompt_hash, response.model_dump(mode="json"))

    # 9. Audit
    audit.writer.write(
        user=user,
        case_id=body.case_id,
        endpoint="/v1/oa/analyze",
        request_payload=body.model_dump(),
        response_payload=response.model_dump(mode="json"),
        masked_rules=obs["mask_rules"],
        model_used=obs["model_used"],
        prompt_tokens=obs["prompt_tokens"],
        completion_tokens=obs["completion_tokens"],
        latency_ms=obs["duration_ms"],
        policy_decisions={**policy_decisions, "cache_hit": False},
    )

    return response


# ---------- Day 2 upload endpoint ----------

@app.post("/v1/oa/upload")
async def upload_oa(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(auth_dependency),
):
    """Day 2: accept a PDF/DOCX, return extracted text for use by /v1/oa/analyze.

    Layering rules respected:
      - Auth + case ACL: handled by `auth_dependency` via X-Case-Id header.
      - Confidential routing: this endpoint REFUSES confidential cases. They
        must use manual text paste — uploading would push pages through cloud
        Vision OCR which is forbidden by security policy (Q15).
      - Gateway never calls the LLM directly: bytes are base64-encoded and
        forwarded to the AI Engine `/v1/ai/extract_text` endpoint.
      - Redaction: NOT applied here. The extracted text is returned to the
        attorney; redaction happens at /v1/oa/analyze time as before.
      - Audit: writes a row recording file size + page count + ocr count +
        cost — NEVER the extracted text itself.
      - Rate limit + cost circuit: 1 request, cost = vision OCR usage.
    """
    started = time.monotonic()
    policy_decisions = {
        "authn_passed": True,
        "authz_passed": True,
        "rate_limit_passed": False,
        "upload_size_passed": False,
        "upload_type_passed": False,
        "confidential_blocked": False,
    }

    # Pull case_id explicitly: multipart bodies are streams so auth_dependency
    # can't autodetect it from body the way it does for JSON POSTs.
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
    if not case_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X-Case-Id header required for upload",
        )
    # auth_dependency already enforced ACL when case_id was on the header.

    # Block confidential cases at the EDGE. Defense in depth: pdf_parser will
    # also refuse, but we want to reject before reading the upload body so
    # large privileged scans never even enter our process memory.
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

    # Read the file into memory and enforce the byte cap. Reading in one shot
    # is fine because the cap is single-digit MB by default; we explicitly
    # avoid streaming-to-disk per the "bytes never touch disk" requirement.
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
            ai_resp = await client.post(ai_url, json=payload)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"AI engine unreachable: {exc}",
            )

    if ai_resp.status_code >= 400:
        # Mirror the AI engine status when meaningful, otherwise 502.
        # We surface the detail body so the frontend can show a useful error
        # (e.g. "PDF is password-protected").
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

    # Account for cost + quota. Cost counts toward the daily circuit breaker.
    rate_limit.record_usage(
        user,
        prompt_tokens=int(usage.get("input_tokens", 0) or 0),
        completion_tokens=int(usage.get("output_tokens", 0) or 0),
        cost_usd=cost_usd,
    )

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit row — NEVER store the extracted text. Only metrics + counts.
    audit.writer.write(
        user=user,
        case_id=case_id,
        endpoint="/v1/oa/upload",
        request_payload={
            "file_size_bytes": file_size,
            "content_type": file.content_type,
            "filename": file.filename,
        },
        response_payload={
            "page_count": page_count,
            "ocr_pages_count": len(ocr_pages_used),
            "char_count": int(body.get("char_count", 0) or 0),
            "cost_usd": cost_usd,
        },
        masked_rules=[],
        model_used=settings.LLM_MODEL_CHEAP if ocr_pages_used else "none",
        prompt_tokens=int(usage.get("input_tokens", 0) or 0),
        completion_tokens=int(usage.get("output_tokens", 0) or 0),
        latency_ms=duration_ms,
        policy_decisions=policy_decisions,
    )

    return {
        "extracted_text": extracted_text,
        "page_count": page_count,
        "ocr_pages_used": ocr_pages_used,
        "char_count": int(body.get("char_count", 0) or 0),
        "warnings": body.get("warnings", []) or [],
        "cost_meta": {
            "estimated_cost_usd": cost_usd,
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(
                usage.get("cache_creation_input_tokens", 0) or 0
            ),
        },
    }


# ---------- Audit query endpoints (for the Auditor role) ----------

@app.get("/v1/audit/recent")
def audit_recent(limit: int = 50, user: User = Depends(auth_dependency)):
    if user.role.value not in ("auditor", "it_admin"):
        raise HTTPException(403, "auditor or it_admin role required")
    return audit.writer.list_for_tenant(user.tenant_id, limit=limit)


@app.get("/v1/audit/verify")
def audit_verify(user: User = Depends(auth_dependency)):
    """Walk the audit chain, recompute hashes, report broken rows (Q13 tamper evidence)."""
    if user.role.value not in ("auditor", "it_admin"):
        raise HTTPException(403, "auditor or it_admin role required")
    return audit.writer.verify_chain(user.tenant_id)


# ---------- Redaction (first-class for digiRunner pre-LLM transform plugins) ----------

class RedactionPreviewRequest(BaseModel):
    text: str


def _do_redact(req: RedactionPreviewRequest, user: User, request: Request, endpoint: str) -> dict:
    """Shared implementation for /v1/redact and its deprecated alias.

    Writes exactly one audit row per call (invariant #4) — the input text is
    NEVER stored, only its hash + the rule ids that fired.
    """
    started = time.monotonic()
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
    if not case_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X-Case-Id header required for redaction (tenant routing)",
        )
    # auth_dependency already enforced ACL when case_id was on the header.

    redacted, rules = masking.redact(req.text, user.tenant_id)

    audit.writer.write(
        user=user,
        case_id=case_id,
        endpoint=endpoint,
        # Never store raw text in audit — only its length + content hash via the
        # writer's _hash_payload mechanism.
        request_payload={"text_chars": len(req.text)},
        response_payload={"rules_triggered": rules, "redacted_chars": len(redacted)},
        masked_rules=rules,
        model_used=None,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=int((time.monotonic() - started) * 1000),
        policy_decisions={"authn_passed": True, "authz_passed": True},
    )
    return {"redacted": redacted, "rules_triggered": rules}


@app.post("/v1/redact")
def redact(
    req: RedactionPreviewRequest,
    request: Request,
    user: User = Depends(auth_dependency),
):
    """First-class redaction endpoint.

    Intended for digiRunner pre-LLM transform plugins that need to scrub user
    input before forwarding to the LLM gateway. Same shape as the legacy
    /v1/debug/redaction_preview alias (which now delegates here).

    Requires:
      - Authorization: Bearer <token>
      - X-Case-Id: <case_id>  (for tenant routing inside masking + ACL check)
    """
    return _do_redact(req, user, request, endpoint="/v1/redact")


@app.post("/v1/debug/redaction_preview", deprecated=True)
def redaction_preview(
    req: RedactionPreviewRequest,
    request: Request,
    response: Response,
    user: User = Depends(auth_dependency),
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
    if user.role not in _AUDIT_APPEND_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Role '{user.role.value}' is not permitted to append audit rows.",
        )
    # Re-check ACL: auth_dependency only validates X-Case-Id (header). The
    # case_id here is in the body, which auth_dependency never saw.
    authorize_case_access(user, req.case_id)

    # `policy_decisions` is typed `dict[str, bool]` on the writer, so we keep
    # a boolean flag for "did an error happen" and preserve the raw error
    # string in `response_payload` (which IS stored verbatim, not just hashed).
    policy_decisions = dict(req.policy_decisions)
    if req.error:
        policy_decisions["error"] = True

    audit.writer.write(
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
    return {"appended": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.gateway.main:app", host="0.0.0.0", port=settings.GATEWAY_PORT, reload=False)
