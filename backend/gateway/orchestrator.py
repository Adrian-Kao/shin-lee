"""Gateway orchestrator (Q1 厚 Gateway + Follow-up C 混合 orchestration).

The Gateway owns the *business* flow:
    1. parse OA  → call AI Engine /v1/parse_oa
    2. for each rejection → call AI Engine /v1/retrieve_prior_art
    3. for each rejection → call AI Engine /v1/draft_response
    4. verify drafts → call AI Engine /v1/verify_citations
    5. compute deadline → call AI Engine /v1/deadline
    6. assemble final AnalysisResponse

The AI Engine (Dify mock) only does **single-step AI inference**.
No business state lives in Dify.  This makes business logic unit-testable
and lets us swap AI providers without touching orchestration.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx

from backend.gateway import cache, masking
from backend.gateway.auth import _internal_headers
from backend.gateway.rate_limit import estimate_cost
from backend.shared.config import settings
from backend.shared.models import (
    AnalysisRequest,
    AnalysisResponse,
    CostMeta,
    DeadlineInfo,
    DraftResponse,
    OADocument,
    Rejection,
    RetrievalHit,
    User,
)


class AIEngineClient:
    """Thin client to the Dify-mock service."""

    def __init__(self, base_url: str = settings.AI_ENGINE_URL):
        self.base_url = base_url.rstrip("/")

    async def call(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Security Chunk A — C-2. AI Engine's middleware refuses any
            # non-`/v1/health` request that lacks X-Internal-Token. The
            # token is server-side only; the SPA never sees it.
            r = await client.post(url, json=payload, headers=_internal_headers())
            r.raise_for_status()
            return r.json()


async def orchestrate_analysis(
    user: User,
    req: AnalysisRequest,
) -> tuple[AnalysisResponse, dict[str, Any]]:
    """Main flow.  Returns (response, observability_meta).

    observability_meta is fed into audit + metrics.
    """
    started = time.monotonic()
    request_id = str(uuid.uuid4())
    ai = AIEngineClient()

    # ---- Step 0: redact OA before anything leaves the gateway (Q3 + Q10) ----
    redacted_oa, mask_rules_triggered = masking.redact(req.oa_text, user.tenant_id)

    # ---- Step 1: parse OA → identify rejections ----
    parse_payload = {
        "oa_text": redacted_oa,
        "tenant_id": user.tenant_id,
        "case_id": req.case_id,
        "target_patent_no": req.target_patent_no,
        "security_level": _security_level_for_case(req.case_id),
    }
    parsed = await ai.call("/v1/parse_oa", parse_payload)
    oa_doc = OADocument(**parsed["oa"])

    # ---- Step 2: per-rejection retrieval ----
    retrieve_tasks = [
        ai.call("/v1/retrieve_prior_art", {
            "tenant_id": user.tenant_id,
            "rejection": rej.model_dump(),
            "target_patent_no": req.target_patent_no,
            "top_k": 5,
        })
        for rej in oa_doc.rejections
    ]
    retrieval_results = await asyncio.gather(*retrieve_tasks)

    all_hits: list[RetrievalHit] = []
    hits_by_rejection: dict[str, list[RetrievalHit]] = {}
    for rej, ret in zip(oa_doc.rejections, retrieval_results):
        hits = [RetrievalHit(**h) for h in ret["hits"]]
        all_hits.extend(hits)
        hits_by_rejection[rej.rejection_id] = hits

    # ---- Step 3: per-rejection draft ----
    # NB: we send the *grounded set* (retrieval hits) so LLM can only cite from there (Q14).
    draft_tasks = [
        ai.call("/v1/draft_response", {
            "tenant_id": user.tenant_id,
            "user_id": user.user_id,
            "case_id": req.case_id,
            "rejection": rej.model_dump(),
            "grounded_set": [h.model_dump() for h in hits_by_rejection[rej.rejection_id]],
            "user_hint": req.user_hint,
            "security_level": _security_level_for_case(req.case_id),
        })
        for rej in oa_doc.rejections
    ]
    draft_results = await asyncio.gather(*draft_tasks)
    drafts = [DraftResponse(**d["draft"]) for d in draft_results]

    # ---- Step 4: verifier (Q14 third defence) ----
    verify_tasks = [
        ai.call("/v1/verify_citations", {
            "draft": d.model_dump(),
            "grounded_set": [h.model_dump() for h in hits_by_rejection[d.rejection_id]],
        })
        for d in drafts
    ]
    verifications = await asyncio.gather(*verify_tasks)
    for d, v in zip(drafts, verifications):
        # Replace the draft with the verifier-cleaned version
        d.draft_text = v["cleaned_draft_text"]
        d.grounded_citations = v["valid_citations"]
        d.confidence = min(d.confidence, v["verifier_confidence"])

    # ---- Step 5: deadline (Q17) ----
    deadline_resp = await ai.call("/v1/deadline", {
        "received_date_iso": oa_doc.received_date.isoformat(),
        "jurisdiction": "TW",  # POC: derive from case metadata in production
        "calendar_version": settings.HOLIDAY_CALENDAR_VERSION,
    })
    deadline = DeadlineInfo(**deadline_resp)
    oa_doc.deadline = deadline.statutory_deadline

    # ---- Step 6: un-mask outbound for attorney's eyes ----
    for d in drafts:
        d.draft_text = masking.unmask(d.draft_text, user.tenant_id)
        d.strategy = masking.unmask(d.strategy, user.tenant_id)

    # ---- Aggregate cost ----
    # Each AI engine response carries an Anthropic-style usage dict (also
    # populated for mock/Ollama with zero cache fields). We aggregate by
    # call, run estimate_cost() per call against its own model_used (parse
    # and draft are typically the reasoning model; verify is the cheap
    # verifier), then sum. This keeps cache-discount accuracy intact.
    all_call_meta = (
        [parsed]
        + list(retrieval_results)
        + list(draft_results)
        + list(verifications)
    )
    total_prompt_tokens = sum(r.get("usage", {}).get("prompt_tokens", 0) for r in all_call_meta)
    total_completion_tokens = sum(r.get("usage", {}).get("completion_tokens", 0) for r in all_call_meta)

    estimated_cost = 0.0
    for r in all_call_meta:
        usage = r.get("usage") or {}
        model = r.get("model_used", "mock")
        # Skip pricing for retrieval (no LLM call) — its usage row is all zeros anyway.
        if not usage:
            continue
        estimated_cost += estimate_cost(model, usage)

    cost_meta = CostMeta(
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        model=parsed.get("model_used", "mock"),
        estimated_cost_usd=estimated_cost,
        cache_hit=False,
    )

    response = AnalysisResponse(
        request_id=request_id,
        oa=oa_doc,
        drafts=drafts,
        related_prior_art=all_hits,
        deadline_summary=deadline,
        cost_meta=cost_meta,
    )

    obs = {
        "duration_ms": int((time.monotonic() - started) * 1000),
        "mask_rules": mask_rules_triggered,
        "model_used": cost_meta.model,
        "prompt_tokens": cost_meta.prompt_tokens,
        "completion_tokens": cost_meta.completion_tokens,
        "estimated_cost_usd": cost_meta.estimated_cost_usd,
    }
    return response, obs


def _security_level_for_case(case_id: str) -> str:
    """Q15: case-level security label drives LLM router.

    POC: simple convention — case ids ending with -CONF use confidential.
    Production: read from case management system.
    """
    if case_id.upper().endswith("-CONF"):
        return "confidential"
    return "public"
