from __future__ import annotations

import hashlib
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from backend.ai_engine import oa_analyzer, rag
from backend.ai_engine.deadline import calculate_deadline
from backend.gateway import masking
from backend.gateway.auth import _USERS, auth_dependency, issue_token
from backend.patent_db.seed import DEMO_PATENTS
from backend.shared.config import settings
from backend.shared.models import (
    AnalysisRequest,
    AnalysisResponse,
    CostMeta,
    DeadlineInfo,
    DraftResponse,
    OADocument,
    Patent,
    RetrievalHit,
    User,
)

app = FastAPI(
    title="PatentMind Minimal MVP Backend",
    version="0.1.0",
    description="Single-process minimal backend for OA analysis.",
)


class LoginRequest(BaseModel):
    user_id: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    tenant_id: str
    role: str
    display_name: str


class RedactionPreviewRequest(BaseModel):
    text: str


@app.on_event("startup")
def startup_index_demo_patents() -> None:
    """Load the demo patent corpus into the in-memory RAG store on startup."""
    for p in DEMO_PATENTS:
        patent = Patent(
            patent_no=p["patent_no"],
            title=p["title"],
            abstract=p["abstract"],
            claims=p["claims"],
            publication_date=p["publication_date"],
            jurisdiction=p["jurisdiction"],
            is_local=p["is_local"],
        )
        rag.index_patent(p["tenant_id"], patent, spec_text=p.get("spec_text", ""))


@app.on_event("startup")
def startup_index_synthetic_cases() -> None:
    """Seed the 30 synthetic cases' patents into RAG so retrieval has real
    same-domain hits to surface during demos. Skipped silently if the
    synthetic_cases module isn't available (Phase B not yet produced).
    """
    import sys
    from datetime import datetime
    try:
        from data.cases.synthetic_cases import CASES
    except Exception as exc:
        sys.stderr.write(f"[seed-cases] skipped, synthetic_cases not available: {exc}\n")
        return

    already_indexed = {p["patent_no"] for p in DEMO_PATENTS}
    seeded = 0
    for case in CASES:
        pdict = case.get("patent") or {}
        pno = pdict.get("patent_no")
        if not pno or pno in already_indexed:
            continue
        y, m, d = pdict.get("publication_date_roc") or (115, 1, 1)
        try:
            patent = Patent(
                patent_no=pno,
                title=pdict.get("title", ""),
                abstract=pdict.get("abstract", ""),
                claims=pdict.get("claims", []),
                publication_date=datetime(y + 1911, m, d),
                jurisdiction=pdict.get("jurisdiction", "TW"),
                is_local=True,
            )
            rag.index_patent("tenant_a", patent, spec_text=pdict.get("spec_text", ""))
            already_indexed.add(pno)
            seeded += 1
        except Exception as exc:  # don't kill startup on one bad case
            sys.stderr.write(f"[seed-cases] failed {pno}: {exc}\n")
    sys.stderr.write(f"[seed-cases] indexed {seeded} synthetic patents into tenant_a\n")
    sys.stderr.flush()


@app.on_event("startup")
def startup_prewarm_local_llm() -> None:
    """Pre-load llama3.1:8b into Ollama's memory so the first user request
    doesn't pay the ~30-60s cold-load tax. Only runs in LLM_MODE=local.
    Errors are non-fatal: if Ollama is down we just skip and let the
    in-request fallback handle it.
    """
    if settings.LLM_MODE != "local":
        return
    import sys
    import time as _time
    from backend.ai_engine.llm_client import chat as _chat
    sys.stderr.write(f"[prewarm] warming {settings.LLM_MODEL_LOCAL} via Ollama...\n")
    sys.stderr.flush()
    t0 = _time.monotonic()
    try:
        r = _chat(
            system="You output JSON only.",
            user='Reply exactly: {"warm": true}',
            intent="parse_oa",
            security_level="public",
        )
        dt = _time.monotonic() - t0
        sys.stderr.write(
            f"[prewarm] done in {dt:.1f}s model={r.model} latency_ms={r.latency_ms}\n"
        )
    except Exception as exc:  # pragma: no cover - warmup is best-effort
        sys.stderr.write(f"[prewarm] skipped: {exc}\n")
    sys.stderr.flush()


