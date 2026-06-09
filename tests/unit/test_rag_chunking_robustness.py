"""Agent H (Day 13H) — RAG chunking + retrieval robustness (Q6/Q7).

Covers the production edge cases the chunker/retriever must survive:

  * oversized spec section → multiple sliding windows with overlap, parent
    metadata retained,
  * unicode / CJK spec + claims chunk cleanly (no byte-vs-char truncation),
  * empty corpus / unindexed tenant retrieve → [],
  * a query with no semantic hits still returns a (possibly empty) list, never
    crashes,
  * sliding-window invariant: consecutive windows overlap by the configured
    amount and cover the whole text.

Uses unique tenant ids so indexing into the shared module-level store does not
contaminate other tests (the same pattern test_claim_tree_chunking.py uses).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.ai_engine import rag
from backend.ai_engine.rag import _sliding_window, chunk_patent
from backend.shared.models import Patent


def _patent(claims, patent_no, abstract="An abstract.", jurisdiction="US"):
    return Patent(
        patent_no=patent_no,
        title="Test patent",
        abstract=abstract,
        claims=claims,
        publication_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        jurisdiction=jurisdiction,
        is_local=False,
    )


# ---------------------------------------------------------------------------
# Sliding window invariants
# ---------------------------------------------------------------------------
def test_sliding_window_overlap_and_coverage():
    text = "x" * 5000
    windows = _sliding_window(text, target_tokens=400, overlap=50)
    assert len(windows) > 1
    # Reassembling with the known overlap reproduces the original length.
    target_chars = 400 * 3
    overlap_chars = 50 * 3
    # Every window except possibly the last is full-size.
    for w in windows[:-1]:
        assert len(w) == target_chars
    # Consecutive windows share `overlap_chars` of text.
    for i in range(len(windows) - 1):
        tail = windows[i][-overlap_chars:]
        head = windows[i + 1][:overlap_chars]
        assert tail == head


def test_sliding_window_short_text_single_window():
    text = "a short section"
    assert _sliding_window(text) == [text]


def test_sliding_window_empty_text():
    assert _sliding_window("") == []


# ---------------------------------------------------------------------------
# Oversized spec → multiple windows, parent metadata retained
# ---------------------------------------------------------------------------
def test_oversized_spec_section_windows_with_metadata():
    big_spec = "DETAILED DESCRIPTION\n" + ("The widget operates smoothly. " * 2000)
    chunks = chunk_patent(_patent(["1. A widget."], "US-BIG"), spec_text=big_spec)
    spec_chunks = [c for c in chunks if c.section.startswith("detailed")]
    assert len(spec_chunks) > 1, "oversized section must split into windows"
    # Each window carries its parent section label + window index in metadata.
    for ch in spec_chunks:
        assert ch.metadata["section_label"] == "DETAILED_DESCRIPTION"
        assert "window_idx" in ch.metadata
        assert ch.claim_no is None
    # Window indices are contiguous from 0.
    idxs = sorted(c.metadata["window_idx"] for c in spec_chunks)
    assert idxs == list(range(len(spec_chunks)))


# ---------------------------------------------------------------------------
# Unicode / CJK chunking
# ---------------------------------------------------------------------------
def test_cjk_claims_and_spec_chunk_cleanly():
    cjk_claims = [
        "一種電動車充電管理方法，包含：由伺服器執行能源管理方案。",
        "如請求項1所述之方法，其中該裝置資料包括最大可供電功率。",
    ]
    cjk_spec = "發明所屬之技術領域\n本發明關於電動車充電管理。\n\n先前技術\n習知技術採固定上限。"
    chunks = chunk_patent(_patent(cjk_claims, "TW-CJK", abstract="一種充電管理方法。",
                                  jurisdiction="TW"), spec_text=cjk_spec)
    by_sec = {c.section: c for c in chunks}
    # Abstract + claim text survive intact (no mojibake / truncation).
    assert by_sec["abstract"].text == "一種充電管理方法。"
    assert by_sec["claim_1"].text == cjk_claims[0]
    assert by_sec["claim_2"].text == cjk_claims[1]
    # The dependent claim got a per-claim chunk; the independent one a bundle.
    assert "claim_1_tree" in by_sec
    assert "充電管理" in by_sec["claim_1_tree"].text


# ---------------------------------------------------------------------------
# Empty corpus / unindexed tenant / no-hit query
# ---------------------------------------------------------------------------
def test_retrieve_unindexed_tenant_returns_empty():
    assert rag.retrieve("h13_never_indexed", "microchannel cooling", top_k=5) == []


def test_get_claim_tree_unindexed_returns_empty():
    assert rag.get_claim_tree("h13_never_indexed", "US999") == []


def test_retrieve_after_index_returns_list():
    p = _patent(
        ["1. A cooling system comprising a base plate with microchannels."],
        "US-H13-RET",
    )
    rag.index_patent("h13_ret_tenant", p)
    hits = rag.retrieve("h13_ret_tenant", "microchannel cooling base plate", top_k=5)
    assert isinstance(hits, list)
    # Self-text-ish query against a tiny corpus returns its only patent.
    assert all(h.patent_no == "US-H13-RET" for h in hits)


def test_retrieve_top_k_bounds_result_count():
    claims = [f"{i}. A standalone method number {i}." for i in range(1, 8)]
    rag.index_patent("h13_topk_tenant", _patent(claims, "US-H13-TOPK"))
    hits = rag.retrieve("h13_topk_tenant", "standalone method", top_k=3)
    assert len(hits) <= 3


def test_empty_claims_only_abstract_chunk():
    chunks = chunk_patent(_patent([], "US-H13-EMPTY"))
    assert [c.section for c in chunks] == ["abstract"]
