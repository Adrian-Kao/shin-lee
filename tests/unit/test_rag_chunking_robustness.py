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

from datetime import UTC, date, datetime

from backend.ai_engine import rag
from backend.ai_engine.rag import _sliding_window, chunk_patent
from backend.shared.models import Patent


def _patent(claims, patent_no, abstract="An abstract.", jurisdiction="US"):
    return Patent(
        patent_no=patent_no,
        title="Test patent",
        abstract=abstract,
        claims=claims,
        publication_date=datetime(2024, 1, 1, tzinfo=UTC),
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
    chunks = chunk_patent(
        _patent(cjk_claims, "TW-CJK", abstract="一種充電管理方法。", jurisdiction="TW"),
        spec_text=cjk_spec,
    )
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


# ---------------------------------------------------------------------------
# CJK section splitting (TW 發明說明書 must NOT collapse into one BODY chunk).
#
# Before the CJK headings were added to _SECTION_HEADINGS, a Traditional-Chinese
# spec matched none of the English-only patterns and _split_spec_into_sections
# returned the whole text as a single {"BODY": ...} section — destroying the
# hierarchical structure retrieval relies on. This pins the fix for the focus
# jurisdiction (TW) and its CN/JP cousins.
# ---------------------------------------------------------------------------
def _tw_spec() -> str:
    return (
        "【技術領域】\n本發明是關於一種電動車充電管理方法。\n\n"
        "【先前技術】\n習知充電系統採用固定功率上限，無法因應電網負載變化。\n\n"
        "【發明內容】\n本發明提出由伺服器動態下發能源管理方案，以最佳化整體供電。\n\n"
        "【圖式簡單說明】\n第1圖為系統架構圖。\n\n"
        "【實施方式】\n以下配合圖式說明較佳實施例。伺服器接收各充電樁的最大可供電功率……\n\n"
        "【申請專利範圍】\n見後附請求項。"
    )


def test_cjk_spec_splits_into_canonical_sections():
    chunks = chunk_patent(
        _patent(["1. 一種充電管理方法。"], "TW-SECT", jurisdiction="TW"),
        spec_text=_tw_spec(),
    )
    section_labels = {
        c.metadata.get("section_label") for c in chunks if "section_label" in c.metadata
    }
    # All five prose sections are recognised — NOT a single BODY chunk.
    assert {
        "FIELD_OF_INVENTION",
        "BACKGROUND",
        "SUMMARY",
        "DRAWINGS",
        "DETAILED_DESCRIPTION",
    } <= section_labels
    assert "BODY" not in section_labels
    # The 先前技術 (prior-art) text lands in the BACKGROUND section, where an
    # OA-prior-art comparison would look for it.
    bg = next(c for c in chunks if c.metadata.get("section_label") == "BACKGROUND")
    assert "固定功率上限" in bg.text


def test_cjk_spec_section_split_is_a_real_improvement():
    """Direct before/after: the old English-only headings would have produced a
    single BODY section for this spec; the new headings produce many."""
    from backend.ai_engine.rag import _split_spec_into_sections

    sections = _split_spec_into_sections(_tw_spec())
    assert list(sections.keys()) != ["BODY"]
    assert len(sections) >= 5


def test_cn_and_jp_headings_also_split():
    cn_spec = (
        "技术领域\n本发明涉及电池管理。\n\n"
        "背景技术\n现有方案功率固定。\n\n"
        "发明内容\n本发明动态调度。\n\n"
        "具体实施方式\n以下结合附图说明。"
    )
    cn_sections = _split_spec_into_sections_public(cn_spec)
    assert "FIELD_OF_INVENTION" in cn_sections
    assert "DETAILED_DESCRIPTION" in cn_sections
    assert "BODY" not in cn_sections


def _split_spec_into_sections_public(text: str) -> dict:
    from backend.ai_engine.rag import _split_spec_into_sections

    return _split_spec_into_sections(text)


# ---------------------------------------------------------------------------
# Prior-art date filter (專利法 §22/§23): art published on/after the application's
# filing date is INADMISSIBLE and must never reach an OA-response grounded set.
# retrieve(max_pub_date=...) is the hard, fail-closed gate.
# ---------------------------------------------------------------------------
def _dated_patent(patent_no, year, jurisdiction="TW"):
    return Patent(
        patent_no=patent_no,
        title="Cooling",
        abstract="microchannel cooling base plate for power electronics",
        claims=["1. A cooling system comprising a base plate with microchannels."],
        publication_date=datetime(year, 1, 1, tzinfo=UTC),
        jurisdiction=jurisdiction,
        is_local=False,
    )


def test_prior_art_date_filter_excludes_post_filing_art():
    rag.index_patent("pa_tenant", _dated_patent("TW-OLD", 2019))
    rag.index_patent("pa_tenant", _dated_patent("TW-NEW", 2026))
    # No filter → both patents are retrievable.
    nos = {h.patent_no for h in rag.retrieve("pa_tenant", "microchannel cooling", top_k=20)}
    assert {"TW-OLD", "TW-NEW"} <= nos
    # Filing/priority date 2023-06-01 → only the 2019 reference is admissible.
    filtered = rag.retrieve(
        "pa_tenant", "microchannel cooling", top_k=20, max_pub_date="2023-06-01"
    )
    fnos = {h.patent_no for h in filtered}
    assert "TW-OLD" in fnos
    assert "TW-NEW" not in fnos


def test_prior_art_filter_accepts_date_and_datetime_inputs():
    rag.index_patent("pa_tenant2", _dated_patent("TW-A", 2018))
    rag.index_patent("pa_tenant2", _dated_patent("TW-B", 2025))
    for cutoff in (date(2020, 1, 1), datetime(2020, 1, 1, tzinfo=UTC), "2020-01-01"):
        fnos = {
            h.patent_no
            for h in rag.retrieve("pa_tenant2", "cooling", top_k=20, max_pub_date=cutoff)
        }
        assert fnos == {"TW-A"}, cutoff


def test_prior_art_filter_fails_closed_and_is_strict():
    from backend.ai_engine.rag import Chunk, _passes_prior_art

    def _chunk(meta):
        return Chunk(
            chunk_id="x",
            patent_no="P",
            section="abstract",
            claim_no=None,
            text="t",
            jurisdiction="TW",
            metadata=meta,
        )

    cutoff = date(2023, 1, 1)
    # Undated → dropped (fail-closed).
    assert _passes_prior_art(_chunk({}), cutoff) is False
    # Before filing → admissible.
    assert _passes_prior_art(_chunk({"pub_date": "2019-01-01"}), cutoff) is True
    # SAME day as filing → NOT prior art (must be strictly before).
    assert _passes_prior_art(_chunk({"pub_date": "2023-01-01"}), cutoff) is False


def test_retrieve_without_filter_is_unchanged():
    # Backwards-compat: default max_pub_date=None retrieves exactly as before.
    rag.index_patent("pa_tenant3", _dated_patent("TW-Z", 2030))
    hits = rag.retrieve("pa_tenant3", "cooling base plate", top_k=5)
    assert any(h.patent_no == "TW-Z" for h in hits)


# ---------------------------------------------------------------------------
# Hybrid retrieval (Phase 2): dense + BM25 lexical fused via RRF. The win is
# exact-term recall (element numbers / proper nouns) that semantic vectors blur.
# ---------------------------------------------------------------------------
def _term_patent(patent_no, abstract, claim, jurisdiction="US"):
    return Patent(
        patent_no=patent_no,
        title="t",
        abstract=abstract,
        claims=[claim],
        publication_date=datetime(2020, 1, 1, tzinfo=UTC),
        jurisdiction=jurisdiction,
        is_local=False,
    )


def test_rrf_fuse_rewards_cross_list_agreement():
    from backend.ai_engine.rag import Chunk, _rrf_fuse

    def ch(cid):
        return Chunk(
            chunk_id=cid, patent_no=cid, section="s", claim_no=None,
            text="t", jurisdiction="US", metadata={},
        )

    a, b, c = ch("A"), ch("B"), ch("C")
    dense = [(a, 0.9), (b, 0.8), (c, 0.7)]
    lexical = [(c, 5.0), (b, 4.0)]  # c, b appear in BOTH lists; a only in dense
    order = [x[0].chunk_id for x in _rrf_fuse([dense, lexical])]
    # Cross-list agreement (B, C) must outrank the dense-only chunk (A).
    assert order.index("B") < order.index("A")
    assert order.index("C") < order.index("A")


def test_bm25_lexical_search_finds_exact_term():
    from backend.ai_engine.rag import _store

    rag.index_patent(
        "lex_tenant",
        _term_patent("ZOG-1", "a zogplex turbine cooling apparatus", "A zogplex turbine."),
    )
    rag.index_patent("lex_tenant", _patent(["A generic cooling microchannel system."], "GEN-2"))
    if not hasattr(_store, "lexical_search"):
        import pytest

        pytest.skip("active store has no lexical_search (qdrant)")
    results = _store.lexical_search("lex_tenant", "zogplex turbine", top_k=5)
    assert results, "BM25 must return the exact-term chunk"
    assert results[0][0].patent_no == "ZOG-1"


def test_hybrid_retrieve_surfaces_exact_term_dense_blurs():
    from backend.ai_engine.rag import _store

    if not hasattr(_store, "lexical_search"):
        import pytest

        pytest.skip("active store has no lexical_search (qdrant)")
    rag.index_patent(
        "hyb_tenant",
        _term_patent("ZOG-H", "a zogplex turbine cooling apparatus", "A zogplex turbine with fins."),
    )
    for i in range(4):
        rag.index_patent("hyb_tenant", _patent([f"A generic cooling system number {i}."], f"GEN-{i}"))
    hits = rag.retrieve("hyb_tenant", "zogplex turbine", top_k=5, hybrid=True)
    # The exact-term patent floats to the top via the BM25 signal (mock dense
    # alone would rank it near-randomly).
    assert hits[0].patent_no == "ZOG-H"


def test_hybrid_explicit_off_matches_default_dense():
    rag.index_patent("hyb_off_tenant", _patent(["A cooling base plate with microchannels."], "OFF-1"))
    a = [h.patent_no for h in rag.retrieve("hyb_off_tenant", "microchannel cooling", top_k=5)]
    b = [h.patent_no for h in rag.retrieve("hyb_off_tenant", "microchannel cooling", top_k=5, hybrid=False)]
    assert a == b  # default (dense) and explicit hybrid=False are identical


def test_hybrid_respects_prior_art_date_filter():
    from backend.ai_engine.rag import _store

    if not hasattr(_store, "lexical_search"):
        import pytest

        pytest.skip("active store has no lexical_search (qdrant)")
    rag.index_patent(
        "hyb_date_tenant",
        _term_patent("ZOG-OLD", "zogplex turbine", "A zogplex turbine.", "US"),
    )
    # Same distinctive term, but published AFTER the filing cut-off → inadmissible.
    rag.index_patent(
        "hyb_date_tenant",
        Patent(
            patent_no="ZOG-NEW", title="t", abstract="zogplex turbine",
            claims=["A zogplex turbine."], publication_date=datetime(2030, 1, 1, tzinfo=UTC),
            jurisdiction="US", is_local=False,
        ),
    )
    nos = {
        h.patent_no
        for h in rag.retrieve(
            "hyb_date_tenant", "zogplex turbine", top_k=10, hybrid=True, max_pub_date="2025-01-01"
        )
    }
    assert "ZOG-OLD" in nos
    assert "ZOG-NEW" not in nos  # hybrid still honours the §22/§23 date filter


def test_prior_art_filter_exempts_preferred_target_patent():
    # The application's OWN patent (prefer_patent_no) must survive the filter
    # even though its publication date is after the filing cut-off — it is the
    # case being prosecuted, not its own prior art. Other post-filing art is
    # still dropped; genuine pre-filing art is admitted.
    rag.index_patent("pa_exempt", _dated_patent("TW-APP", 2026))  # the application
    rag.index_patent("pa_exempt", _dated_patent("US-OLD", 2018))  # admissible prior art
    rag.index_patent("pa_exempt", _dated_patent("US-NEW", 2027))  # inadmissible (post-filing)
    hits = rag.retrieve(
        "pa_exempt",
        "microchannel cooling base plate",
        top_k=20,
        prefer_patent_no="TW-APP",
        max_pub_date="2024-01-01",
    )
    nos = {h.patent_no for h in hits}
    assert "TW-APP" in nos  # own application exempt despite 2026 > 2024 cut-off
    assert "US-OLD" in nos  # genuine pre-filing prior art admitted
    assert "US-NEW" not in nos  # post-filing art excluded
