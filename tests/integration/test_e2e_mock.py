"""End-to-end integration test for the gateway → AI engine flow (mock backends).

This test is fully hermetic: the gateway's outbound httpx.AsyncClient calls
to the AI engine are rerouted via httpx.ASGITransport directly into the AI
engine app in the same process. No socket is opened. All LLM, embedding,
vector store, and cache backends are running in their `mock` / `memory`
configurations (configured by `tests/conftest.py`).

What this proves:
    - JWT login works.
    - The gateway's orchestrator runs the full 6-step flow against the AI
      engine without HTTP-level wiring breaks.
    - parse_oa returns >=1 rejection for the sample US OA.
    - draft_response yields >=1 draft.
    - deadline calculator stamps a non-empty statutory_deadline string.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_OA_US = _REPO_ROOT / "data" / "oa_samples" / "sample_oa_us.txt"


@pytest.mark.asyncio
async def test_analyze_oa_end_to_end(gateway_client, alice_token, patched_ai_engine):
    assert _SAMPLE_OA_US.exists(), f"missing sample fixture: {_SAMPLE_OA_US}"
    oa_text = _SAMPLE_OA_US.read_text(encoding="utf-8")

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": oa_text,
            "case_id": "CASE-2025-001",
            "target_patent_no": "US17123456",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "oa" in body, body
    assert "rejections" in body["oa"], body["oa"]
    assert len(body["oa"]["rejections"]) >= 1, body["oa"]["rejections"]

    assert "drafts" in body, body
    assert len(body["drafts"]) >= 1, body["drafts"]

    # Q14 verifier transparency: the orchestrator surfaces the verifier's output
    # on each draft so the front-end can render the hallucination wall (what was
    # stripped + how confident the verifier was), not just an anonymous
    # [CITATION_REMOVED] marker. These fields default-exist on every draft;
    # a successfully-verified (non-degraded) draft also carries a verifier_model.
    for draft in body["drafts"]:
        assert "invalid_citations" in draft, draft
        assert isinstance(draft["invalid_citations"], list), draft
        assert "verifier_confidence" in draft, draft
        assert "verifier_model" in draft, draft
    assert any(d.get("verifier_model") for d in body["drafts"]), body["drafts"]

    assert "deadline_summary" in body, body
    statutory = body["deadline_summary"].get("statutory_deadline")
    assert isinstance(statutory, str) and statutory, body["deadline_summary"]
