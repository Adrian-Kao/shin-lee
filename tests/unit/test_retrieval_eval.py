"""Unit tests for the Q6-B retrieval evaluation harness.

Two layers:
  1. MATH — recall_at_k / mrr on hand-constructed fixtures. These assertions
     must hold regardless of embedding quality; they pin the metric formulas.
  2. WIRING — evaluate() / assert_quality() run end-to-end against the demo
     dataset on the mock backend and return the right shapes, and the gate
     actually gates (passes at the mock floor, fails at an impossible floor).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ai_engine import retrieval_eval as re_mod


# ---------------------------------------------------------------------------
# Fixtures: a tiny hit shim mirroring RetrievalHit (.patent_no, .metadata).
# ---------------------------------------------------------------------------
def _hit(patent_no: str, chunk_id: str | None = None):
    return SimpleNamespace(
        patent_no=patent_no,
        metadata={"chunk_id": chunk_id} if chunk_id else {},
    )


# ---------------------------------------------------------------------------
# 1. recall_at_k — pure math
# ---------------------------------------------------------------------------
def test_recall_at_k_full_hit():
    results = [_hit("A"), _hit("B"), _hit("C")]
    assert re_mod.recall_at_k(results, {"A"}, k=5) == 1.0


def test_recall_at_k_miss():
    results = [_hit("A"), _hit("B")]
    assert re_mod.recall_at_k(results, {"Z"}, k=5) == 0.0


def test_recall_at_k_respects_cutoff():
    # Relevant item sits at rank 3 (index 2); k=2 must NOT see it.
    results = [_hit("A"), _hit("B"), _hit("C")]
    assert re_mod.recall_at_k(results, {"C"}, k=2) == 0.0
    assert re_mod.recall_at_k(results, {"C"}, k=3) == 1.0


def test_recall_at_k_partial():
    # Two relevant ids, only one appears in top-k → 0.5.
    results = [_hit("A"), _hit("B"), _hit("C")]
    assert re_mod.recall_at_k(results, {"A", "Z"}, k=5) == 0.5


def test_recall_at_k_matches_chunk_id():
    results = [_hit("US1", chunk_id="US1#claim_9")]
    # Match on chunk_id even though patent_no differs from the relevant entry.
    assert re_mod.recall_at_k(results, {"US1#claim_9"}, k=5) == 1.0


def test_recall_at_k_empty_relevant_is_zero():
    assert re_mod.recall_at_k([_hit("A")], set(), k=5) == 0.0


def test_recall_at_k_dedups_repeated_patent():
    # Same patent_no twice in top-k counts once → recall 1.0, not 2.0.
    results = [_hit("A"), _hit("A")]
    assert re_mod.recall_at_k(results, {"A"}, k=5) == 1.0


# ---------------------------------------------------------------------------
# 2. mrr — pure math
# ---------------------------------------------------------------------------
def test_mrr_rank1():
    results = [_hit("A"), _hit("B")]
    assert re_mod.mrr(results, {"A"}) == 1.0


def test_mrr_rank3():
    results = [_hit("X"), _hit("Y"), _hit("A")]
    assert re_mod.mrr(results, {"A"}) == pytest.approx(1.0 / 3.0)


def test_mrr_no_relevant():
    results = [_hit("X"), _hit("Y")]
    assert re_mod.mrr(results, {"A"}) == 0.0


def test_mrr_takes_first_relevant_only():
    # Two relevant hits at ranks 2 and 3 → reciprocal of the FIRST (rank 2).
    results = [_hit("X"), _hit("A"), _hit("B")]
    assert re_mod.mrr(results, {"A", "B"}) == pytest.approx(0.5)


def test_mrr_matches_chunk_id():
    results = [_hit("US1", chunk_id="US1#claim_9")]
    assert re_mod.mrr(results, {"US1#claim_9"}) == 1.0


# ---------------------------------------------------------------------------
# 3. dataset loading
# ---------------------------------------------------------------------------
def test_load_dataset_returns_labeled_cases():
    cases = re_mod.load_dataset()
    assert len(cases) >= 5
    for c in cases:
        assert c["query"]
        assert c["relevant"]


# ---------------------------------------------------------------------------
# 4. evaluate() end-to-end on the demo dataset (mock backend)
# ---------------------------------------------------------------------------
def test_evaluate_runs_and_has_expected_shape():
    report = re_mod.evaluate(k=5)
    # Top-level keys.
    for key in ("k", "n_cases", "recall@k", "mrr", "embedding_backend", "per_case", "failures"):
        assert key in report
    assert report["k"] == 5
    assert report["n_cases"] == len(report["per_case"])
    assert report["n_cases"] >= 5
    # Aggregates are valid probabilities.
    assert 0.0 <= report["recall@k"] <= 1.0
    assert 0.0 <= report["mrr"] <= 1.0
    # Per-case shape.
    pc = report["per_case"][0]
    for key in (
        "id",
        "query",
        "recall@k",
        "mrr",
        "n_relevant",
        "n_retrieved",
        "top_patent_nos",
        "hit",
    ):
        assert key in pc
    # Failures are a subset of per_case with zero recall.
    for f in report["failures"]:
        assert f["recall@k"] == 0.0


def test_evaluate_mock_backend_label():
    report = re_mod.evaluate(k=5)
    assert report["embedding_backend"] == "mock"


def test_evaluate_accepts_custom_dataset():
    custom = [
        {
            "id": "custom",
            "query": "microchannel cooling electric vehicle battery turbulent flow",
            "tenant_id": "tenant_a",
            "relevant": ["US7654321"],
        }
    ]
    report = re_mod.evaluate(dataset=custom, k=5)
    assert report["n_cases"] == 1
    assert report["per_case"][0]["id"] == "custom"


# ---------------------------------------------------------------------------
# 5. assert_quality() — prove the gate actually gates
# ---------------------------------------------------------------------------
def test_assert_quality_passes_at_mock_floor():
    result = re_mod.assert_quality(min_recall_at_5=re_mod.DEFAULT_MIN_RECALL_AT_5)
    assert result["passed"] is True
    assert result["actual_recall_at_5"] >= re_mod.DEFAULT_MIN_RECALL_AT_5
    assert "report" in result


def test_assert_quality_fails_at_impossible_floor():
    # 1.01 is unreachable (recall is capped at 1.0) → gate MUST fail.
    result = re_mod.assert_quality(min_recall_at_5=1.01)
    assert result["passed"] is False
    assert result["actual_recall_at_5"] <= 1.0


def test_default_floor_below_prod_target():
    # Sanity: the mock floor must be looser than the production target, else
    # the mock suite would be flaky-red. Documents the intended gap.
    assert re_mod.DEFAULT_MIN_RECALL_AT_5 < re_mod.PROD_TARGET_RECALL_AT_5
    assert re_mod.PROD_TARGET_RECALL_AT_5 == 0.70
