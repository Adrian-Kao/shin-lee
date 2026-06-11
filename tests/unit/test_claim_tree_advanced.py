"""Agent H (Day 13H) — table-driven hardening for the claim-tree parser.

`test_claim_tree_parser.py` already covers the core cases (TW 請求項, US "of
claim N", multi-parent, depth chains, forward refs, malformed input). This
suite DEEPENS coverage for the production-grade claim phrasings that real EP /
PCT / CN / multiple-dependent filings use and that the original parser silently
missed (returning the dependent claim as independent — which would orphan it in
the tree and break cascade-risk highlighting):

  * EP/UK   "as claimed in claim N"
  * EP/PCT  "of any one of claims 1 to 5"  (multiple-dependent, spelled range)
  * EP/PCT  "of any of claims 1 through 3" (alt range word)
  * CN      "根据权利要求1所述"  (simplified — 权利要求 noun)
  * CN/TW   "根據權利要求 1 所述" (traditional 權利要求 noun)
  * TW      "如請求項 1 至 3 所述"  (Chinese range chars 至/到)
  * means-plus-function INDEPENDENT claims must NOT be misread as dependent.

Every case is a (claims, expected_depends_on, expected_parents) row so the
intent is legible and adding a new phrasing is one line.
"""

from __future__ import annotations

import pytest

from backend.ai_engine.claim_tree import parse_claim_dependencies

# Each row: (label, claims, target_index, expected_depends_on, expected_parents)
_DEP_CASES = [
    (
        "ep-as-claimed-in",
        [
            "1. A method, comprising steps.",
            "2. A method as claimed in claim 1, wherein the step repeats.",
        ],
        1,
        1,
        [1],
    ),
    (
        "ep-any-one-of-range-to",
        [
            "1. A m.",
            "2. A m.",
            "3. A m.",
            "4. A m.",
            "5. A m.",
            "6. The system of any one of claims 1 to 5, wherein the controller is on.",
        ],
        5,
        1,
        [1, 2, 3, 4, 5],
    ),
    (
        "ep-any-of-range-through",
        [
            "1. A m.",
            "2. A m.",
            "3. A m.",
            "4. The method of any of claims 1 through 3, further comprising sensors.",
        ],
        3,
        1,
        [1, 2, 3],
    ),
    (
        "cn-simplified-genju-quanli",
        ["1. 一种方法。", "2. 根据权利要求1所述的方法，其中该步骤重复。"],
        1,
        1,
        [1],
    ),
    (
        "tw-traditional-quanli",
        ["1. 一種方法。", "2. 根據權利要求 1 所述之方法，其中該步驟重複。"],
        1,
        1,
        [1],
    ),
    (
        "tw-chinese-range-zhi",
        ["1. 一種方法。", "2. 一種方法。", "3. 一種方法。", "4. 如請求項 1 至 3 所述之方法，其中…"],
        3,
        1,
        [1, 2, 3],
    ),
    (
        "tw-chinese-range-dao",
        ["1. 一種方法。", "2. 一種方法。", "3. 如請求項 1 到 2 所述之方法。"],
        2,
        1,
        [1, 2],
    ),
]


@pytest.mark.parametrize(
    "claims,idx,exp_depends_on,exp_parents",
    [pytest.param(*row[1:], id=row[0]) for row in _DEP_CASES],
)
def test_dependency_phrasing(claims, idx, exp_depends_on, exp_parents):
    nodes = parse_claim_dependencies(claims)
    node = nodes[idx]
    assert node["depends_on"] == exp_depends_on, (
        f"depends_on {node['depends_on']} != {exp_depends_on}"
    )
    assert node["parents"] == exp_parents, f"parents {node['parents']} != {exp_parents}"
    assert node["is_independent"] is False


# ---------------------------------------------------------------------------
# means-plus-function INDEPENDENT claims — the head noun "means for X" must NOT
# trip any dependency pattern. 35 USC 112(f) claims are independent unless they
# carry an explicit "of claim N" reference.
# ---------------------------------------------------------------------------
_MPF_INDEPENDENT = [
    "An apparatus comprising: means for cooling a substrate; and "
    "means for sensing a temperature of the substrate.",
    "一種裝置，包含：用以冷卻基板之手段；以及用以感測溫度之手段。",
    "A system, comprising: a processor configured to execute instructions; "
    "and a memory storing said instructions.",
]


@pytest.mark.parametrize("claim", _MPF_INDEPENDENT)
def test_means_plus_function_stays_independent(claim):
    nodes = parse_claim_dependencies([claim])
    assert nodes[0]["is_independent"] is True
    assert nodes[0]["depends_on"] is None
    assert nodes[0]["parents"] == []
    assert nodes[0]["depth"] == 0


def test_mpf_dependent_still_parsed():
    """A means-plus-function DEPENDENT claim (with an explicit reference) must
    still be recognised as dependent — the MPF body must not mask the ref."""
    claims = [
        "1. An apparatus comprising means for cooling.",
        "2. The apparatus of claim 1, wherein the means for cooling comprises "
        "a microchannel array.",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[1]["depends_on"] == 1
    assert nodes[1]["is_independent"] is False


# ---------------------------------------------------------------------------
# Mixed independent / multiple-dependent tree shape — end to end depth check.
# ---------------------------------------------------------------------------
def test_multiple_dependent_depth_takes_first_parent():
    """A multiple-dependent claim's depth follows its FIRST parent (claim 1
    here), since depends_on is the first valid parent."""
    claims = [
        "1. A base method.",
        "2. The method of claim 1, wherein x.",  # depth 1
        "3. The method of any one of claims 1 to 2, y.",  # first parent = 1 -> depth 1
    ]
    nodes = parse_claim_dependencies(claims)
    by_no = {n["claim_no"]: n for n in nodes}
    assert by_no[3]["depends_on"] == 1
    assert by_no[3]["parents"] == [1, 2]
    assert by_no[3]["depth"] == 1


def test_forward_reference_in_range_is_filtered():
    """A multiple-dependent range that includes forward refs keeps only the
    valid (earlier) parents — claims can only depend on earlier claims."""
    claims = [
        "1. A m.",
        "2. A m.",
        # Claim 3 referencing "claims 1 to 5" — 4 and 5 are forward (illegal),
        # only 1 and 2 are valid antecedents.
        "3. The method of any one of claims 1 to 5, wherein z.",
        "4. A m.",
        "5. A m.",
    ]
    nodes = parse_claim_dependencies(claims)
    assert nodes[2]["depends_on"] == 1
    assert nodes[2]["parents"] == [1, 2]  # 3,4,5 filtered (3=self, 4/5=forward)
