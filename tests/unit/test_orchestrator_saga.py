"""Saga partial-failure tests for `orchestrate_analysis` (Q1 + Follow-up).

The orchestrator is a saga coordinator: one rejection's draft / verify /
retrieval failing must NOT sink the whole analysis. The failed rejection is
served as a degraded placeholder (confidence 0, empty citations, manual-draft
note) while every other rejection proceeds normally.

We exercise this by monkeypatching the single egress point
(`AIEngineClient.call`) with a deterministic fake that dispatches on path and
can be told to raise for a chosen rejection — no AI Engine, no sockets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.gateway import orchestrator as orch
from backend.gateway.orchestrator import orchestrate_analysis
from backend.shared.models import AnalysisRequest, User, UserRole

_NOW = datetime(2025, 3, 1, tzinfo=UTC)

# Two rejections so we can fail exactly one and prove the other survives.
_REJECTIONS = [
    {
        "rejection_id": "rej-1",
        "rejection_type": "102_novelty",
        "affected_claims": [1],
        "cited_prior_art": ["US111"],
        "examiner_argument": "claim 1 anticipated",
        "confidence": 0.9,
    },
    {
        "rejection_id": "rej-2",
        "rejection_type": "103_obviousness",
        "affected_claims": [2],
        "cited_prior_art": ["US222"],
        "examiner_argument": "claim 2 obvious",
        "confidence": 0.8,
    },
]


def _make_fake_call(
    fail_draft_for: set[str] | None = None,
    fail_retrieve_for: set[str] | None = None,
    fail_verify_for: set[str] | None = None,
):
    """Return an async fake for AIEngineClient.call dispatching on path."""
    fail_draft_for = fail_draft_for or set()
    fail_retrieve_for = fail_retrieve_for or set()
    fail_verify_for = fail_verify_for or set()

    async def _fake_call(self, path: str, payload: dict) -> dict:
        if path == "/v1/parse_oa":
            return {
                "oa": {
                    "oa_id": "oa-1",
                    "case_id": payload["case_id"],
                    "tenant_id": payload["tenant_id"],
                    "received_date": _NOW.isoformat(),
                    "deadline": (_NOW + timedelta(days=60)).isoformat(),
                    "raw_text_hash": "deadbeef",
                    "rejections": _REJECTIONS,
                },
                "model_used": "mock",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        if path == "/v1/retrieve_prior_art":
            rid = payload["rejection"]["rejection_id"]
            if rid in fail_retrieve_for:
                raise RuntimeError(f"retrieve boom for {rid}")
            return {
                "hits": [
                    {
                        "patent_no": "US111",
                        "section": "claim_1",
                        "text": "prior art text",
                        "score": 0.5,
                        "metadata": {},
                    }
                ],
                "model_used": "mock",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }
        if path == "/v1/draft_response":
            rid = payload["rejection"]["rejection_id"]
            if rid in fail_draft_for:
                raise RuntimeError(f"draft boom for {rid}")
            return {
                "draft": {
                    "rejection_id": rid,
                    "strategy": f"strategy for {rid}",
                    "draft_text": f"draft for {rid}",
                    "grounded_citations": ["US111"],
                    "confidence": 0.7,
                    "requires_attorney_review": True,
                },
                "model_used": "mock",
                "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            }
        if path == "/v1/verify_citations":
            rid = payload["draft"]["rejection_id"]
            if rid in fail_verify_for:
                raise RuntimeError(f"verify boom for {rid}")
            return {
                "cleaned_draft_text": payload["draft"]["draft_text"],
                "valid_citations": payload["draft"]["grounded_citations"],
                "verifier_confidence": 0.95,
                "model_used": "mock",
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            }
        if path == "/v1/deadline":
            return {
                "received_date": _NOW.isoformat(),
                "statutory_deadline": (_NOW + timedelta(days=60)).isoformat(),
                "recommended_internal_deadline": (_NOW + timedelta(days=53)).isoformat(),
                "days_remaining": 60,
                "holiday_calendar_version": "2025.1",
                "warnings": [],
            }
        if path == "/v1/claim_tree":
            return {"claim_tree": []}
        raise AssertionError(f"unexpected path {path}")

    return _fake_call


def _user() -> User:
    return User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice",
    )


def _req() -> AnalysisRequest:
    return AnalysisRequest(
        oa_text="Claim 1 rejected under 102. Claim 2 rejected under 103.",
        case_id="CASE-2025-001",
        target_patent_no="US17123456",
    )


def _draft_by_id(resp, rid):
    return next(d for d in resp.drafts if d.rejection_id == rid)


_DEGRADED_NOTE = "manual attorney drafting required"


@pytest.mark.asyncio
async def test_all_succeed_happy_path(monkeypatch):
    monkeypatch.setattr(orch.AIEngineClient, "call", _make_fake_call())
    resp, obs = await orchestrate_analysis(_user(), _req())
    assert len(resp.drafts) == len(_REJECTIONS)
    for d in resp.drafts:
        assert d.confidence > 0.0
        assert _DEGRADED_NOTE not in d.draft_text
        assert d.grounded_citations == ["US111"]


@pytest.mark.asyncio
async def test_one_draft_fails_others_survive(monkeypatch):
    monkeypatch.setattr(orch.AIEngineClient, "call", _make_fake_call(fail_draft_for={"rej-2"}))
    resp, obs = await orchestrate_analysis(_user(), _req())

    # Count invariant preserved (verify.sh expects drafts == rejections).
    assert len(resp.drafts) == len(_REJECTIONS)

    good = _draft_by_id(resp, "rej-1")
    bad = _draft_by_id(resp, "rej-2")

    # The healthy rejection is unaffected.
    assert good.confidence > 0.0
    assert good.grounded_citations == ["US111"]
    assert _DEGRADED_NOTE not in good.draft_text

    # The failed rejection is a degraded placeholder.
    assert bad.confidence == 0.0
    assert bad.grounded_citations == []
    assert _DEGRADED_NOTE in bad.draft_text
    assert bad.requires_attorney_review is True


@pytest.mark.asyncio
async def test_one_verify_fails_degrades_only_that_rejection(monkeypatch):
    monkeypatch.setattr(orch.AIEngineClient, "call", _make_fake_call(fail_verify_for={"rej-1"}))
    resp, _ = await orchestrate_analysis(_user(), _req())
    assert len(resp.drafts) == len(_REJECTIONS)

    bad = _draft_by_id(resp, "rej-1")
    good = _draft_by_id(resp, "rej-2")
    assert bad.confidence == 0.0
    assert bad.grounded_citations == []
    assert _DEGRADED_NOTE in bad.draft_text
    assert good.confidence > 0.0


@pytest.mark.asyncio
async def test_one_retrieval_fails_draft_still_produced(monkeypatch):
    # Retrieval failure => empty grounded set for that rejection, but the
    # draft step still runs (fake returns a draft regardless), so the
    # rejection is NOT degraded — it just has an empty grounded input.
    monkeypatch.setattr(orch.AIEngineClient, "call", _make_fake_call(fail_retrieve_for={"rej-1"}))
    resp, _ = await orchestrate_analysis(_user(), _req())
    assert len(resp.drafts) == len(_REJECTIONS)
    # Both drafts produced; no crash.
    d1 = _draft_by_id(resp, "rej-1")
    d2 = _draft_by_id(resp, "rej-2")
    assert d2.confidence > 0.0
    assert d1.rejection_id == "rej-1"


@pytest.mark.asyncio
async def test_cost_aggregation_skips_failed_calls(monkeypatch):
    # Even with a failed draft (no usage row), cost aggregation must not crash
    # and must still report the tokens from the surviving calls.
    monkeypatch.setattr(orch.AIEngineClient, "call", _make_fake_call(fail_draft_for={"rej-2"}))
    resp, obs = await orchestrate_analysis(_user(), _req())
    assert resp.cost_meta.prompt_tokens > 0
    assert obs["prompt_tokens"] == resp.cost_meta.prompt_tokens
