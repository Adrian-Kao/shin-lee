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

import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.gateway import audit, cache, masking, rate_limit
from backend.gateway.auth import auth_dependency, issue_token
from backend.gateway.orchestrator import orchestrate_analysis
from backend.shared.config import settings
from backend.shared.models import AnalysisRequest, AnalysisResponse, User

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


# ---------- Redaction inspection (debug only) ----------

class RedactionPreviewRequest(BaseModel):
    text: str


@app.post("/v1/debug/redaction_preview")
def redaction_preview(
    req: RedactionPreviewRequest,
    user: User = Depends(auth_dependency),
):
    """Useful for showing the attorney exactly what gets redacted before send."""
    redacted, rules = masking.redact(req.text, user.tenant_id)
    return {"redacted": redacted, "rules_triggered": rules}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.gateway.main:app", host="0.0.0.0", port=settings.GATEWAY_PORT, reload=False)
