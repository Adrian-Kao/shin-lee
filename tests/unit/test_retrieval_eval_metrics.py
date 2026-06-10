"""Agent H (Day 13H) — nDCG@k + grounding-coverage metric tests.

These DEEPEN the retrieval-eval harness beyond recall@k / MRR with two metrics
that actually distinguish ranking QUALITY (the thing Q6 cares about once
embeddings are real):

  * ndcg_at_k — rewards placing relevant hits higher; credits every relevant
    hit in the cutoff with a log-discounted gain.
  * grounding_coverage — fraction of the grounded set that is relevant
    (precision-like; the Q14 grounding-quality signal).

All assertions are hand-computed so the formulas are pinned independent of
embedding quality, exactly like the existing recall/MRR math tests.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from backend.ai_engine import retrieval_eval as re_mod


def _hit(patent_no, chunk_id=None):
    return SimpleNamespace(
        patent_no=patent_no,
        metadata={"chunk_id": chunk_id} if chunk_id else {},
    )


# ---------------------------------------------------------------------------
# nDCG@k
# ---------------------------------------------------------------------------
def test_ndcg_perfect_ranking_is_one():
    # Single relevant id at rank 1 → DCG == IDCG → 1.0.
    results = [_hit("A"), _hit("B"), _hit("C")]
    assert re_mod.ndcg_at_k(results, {"A"}, k=5) == pytest.approx(1.0)


def test_ndcg_relevant_at_rank2_discounted():
    # Relevant at rank 2: DCG = 1/log2(3); IDCG = 1/log2(2) = 1.
    results = [_hit("X"), _hit("A")]
    expected = (1.0 / math.log2(3)) / 1.0
    assert re_mod.ndcg_at_k(results, {"A"}, k=5) == pytest.approx(expected)


def test_ndcg_rewards_higher_placement():
    # Same relevant item, two rankings: rank-1 must score strictly higher.
    better = [_hit("A"), _hit("X"), _hit("Y")]
    worse = [_hit("X"), _hit("Y"), _hit("A")]
    assert re_mod.ndcg_at_k(better, {"A"}, k=5) > re_mod.ndcg_at_k(worse, {"A"}, k=5)


def test_ndcg_two_relevant_ideal():
    # Two relevant ids at ranks 1 and 2 = the ideal ordering → 1.0.
    results = [_hit("A"), _hit("B"), _hit("C")]
    assert re_mod.ndcg_at_k(results, {"A", "B"}, k=5) == pytest.approx(1.0)


def test_ndcg_respects_cutoff():
    # Relevant at rank 3 but k=2 → nothing in cutoff → 0.0.
    results = [_hit("X"), _hit("Y"), _hit("A")]
    assert re_mod.ndcg_at_k(results, {"A"}, k=2) == 0.0


def test_ndcg_no_relevant_is_zero():
    assert re_mod.ndcg_at_k([_hit("X")], {"A"}, k=5) == 0.0


def test_ndcg_empty_relevant_is_zero():
    assert re_mod.ndcg_at_k([_hit("X")], set(), k=5) == 0.0


def test_ndcg_dedups_repeated_relevant_patent():
    # Same relevant patent twice must not double-credit; equals single-hit DCG
    # normalised by IDCG for ONE relevant id.
    results = [_hit("A"), _hit("A")]
    assert re_mod.ndcg_at_k(results, {"A"}, k=5) == pytest.approx(1.0)


def test_ndcg_matches_on_chunk_id():
    results = [_hit("US1", chunk_id="US1#claim_9")]
    assert re_mod.ndcg_at_k(results, {"US1#claim_9"}, k=5) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# grounding_coverage
# ---------------------------------------------------------------------------
def test_coverage_all_relevant():
    results = [_hit("A"), _hit("B")]
    assert re_mod.grounding_coverage(results, {"A", "B"}) == pytest.approx(1.0)


def test_coverage_half_relevant():
    results = [_hit("A"), _hit("X"), _hit("B"), _hit("Y")]
    # 2 of 4 returned hits are relevant → 0.5.
    assert re_mod.grounding_coverage(results, {"A", "B"}) == pytest.approx(0.5)


def test_coverage_none_relevant():
    results = [_hit("X"), _hit("Y")]
    assert re_mod.grounding_coverage(results, {"A"}) == 0.0


def test_coverage_empty_results_is_zero():
    assert re_mod.grounding_coverage([], {"A"}) == 0.0


def test_coverage_empty_relevant_is_zero():
    assert re_mod.grounding_coverage([_hit("A")], set()) == 0.0


def test_coverage_chunk_id_match_counts():
    results = [_hit("US1", chunk_id="US1#claim_9"), _hit("X")]
    assert re_mod.grounding_coverage(results, {"US1#claim_9"}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# evaluate() now surfaces the new aggregates + per-case fields.
# ---------------------------------------------------------------------------
def test_evaluate_includes_ndcg_and_coverage():
    report = re_mod.evaluate(k=5)
    for key in ("ndcg@k", "grounding_coverage@k"):
        assert key in report
        assert 0.0 <= report[key] <= 1.0
    pc = report["per_case"][0]
    for key in ("ndcg@k", "grounding_coverage@k"):
        assert key in pc
        assert 0.0 <= pc[key] <= 1.0


def test_evaluate_ndcg_le_one_per_case():
    # Sanity invariant: nDCG and coverage are bounded probabilities per case.
    report = re_mod.evaluate(k=5)
    for pc in report["per_case"]:
        assert 0.0 <= pc["ndcg@k"] <= 1.0
        assert 0.0 <= pc["grounding_coverage@k"] <= 1.0
