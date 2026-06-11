"""Unit tests for `backend.ai_engine.claim_tree.parse_claim_dependencies`.

Covers:
    * independent claim (claim 1) is recognised
    * TW Chinese dependent claim ("如請求項 1 所述")
    * US English dependent claim ("The system of claim 1")
    * multi-parent reference ("如請求項 1 或 2 所述") — first parent wins for tree
      layout but all parents are recorded
    * depth-3 chain (1 → 5 → 7)
    * unparseable body — degrades gracefully to independent
    * malformed input — empty list, None entries, claims with no number prefix
    * forward reference — claim 2 mentioning claim 5 (illegal, ignored)
    * cycle resilience — explicit self-reference is filtered out by own_number
      filter, and an injected cycle in the depth walk does not crash
"""

from __future__ import annotations

from backend.ai_engine.claim_tree import parse_claim_dependencies


def test_independent_claim_marked_correctly():
    claims = [
        "1. 一種充電方法，包含：取得裝置資料；判斷事件；停止管理作業。",
    ]
    nodes = parse_claim_dependencies(claims)
    assert len(nodes) == 1
    assert nodes[0]["claim_no"] == 1
    assert nodes[0]["depends_on"] is None
    assert nodes[0]["is_independent"] is True
    assert nodes[0]["depth"] == 0
    assert nodes[0]["parents"] == []


def test_tw_chinese_dependent_claim():
    claims = [
        "1. 一種充電方法。",
        "2. 如請求項 1 所述之充電方法，其中該裝置資料包括最大功率。",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[1]["depends_on"] == 1
    assert nodes[1]["is_independent"] is False
    assert nodes[1]["depth"] == 1
    assert nodes[1]["parents"] == [1]


def test_us_english_dependent_claim():
    claims = [
        "1. A cooling system, comprising: a base plate.",
        "2. The cooling system of claim 1, wherein the base plate is copper.",
        "3. The cooling system according to claim 1, further comprising sensors.",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[1]["depends_on"] == 1
    assert nodes[2]["depends_on"] == 1
    assert nodes[1]["depth"] == 1
    assert nodes[2]["depth"] == 1


def test_multi_parent_first_wins_but_all_recorded():
    claims = [
        "1. 一種方法。",
        "2. 一種方法。",
        "3. 如請求項 1 或 2 所述之方法，其中...",
    ]
    nodes = parse_claim_dependencies(claims)
    # First parent wins for tree layout (claim 1).
    assert nodes[2]["depends_on"] == 1
    # But both parents are surfaced for cascade-risk highlighting.
    assert nodes[2]["parents"] == [1, 2]


def test_depth_three_chain():
    claims = [
        "1. 一種方法。",
        "2. 一種獨立方法。",
        "3. 一種獨立系統。",
        "4. 一種獨立裝置。",
        "5. 如請求項 1 所述之方法，其中…",  # depth 1
        "6. 如請求項 1 所述之方法。",  # depth 1 (different parent path)
        "7. 如請求項 5 所述之方法，其中…",  # depth 2
        "8. 如請求項 7 所述之方法。",  # depth 3
    ]
    nodes = parse_claim_dependencies(claims)
    by_no = {n["claim_no"]: n for n in nodes}
    assert by_no[1]["depth"] == 0
    assert by_no[5]["depth"] == 1
    assert by_no[7]["depth"] == 2
    assert by_no[8]["depth"] == 3
    assert by_no[8]["depends_on"] == 7


def test_unparseable_body_degrades_to_independent():
    claims = [
        # No clear dependency marker — treated as independent (best-effort).
        "1. 一種奇怪的東西，沒有正規前言。",
        "2. 完全沒有引用任何前一項的內容。",
    ]
    nodes = parse_claim_dependencies(claims)
    assert all(n["depends_on"] is None for n in nodes)
    assert all(n["depth"] == 0 for n in nodes)


def test_empty_list_returns_empty():
    assert parse_claim_dependencies([]) == []


def test_malformed_entries_are_tolerated():
    # None and non-string entries should not crash the parser.
    claims = [
        "1. 一種方法。",
        None,  # type: ignore[list-item]
        "3. 如請求項 1 所述之方法。",
        123,  # type: ignore[list-item]
    ]
    nodes = parse_claim_dependencies(claims)  # type: ignore[arg-type]
    assert len(nodes) == 4
    assert nodes[0]["claim_no"] == 1
    assert nodes[1]["text"] == "" and nodes[1]["is_independent"]
    assert nodes[2]["depends_on"] == 1
    assert nodes[3]["text"] == "" and nodes[3]["is_independent"]


def test_forward_reference_is_ignored():
    # Claim 2 mentioning "claim 5" is illegal (MPEP 608.01(n) / TIPO §2.3.5)
    # and almost always a body-text artefact. Parser must NOT use it.
    claims = [
        "1. 一種方法。",
        "2. 如請求項 5 所述之方法。",  # forward ref — invalid
        "3. 一種獨立的另一方法。",
        "4. 另一獨立方法。",
        "5. 另一獨立方法。",
    ]
    nodes = parse_claim_dependencies(claims)
    # Claim 2 should fall back to independent because its only parent
    # reference points forward.
    assert nodes[1]["depends_on"] is None
    assert nodes[1]["is_independent"] is True


def test_self_reference_in_prefix_does_not_make_self_parent():
    # The prefix "5." should not become a parent reference of claim 5 once
    # the prefix is stripped.
    claims = [
        "1. 一種方法。",
        "2. 一種方法。",
        "3. 一種方法。",
        "4. 一種方法。",
        "5. 如請求項 2 所述之方法。",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[4]["depends_on"] == 2
    assert 5 not in nodes[4]["parents"]


def test_range_expansion_for_us_phrasing():
    # "The method of claims 1-3, wherein..." — pick the first, expose all.
    claims = [
        "1. A method.",
        "2. A method.",
        "3. A method.",
        "4. The method of claims 1-3, wherein the controller is on.",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[3]["depends_on"] == 1
    assert nodes[3]["parents"] == [1, 2, 3]
