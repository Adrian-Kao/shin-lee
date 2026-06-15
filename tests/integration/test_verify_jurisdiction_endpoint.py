"""Exp4 wiring: the case jurisdiction flows orchestrator → /v1/verify_citations
→ oa_analyzer, so a TW 申復書 that cites US law has that citation stripped at the
hard wall. Function-level behaviour is covered in
tests/unit/test_invariant_citation_grounding.py; this pins the HTTP contract
(VerifyRequest.jurisdiction → verify_citations(jurisdiction=...)).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.shared.models import DraftResponse, RetrievalHit


def _draft() -> DraftResponse:
    return DraftResponse(
        rejection_id="R1",
        strategy="distinguish",
        draft_text=(
            "依 [GROUNDED_REF_1]，本案請求項與引證有別；依 35 U.S.C. § 103 之顯而易見性標準，"
            "核駁認定有誤，且依 專利法第22條第2項 亦不成立。"
        ),
        grounded_citations=[],
        confidence=0.9,
    )


def _payload(jurisdiction):
    hit = RetrievalHit(patent_no="US7654321", section="claim_1", text="x", score=0.9)
    body = {
        "draft": _draft().model_dump(mode="json"),
        "grounded_set": [hit.model_dump(mode="json")],
    }
    if jurisdiction is not None:
        body["jurisdiction"] = jurisdiction
    return body


def test_verify_endpoint_strips_us_law_for_tw_case(ai_engine_app):
    with TestClient(ai_engine_app) as client:
        resp = client.post("/v1/verify_citations", json=_payload("TW"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any("103" in c for c in body["cross_jurisdiction_citations"])
    assert "U.S.C" not in body["cleaned_draft_text"]
    # The TW statute and grounded slot survive.
    assert "專利法第22條第2項" in body["cleaned_draft_text"]
    assert "[GROUNDED_REF_1]" in body["cleaned_draft_text"]


def test_verify_endpoint_keeps_us_law_without_jurisdiction(ai_engine_app):
    """Backwards-compat: omitting jurisdiction preserves the historical
    behaviour (a well-formed US statute is kept)."""
    with TestClient(ai_engine_app) as client:
        resp = client.post("/v1/verify_citations", json=_payload(None))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cross_jurisdiction_citations"] == []
    assert "U.S.C" in body["cleaned_draft_text"]
