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
import logging
import time
import uuid
from typing import Any

import httpx

from backend.gateway import cache, masking
from backend.gateway.auth import _internal_headers
from backend.gateway.rate_limit import cost_provenance_for, estimate_cost
from backend.shared.config import settings
from backend.shared.models import (
    AnalysisRequest,
    AnalysisResponse,
    ClaimNode,
    CostMeta,
    DeadlineInfo,
    DraftResponse,
    OADocument,
    RedactionSummary,
    Rejection,
    RetrievalHit,
    User,
)

logger = logging.getLogger("patentmind.gateway.egress")


class EgressGuardError(Exception):
    """Raised when the egress guard detects raw (un-redacted) PII in an
    outbound payload to the AI Engine.

    Invariant #3 (Q3 + Q10): redaction is mandatory before any LLM call.
    Hitting this means the masking layer was bypassed for some field — we
    FAIL CLOSED (block the call) rather than leak PII to the AI Engine.
    """

    def __init__(self, rule_id: str, path: str):
        self.rule_id = rule_id
        self.path = path
        super().__init__(
            f"EGRESS GUARD: unredacted PII pattern {rule_id!r} detected in "
            f"outbound payload to {path!r}"
        )


def _scan_value_for_pii(value: Any) -> str | None:
    """Recursively scan a JSON-serialisable value for raw PII patterns.

    Reuses the *already-compiled* `masking.PII_RULES` patterns (compiled once
    at import time in masking.py) — no per-call recompile / re-import.

    Returns the first matching `rule_id` (so the caller can name it in the
    alert), or None if the value is clean.

    Placeholders like ``[EMAIL_A1B2C3D4]`` are *expected* to pass: the email
    regex requires an ``@`` and the bracketed-hex placeholder shape has none,
    and the SSN/ID/phone patterns are anchored on digit runs the placeholder
    doesn't contain. We never strip placeholders before scanning — defence in
    depth means we scan the literal outbound bytes.
    """
    if isinstance(value, str):
        for rule in masking.PII_RULES:
            if rule.pattern.search(value):
                return rule.rule_id
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            # Keys are usually field names (no PII), but scan them too —
            # cheap and closes the "PII smuggled as a dict key" hole.
            if isinstance(k, str):
                for rule in masking.PII_RULES:
                    if rule.pattern.search(k):
                        return rule.rule_id
            hit = _scan_value_for_pii(v)
            if hit is not None:
                return hit
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            hit = _scan_value_for_pii(item)
            if hit is not None:
                return hit
        return None
    # int / float / bool / None — no string content to leak.
    return None


def _assert_no_raw_pii(path: str, payload: dict) -> None:
    """Egress chokepoint enforcing invariant #3.

    If `EGRESS_GUARD_ENABLED` is on (default) and the outbound `payload`
    contains a raw PII pattern, log an error-level alert and raise
    `EgressGuardError` (fail closed). No-op when the guard is disabled.
    """
    if not settings.EGRESS_GUARD_ENABLED:
        return
    rule_id = _scan_value_for_pii(payload)
    if rule_id is not None:
        # Never log the offending value itself — that would re-leak the PII
        # into the log sink. Log the rule id + destination path only.
        logger.error(
            "EGRESS GUARD: unredacted PII pattern %s detected in outbound "
            "payload to %s",
            rule_id,
            path,
        )
        raise EgressGuardError(rule_id, path)


