"""Unit tests for `backend.ai_engine.element_table` (Q8 OCR-baseline).

Covers:
    * English noun-phrase + numeral extraction, incl. multi-word phrases and
      article ("a/an/the/said") stripping.
    * Chinese/TW extraction incl. a fullwidth-digit case (proves NFKC).
    * False-positive rejection: claim numbers, statute (§/U.S.C.) citations,
      years, paragraph/figure/page refs, Chinese quantities/addresses/dates.
    * `correlate()` proposing the examiner-style "102 <-> 200" mapping and
      returning nothing for unrelated tables.
    * Running over the real data/oa_samples/sample_oa_us.txt without crashing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ai_engine.element_table import (
    correlate,
    extract_element_table,
    extract_elements,
)

# ---------------------------------------------------------------------------
# English extraction
# ---------------------------------------------------------------------------


def test_en_single_word_element():
    table = extract_element_table("The device includes a heat sink 200 below.")
    assert table[200] == "heat sink"


def test_en_strips_leading_article():
    # "the substrate 10" -> article "the" dropped, "substrate" kept.
    table = extract_element_table("Mounted on the substrate 10 firmly.")
    assert table[10] == "substrate"


def test_en_multi_word_description():
    table = extract_element_table("A first electrode 102 contacts the layer.")
    assert table[102] == "first electrode"


def test_en_keeps_nearest_content_words():
    # Long lead-in: only the last up-to-3 content words are the element name.
    txt = "the elongated non-uniform cross section 305 is shown"
    table = extract_element_table(txt)
    assert 305 in table
    assert "cross section" in table[305]
    assert "the" not in table[305].lower().split()


def test_en_said_is_stripped():
    table = extract_element_table("wherein said control module 42 receives data")
    assert table[42] == "control module"


# ---------------------------------------------------------------------------
# Chinese / TW extraction (incl. NFKC fullwidth digits)
# ---------------------------------------------------------------------------


def test_zh_basic_element():
    table = extract_element_table("如圖所示，基板 10 之上設有結構。", jurisdiction="TW")
    assert table[10] == "基板"


def test_zh_multi_char_element():
    table = extract_element_table("第一電極 102 與第二電極 104 相對。", jurisdiction="TW")
    assert table[102] == "第一電極"
    assert table[104] == "第二電極"


def test_zh_fullwidth_digits_nfkc():
    # Fullwidth digits U+FF10..U+FF19 must be NFKC-normalised to ASCII so the
    # numeral parses as int 200.
    fullwidth = "散熱片 ２００ 設置於底部。"  # "散熱片 ２００"
    table = extract_element_table(fullwidth, jurisdiction="TW")
    assert 200 in table
    assert table[200] == "散熱片"


# ---------------------------------------------------------------------------
# False-positive rejection
# ---------------------------------------------------------------------------


def test_reject_claim_number():
    table = extract_element_table("Claims 1-3 are rejected. See claim 5 also.")
    assert 1 not in table
    assert 3 not in table
    assert 5 not in table


def test_reject_statute_citation():
    table = extract_element_table("rejected under 35 U.S.C. 103 as obvious over the references")
    assert 35 not in table
    assert 103 not in table


def test_reject_year():
    table = extract_element_table("filed in 1999 and again in 2020 (2018).")
    assert 1999 not in table
    assert 2020 not in table
    assert 2018 not in table


def test_reject_paragraph_and_page_refs():
    table = extract_element_table("See paragraph 23 and page 5 and Fig 3.")
    assert 23 not in table
    assert 5 not in table
    assert 3 not in table


def test_reject_zh_quantities_and_dates():
    txt = "發文日期：中華民國 114 年 5 月 29 日；規費新台幣 1 千元；共 10 項。"
    table = extract_element_table(txt, jurisdiction="TW")
    for bad in (114, 5, 29, 1, 10):
        assert bad not in table, f"{bad} should be rejected ({table.get(bad)!r})"


def test_reject_zh_address():
    table = extract_element_table("地址：臺北市辛亥路 2 段 185 號 3 樓。", jurisdiction="TW")
    for bad in (2, 185, 3):
        assert bad not in table


# ---------------------------------------------------------------------------
# Aggregation / tie-break
# ---------------------------------------------------------------------------


def test_most_frequent_phrase_wins():
    # "heat sink" appears twice, "sink" once -> most-frequent wins.
    txt = "the heat sink 200 cools; the heat sink 200 again; a sink 200 here."
    elements = extract_elements(txt)
    assert elements[200].description == "heat sink"
    assert elements[200].mention_count == 3


# ---------------------------------------------------------------------------
# correlate()
# ---------------------------------------------------------------------------


def test_correlate_matches_obvious_pair():
    app = {102: "heat sink", 104: "copper conductor"}
    cited = {200: "heat sink assembly", 999: "unrelated widget"}
    pairs = correlate(app, cited)
    # 102 (heat sink) should map to 200 (heat sink assembly).
    assert any(p["app_numeral"] == 102 and p["cited_numeral"] == 200 for p in pairs)
    # The unrelated widget 999 must not be matched to anything.
    assert all(p["cited_numeral"] != 999 for p in pairs)


def test_correlate_returns_nothing_for_unrelated():
    app = {10: "optical lens"}
    cited = {20: "hydraulic pump"}
    assert correlate(app, cited) == []


def test_correlate_accepts_element_tables():
    # Passing the rich {numeral: Element} table (from extract_elements) works.
    app = extract_elements("a heat sink 200 cools the chip")
    cited = extract_elements("the heat sink 5 dissipates heat")
    pairs = correlate(app, cited)
    assert pairs and pairs[0]["app_numeral"] == 200 and pairs[0]["cited_numeral"] == 5


# ---------------------------------------------------------------------------
# Real sample smoke test
# ---------------------------------------------------------------------------


def _sample_path(name: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "oa_samples" / name


def test_real_us_sample_well_formed():
    p = _sample_path("sample_oa_us.txt")
    text = p.read_text(encoding="utf-8")
    table = extract_element_table(text, "US")
    # Must not crash and must be a well-formed dict[int, str].  The sample is
    # pure OA argument prose with no figure/element descriptions, so the
    # correct result is that no statute/claim number leaks in.
    assert isinstance(table, dict)
    for k, v in table.items():
        assert isinstance(k, int) and isinstance(v, str)
    # The statute / claim numbers in that file must NOT be mistaken for elements.
    for bad in (35, 102, 103):
        assert bad not in table


def test_real_tw_sample_well_formed():
    p = _sample_path("sample_oa_tw.txt")
    if not p.exists():
        pytest.skip("TW sample not present")
    text = p.read_text(encoding="utf-8")
    table = extract_element_table(text, "TW")
    assert isinstance(table, dict)
    for k, v in table.items():
        assert isinstance(k, int) and isinstance(v, str)