@app.post("/v1/auth/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    if req.user_id not in _USERS:
        raise HTTPException(status_code=404, detail=f"user {req.user_id} not found")
    user = _USERS[req.user_id]
    return LoginResponse(
        token=issue_token(req.user_id),
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        display_name=user.display_name,
    )


@app.get("/v1/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "minimal-backend",
        "vector_stats": rag.stats(),
    }


@app.get("/v1/quota")
def quota(case_id: str = "", user: User = Depends(auth_dependency)) -> dict:
    # Shape matches what frontend Analyze.jsx renders.
    return {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "case_id": case_id,
        "user_daily_used": 0,
        "user_daily_limit": settings.DEFAULT_DAILY_TOKENS,
        "tenant_monthly_used": 0,
        "tenant_monthly_cap": settings.TENANT_MONTHLY_TOKENS,
        "rpm_used": 0,
        "rpm_limit": settings.DEFAULT_RPM,
        "circuit_breaker": {
            "current_usd": 0.0,
            "threshold_usd": settings.COST_CIRCUIT_DAILY_USD,
            "tripped": False,
        },
    }


@app.get("/v1/audit/recent")
def audit_recent(limit: int = 50, user: User = Depends(auth_dependency)) -> dict:
    return {"items": [], "tenant_id": user.tenant_id}


@app.get("/v1/audit/verify")
def audit_verify(user: User = Depends(auth_dependency)) -> dict:
    return {"valid": True, "rows_checked": 0, "broken_at": None, "tenant_id": user.tenant_id}


# In-process response cache (MVP).
# Key:  tenant_id:user_id:case_id:sha256(oa_text|target|hint)
# Value: (AnalysisResponse, inserted_at_epoch)
# TTL keeps the cache from going stale across long sessions; size cap stops
# unbounded growth during a busy demo (FIFO eviction).
_RESPONSE_CACHE: dict[str, tuple[AnalysisResponse, float]] = {}
_CACHE_TTL_SEC = 3600
_CACHE_MAX_ENTRIES = 64


def _cache_key(user: User, req: AnalysisRequest) -> str:
    payload = "|".join([req.oa_text, req.target_patent_no, req.user_hint or ""])
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"{user.tenant_id}:{user.user_id}:{req.case_id}:{h}"


@app.post("/v1/oa/analyze", response_model=AnalysisResponse)
def analyze_oa(
    body: AnalysisRequest,
    user: User = Depends(auth_dependency),
) -> AnalysisResponse:
    key = _cache_key(user, body)
    cached = _RESPONSE_CACHE.get(key)
    if cached is not None:
        resp, inserted_at = cached
        if time.time() - inserted_at < _CACHE_TTL_SEC:
            cached_copy = resp.model_copy(deep=True)
            cached_copy.request_id = str(int(time.time() * 1000))
            cached_copy.cost_meta.cache_hit = True
            cached_copy.cost_meta.model = "cache"
            cached_copy.cost_meta.estimated_cost_usd = 0.0
            return cached_copy

    response, _meta = _orchestrate_analysis(user, body)

    if len(_RESPONSE_CACHE) >= _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_RESPONSE_CACHE))
        _RESPONSE_CACHE.pop(oldest_key, None)
    _RESPONSE_CACHE[key] = (response, time.time())
    return response


@app.post("/v1/debug/redaction_preview")
def redaction_preview(
    req: RedactionPreviewRequest,
    user: User = Depends(auth_dependency),
) -> dict[str, object]:
    redacted, rules = masking.redact(req.text, user.tenant_id)
    # frontend Analyze.jsx reads .redacted; keep redacted_text alias for callers.
    return {"redacted": redacted, "redacted_text": redacted, "rules_triggered": rules}


