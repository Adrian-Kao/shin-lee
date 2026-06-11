"""Integration test for the claim-tree round-trip.

Walks the new `/v1/claim_tree` endpoint on the AI engine and verifies the
gateway orchestrator surfaces `claim_tree` on `AnalysisResponse` (the
field defaults to [] so absence isn't a failure — what matters is that
the field exists on the wire shape).

We seed the target patent's claim chunks directly into the in-process AI
engine's vector store before issuing the analyze request — that's the
cheapest way to exercise the lookup without dragging in the seed script's
HTTP round-trip.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_OA_US = _REPO_ROOT / "data" / "oa_samples" / "sample_oa_us.txt"


@pytest.mark.asyncio
async def test_claim_tree_field_present_on_response(gateway_client, alice_token, patched_ai_engine):
    """Even when the target patent is not indexed, the response must carry
    `claim_tree` (empty list). This is the backwards-compat contract — the
    SPA always reads `result.claim_tree` and crashes if the field is missing.
    """
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
    assert "claim_tree" in body, body
    assert isinstance(body["claim_tree"], list), body["claim_tree"]


@pytest.mark.asyncio
async def test_claim_tree_populated_when_patent_indexed(
    gateway_client, alice_token, patched_ai_engine
):
    """When the target patent IS indexed, the response carries the parsed
    tree. We index a minimal patent directly via the AI engine's rag
    module (bypassing HTTP) so the test stays hermetic.
    """
    from backend.ai_engine import rag
    from backend.shared.models import Patent

    p = Patent(
        patent_no="US17123456",
        title="Test cooling patent for claim-tree round-trip",
        abstract="Abstract.",
        claims=[
            "1. A cooling system, comprising: a base plate having microchannels.",
            "2. The cooling system of claim 1, wherein said microchannels are copper.",
            "3. The cooling system of claim 2, further comprising temperature sensors.",
        ],
        publication_date=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
        jurisdiction="US",
        is_local=False,
    )
    rag.index_patent("tenant_a", p)

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
    tree = body["claim_tree"]
    assert len(tree) == 3, tree
    assert tree[0]["claim_no"] == 1 and tree[0]["is_independent"] is True
    assert tree[1]["claim_no"] == 2 and tree[1]["depends_on"] == 1
    assert tree[2]["claim_no"] == 3 and tree[2]["depends_on"] == 2
    assert tree[2]["depth"] == 2