class AIEngineClient:
    """Thin client to the Dify-mock service."""

    def __init__(self, base_url: str = settings.AI_ENGINE_URL):
        self.base_url = base_url.rstrip("/")

    async def call(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        # ---- Egress guard (Q3 / invariant #3) ----
        # This is the SINGLE egress point to the AI Engine. Before any bytes
        # leave the gateway we scan the whole payload for raw PII that should
        # have been redacted upstream. Fail closed if redaction escaped.
        _assert_no_raw_pii(path, payload)
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
    circuit_open: bool = False,
) -> tuple[AnalysisResponse, dict[str, Any]]:
    """Main flow.  Returns (response, observability_meta).

    observability_meta is fed into audit + metrics.

    `circuit_open` is forwarded from the gateway cost circuit breaker (Q18):
    when True the AI Engine degrades the draft model to the cheap tier.
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

    # ---- Step 2: per-rejection retrieval (saga: per-rejection resilient) ----
    # Q1 + Follow-up: the orchestrator is a saga coordinator. One rejection's
    # retrieval failing must NOT sink the others — a failed retrieval degrades
    # to an empty grounded set for that rejection only.
    retrieve_tasks = [
        ai.call("/v1/retrieve_prior_art", {
            "tenant_id": user.tenant_id,
            "rejection": rej.model_dump(),
            "target_patent_no": req.target_patent_no,
            "top_k": 5,
        })
        for rej in oa_doc.rejections
    ]
    retrieval_results = await asyncio.gather(*retrieve_tasks, return_exceptions=True)

    all_hits: list[RetrievalHit] = []
    hits_by_rejection: dict[str, list[RetrievalHit]] = {}
    for rej, ret in zip(oa_doc.rejections, retrieval_results):
        if isinstance(ret, BaseException):
            logger.warning(
                "saga: retrieval failed for rejection %s (%s) — proceeding "
                "with empty grounded set",
                rej.rejection_id,
                ret.__class__.__name__,
            )
            hits_by_rejection[rej.rejection_id] = []
            continue
        hits = [RetrievalHit(**h) for h in ret["hits"]]
        all_hits.extend(hits)
        hits_by_rejection[rej.rejection_id] = hits

    # ---- Step 3: per-rejection draft (saga: per-rejection resilient) ----
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
            "circuit_open": circuit_open,
        })
        for rej in oa_doc.rejections
    ]
    draft_results = await asyncio.gather(*draft_tasks, return_exceptions=True)

    # Build the draft list, substituting a degraded placeholder for any
    # rejection whose draft call raised. `failed_rejection_ids` tracks those
    # so the verify step can skip them (no point verifying a placeholder).
    drafts: list[DraftResponse] = []
    failed_rejection_ids: set[str] = set()
    for rej, dr in zip(oa_doc.rejections, draft_results):
        if isinstance(dr, BaseException):
            logger.warning(
                "saga: draft generation failed for rejection %s (%s) — "
                "emitting degraded placeholder",
                rej.rejection_id,
                dr.__class__.__name__,
            )
            failed_rejection_ids.add(rej.rejection_id)
            drafts.append(_degraded_draft(rej.rejection_id))
            continue
        try:
            drafts.append(DraftResponse(**dr["draft"]))
        except (KeyError, TypeError, ValueError) as exc:
            # Malformed AI Engine response for this rejection — treat as a
            # per-rejection failure, not a whole-request crash.
            logger.warning(
                "saga: malformed draft payload for rejection %s (%s) — "
                "emitting degraded placeholder",
                rej.rejection_id,
                exc.__class__.__name__,
            )
            failed_rejection_ids.add(rej.rejection_id)
            drafts.append(_degraded_draft(rej.rejection_id))

    # ---- Step 4: verifier (Q14 third defence; saga: per-rejection resilient) ----
    # Only verify drafts that actually generated. Placeholders carry no
    # citations and must never reach the verifier (nothing to ground).
    verifiable = [d for d in drafts if d.rejection_id not in failed_rejection_ids]
    verify_tasks = [
        ai.call("/v1/verify_citations", {
            "draft": d.model_dump(),
            "grounded_set": [h.model_dump() for h in hits_by_rejection.get(d.rejection_id, [])],
        })
        for d in verifiable
    ]
    verifications = await asyncio.gather(*verify_tasks, return_exceptions=True)
    for d, v in zip(verifiable, verifications):
        if isinstance(v, BaseException):
            # Verifier failed for this rejection. Q14 is a hard wall: an
            # unverified draft must NOT be served with its (unvalidated)
            # citations. Degrade to a placeholder rather than leak ungrounded
            # citations or crash the whole request.
            logger.warning(
                "saga: citation verification failed for rejection %s (%s) — "
                "emitting degraded placeholder",
                d.rejection_id,
                v.__class__.__name__,
            )
            failed_rejection_ids.add(d.rejection_id)
            for idx, existing in enumerate(drafts):
                if existing.rejection_id == d.rejection_id:
                    drafts[idx] = _degraded_draft(d.rejection_id)
                    break
            continue
        # Replace the draft with the verifier-cleaned version, and surface the
        # verifier's transparency fields (Q14) so the front-end can render the
        # hallucination wall (what was stripped, how confident the verifier
        # was, which model verified) instead of an anonymous [CITATION_REMOVED].
        d.draft_text = v["cleaned_draft_text"]
        d.grounded_citations = v["valid_citations"]
        d.invalid_citations = v.get("invalid_citations", [])
        d.verifier_confidence = v.get("verifier_confidence")
        d.verifier_model = v.get("model_used")
        d.confidence = min(d.confidence, v["verifier_confidence"])

    # ---- Step 5: deadline (Q17) ----
    deadline_resp = await ai.call("/v1/deadline", {
        "received_date_iso": oa_doc.received_date.isoformat(),
        "jurisdiction": _jurisdiction_for_patent(req.target_patent_no),
        "calendar_version": settings.HOLIDAY_CALENDAR_VERSION,
    })
    deadline = DeadlineInfo(**deadline_resp)
    oa_doc.deadline = deadline.statutory_deadline

    # ---- Step 5b: claim tree (UX_RESEARCH §5 #2) ----
    # Pure payload lookup against the indexed target patent; no LLM call,
    # no cost. Defensive: if the AI engine errors or the patent isn't
    # indexed, fall back to an empty tree so the front-end renders normally.
    claim_tree_nodes: list[ClaimNode] = []
    try:
        ct_resp = await ai.call("/v1/claim_tree", {
            "tenant_id": user.tenant_id,
            "patent_no": req.target_patent_no,
        })
        claim_tree_nodes = [ClaimNode(**n) for n in ct_resp.get("claim_tree", [])]
    except Exception:
        # Trees are a presentation nicety — never let their absence break
        # the analysis pipeline. Empty list = "front-end renders nothing"
        # which is what `Field(default_factory=list)` was designed for.
        claim_tree_nodes = []

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
    # Saga: some entries may be Exception objects (a sub-call failed). Filter
    # them out — a failed call produced no billable usage and exposes no
    # `.get`, so including it would crash the aggregation.
    all_call_meta = [
        r
        for r in (
            [parsed]
            + list(retrieval_results)
            + list(draft_results)
            + list(verifications)
        )
        if isinstance(r, dict)
    ]
    total_prompt_tokens = sum(r.get("usage", {}).get("prompt_tokens", 0) for r in all_call_meta)
    total_completion_tokens = sum(r.get("usage", {}).get("completion_tokens", 0) for r in all_call_meta)

    estimated_cost = 0.0
    # M-3 fix: track the *weakest* provenance across every call. Order is
    # exact > fallback > mock (where "weakest" = least trustworthy for
    # billing). If any LLM call dispatched to a fallback-priced model, the
    # aggregate cost is suspect even if other calls were exact-priced.
    # "mock" is preferred over "fallback" only when EVERY call was mock —
    # a single fallback call means at least one real-money error path.
    _provenance_rank = {"exact": 0, "mock": 1, "fallback": 2}
    worst_provenance = "exact"
    for r in all_call_meta:
        usage = r.get("usage") or {}
        model = r.get("model_used", "mock")
        # Skip pricing for retrieval (no LLM call) — its usage row is all zeros anyway.
        if not usage:
            continue
        estimated_cost += estimate_cost(model, usage)
        prov = cost_provenance_for(model)
        if _provenance_rank.get(prov, 99) > _provenance_rank.get(worst_provenance, -1):
            worst_provenance = prov

    cost_meta = CostMeta(
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        model=parsed.get("model_used", "mock"),
        estimated_cost_usd=estimated_cost,
        cache_hit=False,
        cost_provenance=worst_provenance,
    )

    # CHUNK-8 trust band — surface the redaction count so the SPA can show
    # "N entities masked" on THIS analysis. `mask_rules_triggered` is the
    # list of rule ids that fired (one per match); we count distinct
    # occurrences via length, and pass the de-duplicated rule ids so the
    # tooltip can list the rule types without re-revealing values.
    redaction_summary = RedactionSummary(
        masked_entity_count=len(mask_rules_triggered),
        rules_triggered=sorted(set(mask_rules_triggered)),
    )

    response = AnalysisResponse(
        request_id=request_id,
        oa=oa_doc,
        drafts=drafts,
        related_prior_art=all_hits,
        deadline_summary=deadline,
        cost_meta=cost_meta,
        claim_tree=claim_tree_nodes,
        redaction_summary=redaction_summary,
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


def _degraded_draft(rejection_id: str) -> DraftResponse:
    """Saga fallback (Q1 + Follow-up): a placeholder draft for a rejection
    whose draft / verify step failed.

    Confidence is pinned to 0.0 and citations are empty so the front-end and
    the attorney treat it as "AI could not help here — draft manually". The
    rest of the analysis (other rejections, deadline, claim tree) is unaffected.
    """
    note = (
        "[draft generation failed for this rejection — "
        "manual attorney drafting required]"
    )
    return DraftResponse(
        rejection_id=rejection_id,
        strategy=note,
        draft_text=note,
        grounded_citations=[],
        confidence=0.0,
        requires_attorney_review=True,
    )


def _jurisdiction_for_patent(patent_no: str) -> str:
    """Q17: the answer period + holiday calendar differ per jurisdiction, so
    a US patent must NOT be scored against TW's 60-day rule (and vice versa).

    POC: derive from the patent-number country prefix (US…, TW…, EP…, JP…,
    CN…). Production: read jurisdiction from the case-management record.
    Unknown / missing prefix falls back to TW (this firm's home office) — the
    deadline module additionally warns for any jurisdiction it can't compute.
    """
    if not patent_no:
        return "TW"
    prefix = patent_no.strip().upper()[:2]
    known = {"US", "TW", "EP", "JP", "CN", "KR"}
    return prefix if prefix in known else "TW"


def _security_level_for_case(case_id: str) -> str:
    """Q15: case-level security label drives LLM router.

    POC: simple convention — case ids ending with -CONF use confidential.
    Production: read from case management system.
    """
    if case_id.upper().endswith("-CONF"):
        return "confidential"
    return "public"
