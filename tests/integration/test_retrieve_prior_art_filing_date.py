"""Wiring (Direction-1 starter): the case filing_date flows orchestrator →
/v1/retrieve_prior_art → rag.retrieve(max_pub_date=...), so prior-art retrieval
hard-excludes references published on/after the application's filing/priority
date (專利法 §22/§23), while the application's own patent stays exempt.

Function-level behaviour is covered in tests/unit/test_rag_chunking_robustness.py;
this pins the HTTP contract (RetrieveRequest.filing_date → max_pub_date).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.ai_engine import rag
from backend.shared.models import Patent


def _patent(patent_no: str, year: int, jurisdiction: str = "US") -> Patent:
    return Patent(
        patent_no=patent_no,
        title="Cooling",
        abstract="microchannel cooling base plate for power electronics battery pack",
        claims=["A cooling system comprising a base plate with microchannels."],
        publication_date=datetime(year, 1, 1, tzinfo=UTC),
        jurisdiction=jurisdiction,
        is_local=False,
    )


def _rejection() -> dict:
    return {
        "rejection_id": "R1",
        "rejection_type": "103_obviousness",
        "affected_claims": [1],
        "cited_prior_art": ["PA-OLD"],
        "examiner_argument": "microchannel cooling base plate for power electronics",
        "confidence": 0.9,
    }


def test_retrieve_prior_art_endpoint_excludes_post_filing_art(ai_engine_app):
    t = "pa_filing_tenant"
    rag.index_patent(t, _patent("APP-2026", 2026, "TW"))  # the application
    rag.index_patent(t, _patent("PA-OLD", 2017))  # admissible prior art
    rag.index_patent(t, _patent("PA-NEW", 2028))  # inadmissible (post-filing)

    with TestClient(ai_engine_app) as client:
        resp = client.post(
            "/v1/retrieve_prior_art",
            json={
                "tenant_id": t,
                "rejection": _rejection(),
                "target_patent_no": "APP-2026",
                "top_k": 20,
                "filing_date": "2024-01-01",
            },
        )
    assert resp.status_code == 200, resp.text
    nos = {h["patent_no"] for h in resp.json()["hits"]}
    assert "PA-OLD" in nos  # pre-filing prior art admitted
    assert "PA-NEW" not in nos  # post-filing art excluded
    assert "APP-2026" in nos  # the application itself is exempt (prefer_patent_no)


def test_retrieve_prior_art_endpoint_without_filing_date_is_unchanged(ai_engine_app):
    t = "pa_nofilter_tenant"
    rag.index_patent(t, _patent("ANY-2030", 2030, "TW"))
    with TestClient(ai_engine_app) as client:
        resp = client.post(
            "/v1/retrieve_prior_art",
            json={
                "tenant_id": t,
                "rejection": _rejection(),
                "target_patent_no": "ANY-2030",
                "top_k": 5,
            },  # no filing_date → no date filter
        )
    assert resp.status_code == 200, resp.text
    nos = {h["patent_no"] for h in resp.json()["hits"]}
    assert "ANY-2030" in nos
