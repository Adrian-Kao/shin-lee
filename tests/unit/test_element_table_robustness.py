"""Agent H (Day 13H) — element-table robustness + large-doc perf guard.

Extends test_element_table.py with the edge cases a production OA/spec pipeline
must survive:

  * empty / None / whitespace-only / numeral-free input → empty table,
  * duplicate numeral with conflicting descriptions → deterministic aggregation,
  * correlate() with empty tables / no matches → [],
  * correlate() is asymmetric-greedy but stable,
  * LARGE document does not blow up (regression guard for the O(n^2) neighbour
    lookup that made a 185 KB doc take ~87 s — now bounded to a small window).

The perf guard asserts a generous wall-clock ceiling: it is NOT a microbenchmark
(CI boxes vary), it only catches a reintroduction of the quadratic slicing.
"""

from __future__ import annotations

import time

import pytest

from backend.ai_engine.element_table import (
    correlate,
    extract_element_table,
    extract_elements,
)


# ---------------------------------------------------------------------------
# Degenerate inputs → empty table (never crash)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "   \n\t  ", None])
def test_empty_inputs_yield_empty_table(text):
    assert extract_element_table(text) == {}
    assert extract_elements(text) == {}


def test_numeral_free_text_yields_empty():
    assert extract_element_table("A cooling system having fins and a base plate.") == {}


def test_only_structural_numbers_yield_empty():
    # "claim 1", "Fig. 3", "page 5", "35 U.S.C. 103" are all rejected.
    text = "See claim 1 and Fig. 3 on page 5 under 35 U.S.C. 103."
    assert extract_element_table(text) == {}


# ---------------------------------------------------------------------------
# Duplicate numeral aggregation is deterministic
# ---------------------------------------------------------------------------
def test_duplicate_numeral_aggregates_deterministically():
    # numeral 200 appears 3x with 3 distinct phrases, each once → tie on count,
    # broken by LONGEST phrase ("copper heat sink").
    text = "the heat sink 200 ... a copper heat sink 200 ... the radiator 200"
    el = extract_elements(text)
    assert 200 in el
    assert el[200].mention_count == 3
    assert el[200].description == "copper heat sink"
    assert el[200].candidate_phrases == ["copper heat sink", "heat sink", "radiator"]


def test_most_frequent_phrase_wins_over_longest():
    # "heat sink" appears twice, "copper heat sink" once → frequency beats length.
    text = "the heat sink 200 and the heat sink 200 versus a copper heat sink 200"
    el = extract_elements(text)
    assert el[200].description == "heat sink"


def test_aggregation_is_stable_across_runs():
    text = "the substrate 10, a substrate 10, the base substrate 10"
    a = extract_element_table(text)
    b = extract_element_table(text)
    assert a == b  # deterministic


# ---------------------------------------------------------------------------
# correlate() edge cases
# ---------------------------------------------------------------------------
def test_correlate_empty_tables():
    assert correlate({}, {}) == []
    assert correlate({200: "heat sink"}, {}) == []
    assert correlate({}, {50: "heat sink"}) == []


def test_correlate_no_match_above_threshold():
    assert correlate({200: "heat sink"}, {50: "wireless antenna coil"}) == []


def test_correlate_basic_pair_round_trips():
    app = {200: "heat sink", 102: "electrode"}
    cited = {50: "heat sink", 12: "electrode"}
    pairs = correlate(app, cited)
    mapping = {p["app_numeral"]: p["cited_numeral"] for p in pairs}
    assert mapping[200] == 50
    assert mapping[102] == 12
    # Sorted by descending score (contract).
    scores = [p["score"] for p in pairs]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Large-document performance regression guard
# ---------------------------------------------------------------------------
def test_large_document_extraction_is_bounded():
    """A ~190 KB document with thousands of numeral mentions must extract in
    well under a second on any reasonable box. Before the bounded-window fix
    the neighbour lookups were O(n) per match → ~87 s on this input. We assert
    a generous 5 s ceiling: enough headroom for slow CI, tight enough to catch
    a reintroduced quadratic."""
    big = "the substrate 10 and a heat sink 200. " * 5000
    start = time.perf_counter()
    table = extract_element_table(big)
    elapsed = time.perf_counter() - start
    assert table == {10: "substrate", 200: "heat sink"}
    assert elapsed < 5.0, f"extraction took {elapsed:.1f}s — quadratic regression?"


def test_large_cjk_document_is_bounded():
    """Same guard for the CJK extractor path."""
    big = "基板 10 上設有第一電極 102 與第二電極 104。" * 5000
    start = time.perf_counter()
    table = extract_element_table(big, jurisdiction="TW")
    elapsed = time.perf_counter() - start
    assert set(table.keys()) == {10, 102, 104}
    assert elapsed < 5.0, f"CJK extraction took {elapsed:.1f}s — quadratic regression?"