def _orchestrate_analysis(user: User, req: AnalysisRequest) -> tuple[AnalysisResponse, dict[str, object]]:
    started = time.monotonic()

    redacted_oa, mask_rules_triggered = masking.redact(req.oa_text, user.tenant_id)

    rejections, parse_meta = oa_analyzer.parse_oa(redacted_oa, req.target_patent_no)
    oa_doc = oa_analyzer.make_oa_document(
        tenant_id=user.tenant_id,
        case_id=req.case_id,
        target_patent_no=req.target_patent_no,
        oa_text=redacted_oa,
        rejections=rejections,
    )

    all_hits: list[RetrievalHit] = []
    hits_by_rejection: dict[str, list[RetrievalHit]] = {}
    for rejection in oa_doc.rejections:
        hits = rag.retrieve(
            user.tenant_id,
            rejection.examiner_argument + " " + " ".join(rejection.cited_prior_art),
            top_k=5,
            prefer_patent_no=req.target_patent_no,
        )
        hits_by_rejection[rejection.rejection_id] = hits
        all_hits.extend(hits)

    drafts: list[DraftResponse] = []
    draft_prompt_tokens = 0
    draft_completion_tokens = 0
    verification_usage_tokens = 0
    verification_completion_tokens = 0
    valid_model = parse_meta.get("model_used", "mock")

    for rejection in oa_doc.rejections:
        grounded_set = hits_by_rejection[rejection.rejection_id]
        draft, draft_meta = oa_analyzer.draft_response(
            rejection,
            grounded_set,
            req.user_hint,
            security_level=_security_level_for_case(req.case_id),
        )
        verification, verify_meta = oa_analyzer.verify_citations(draft, grounded_set)
        draft.draft_text = verification["cleaned_draft_text"]
        draft.grounded_citations = verification["valid_citations"]
        draft.confidence = min(draft.confidence, float(verification["verifier_confidence"]))
        drafts.append(draft)
        draft_prompt_tokens += draft_meta["usage"]["prompt_tokens"]
        draft_completion_tokens += draft_meta["usage"]["completion_tokens"]
        verification_usage_tokens += verify_meta["usage"]["prompt_tokens"]
        verification_completion_tokens += verify_meta["usage"]["completion_tokens"]
        valid_model = draft_meta.get("model_used", valid_model)

    deadline_data = calculate_deadline(
        oa_doc.received_date,
        jurisdiction="TW",
        calendar_version=settings.HOLIDAY_CALENDAR_VERSION,
    )
    deadline = DeadlineInfo(**deadline_data)
    oa_doc.deadline = deadline.statutory_deadline

    for draft in drafts:
        draft.draft_text = masking.unmask(draft.draft_text, user.tenant_id)
        draft.strategy = masking.unmask(draft.strategy, user.tenant_id)

    prompt_tokens = (
        parse_meta["usage"]["prompt_tokens"]
        + draft_prompt_tokens
        + verification_usage_tokens
    )
    completion_tokens = (
        parse_meta["usage"]["completion_tokens"]
        + draft_completion_tokens
        + verification_completion_tokens
    )
    estimated_cost = (prompt_tokens * 3 + completion_tokens * 15) / 1_000_000

    cost_meta = CostMeta(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=valid_model,
        estimated_cost_usd=estimated_cost,
        cache_hit=False,
    )

    response = AnalysisResponse(
        request_id=str(int(time.time() * 1000)),
        oa=oa_doc,
        drafts=drafts,
        related_prior_art=all_hits,
        deadline_summary=deadline,
        cost_meta=cost_meta,
    )
    meta = {
        "duration_ms": int((time.monotonic() - started) * 1000),
        "mask_rules": mask_rules_triggered,
        "model_used": valid_model,
    }
    return response, meta


def _security_level_for_case(case_id: str) -> str:
    if case_id.upper().endswith("-CONF"):
        return "confidential"
    return "public"
