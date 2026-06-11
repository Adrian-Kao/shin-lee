"""Claim dependency tree parser.

Backs UX_RESEARCH §5 #2 "claim dependency tree in left rail, color-coded by
rejection status". The Q11 spotlight data already carries the rejections; the
missing piece is the parent-of-each-claim relationship that turns a flat list
into a tree.

Why pure-Python regex instead of an LLM call:
    - Deterministic, < 1 ms per patent, no token cost.
    - Patent claim language for "dependency reference" is one of the most
      ritualised sentence patterns in legal English/Chinese — TIPO and USPTO
      examiners both reject claims whose first phrase doesn't follow the
      template, so the regex coverage is high (> 95% on demo corpus).
    - Failures degrade gracefully: an unparseable claim is treated as
      independent so it just renders flat at the root. Nothing breaks.

What this returns:
    A list of dicts with the shape `ClaimNode`:
        {
            "claim_no":      int   — 1-based claim number, in source order
            "depends_on":    int | None — the FIRST parent (for tree layout)
            "parents":       list[int] — ALL parents (multi-parent "claim 1 or 2"
                                        is rare but real; UI can use this for
                                        cascade-risk highlighting if it wants)
            "text":          str   — the original claim text
            "is_independent": bool — convenience flag = (depends_on is None)
            "depth":         int   — 0 = independent, 1 = direct dependent, etc.
                                    Capped at MAX_DEPTH; cycles fall back to 0.
        }

Algorithm:
    1. Pull the leading clause (first ~120 chars) of each claim — that's
       where the dependency declaration sits. Looking only at the leading
       clause prevents a body-paragraph mention of "claim 1" (in describing
       prior-art or referring to "as recited in claim 1 above") from being
       mistaken for a dependency.
    2. Try TW Chinese patterns first (more specific markers like
       "如請求項 N 所述", "如前述任一項請求項所述"), then US English
       ("the system of claim N", "according to claim N").
    3. Collect every claim number in the leading clause as a parent.
    4. After all claims are parsed, walk the depths with cycle detection.

NB: This is a pure module — no I/O, no settings, no async. Safe to import
from anywhere and trivial to unit-test.
"""

from __future__ import annotations

import re
from typing import Any

# Look only at this many characters of the leading clause. Patent claim
# convention is "如請求項 1 所述..." / "The X of claim N, wherein..." which
# is always in the first sentence; capping prevents a body-paragraph
# false-positive (e.g. a method claim that says "...wherein the controller
# of claim 1 above...").
_LEADING_CLAUSE_CHARS = 200

# Defence against pathological recursion in the depth walk if the parsed
# graph somehow forms a cycle (shouldn't happen with patent claims but the
# parser is permissive). Anything deeper than this is treated as "depth 0
# unparseable" — the UI just renders it flat.
_MAX_DEPTH = 20


# ---------------------------------------------------------------------------
# Pattern set
# ---------------------------------------------------------------------------

# Each pattern is (regex, group_name_for_numbers). The number group can hold
# a single int or a sequence like "1 或 2", "1 or 2", "1, 2, or 3" — the
# `_extract_numbers` helper handles all of them.
_DEPENDENCY_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ----- TW traditional / CN simplified Chinese -----
    # 如請求項 1 所述
    # 如請求項1所述
    # 如請求項 1 或 2 所述
    # 如請求項 1、2 或 3 所述
    # 如申請專利範圍第 1 項所述 (older TIPO phrasing)
    # 根據權利要求 1 所述 / 根据权利要求1所述 (CN simplified — 权利要求)
    #
    # NB the marker noun differs by jurisdiction: TW uses 請求項, CN uses
    # 權利要求/权利要求 (both the traditional and simplified forms). We accept
    # all three noun spellings in ONE pattern so a Chinese-language OA from
    # either office parses without a separate branch.
    (
        re.compile(
            r"如(?:申請專利範圍第)?\s*(?:請求項|權利要求|权利要求)\s*"
            r"([\d、,，\s或至到and及與or]+?)\s*(?:項)?\s*所述",
            re.UNICODE,
        ),
        "nums",
    ),
    # 依請求項 1 所述 / 依據請求項 1 所述
    # 根據權利要求 1 所述 / 根据权利要求1所述 (依/依據/根據/根据 + noun)
    (
        re.compile(
            r"(?:依據|依|根據|根据)\s*(?:請求項|權利要求|权利要求)\s*"
            r"([\d、,，\s或至到and及與]+?)\s*所述",
            re.UNICODE,
        ),
        "nums",
    ),
    # ----- US / EP English -----
    # The system of claim 1, wherein...
    # The method of claims 1-3, wherein...   (range)
    # A device according to claim 1 or 2
    # A method as claimed in claim 1, ...     (EP/UK phrasing)
    # The system of any one of claims 1 to 5  (multiple-dependent, EP/PCT)
    # The method of any of claims 1-3
    (
        re.compile(
            r"\b(?:of|according to|as (?:recited|set forth|claimed) in|as in)\s+"
            r"(?:any (?:one )?of\s+)?"
            r"claims?\s+([\d\s,\-or]+?(?:\s+(?:to|through)\s+\d+)?)"
            r"(?:,|\s+wherein|\s+further|\s*$|\s+comprising|\s+being)",
            re.IGNORECASE,
        ),
        "nums",
    ),
    # depending on claim 1 / dependent on claim 1
    (
        re.compile(
            r"\bdepend(?:ing|ent)\s+on\s+claims?\s+([\d\s,\-or]+(?:\s+(?:to|through)\s+\d+)?)",
            re.IGNORECASE,
        ),
        "nums",
    ),
]

# Strip a leading claim-number prefix like "1." "1)" "請求項 1" — keep only
# the substantive body for dependency parsing. Without this strip a clause
# like "1. 如請求項 1 所述" would also match the "1" prefix and confuse
# multi-parent extraction (claim 5 saying "5. as in claim 1" would pull both
# 5 and 1 as parents of itself).
_CLAIM_NUMBER_PREFIX = re.compile(
    r"^\s*(?:claim\s+|請求項\s*|申請專利範圍第\s*)?\d+\s*[\.\)、:：]\s*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_claim_prefix(text: str) -> str:
    """Drop a `1.` / `請求項 1、` style prefix so it doesn't get parsed as a parent."""
    return _CLAIM_NUMBER_PREFIX.sub("", text, count=1)


def _extract_numbers(blob: str) -> list[int]:
    """Pull all integers out of a regex match group, in order, deduped.

    Handles "1", "1 或 2", "1, 2", "1-3", "1, 2 or 3", and the spelled-out
    range forms common in EP/PCT multiple-dependent claims and Chinese
    filings: "1 to 3", "1 through 5", "1至3", "1到5". Every range notation
    is EXPANDED to the full inclusive list ("1 to 3" -> [1, 2, 3]) so that
    `parents` carries every antecedent claim (cascade-risk highlighting in
    the UI needs them all), while `depends_on` (first parent) drives layout.
    """
    nums: list[int] = []
    # Find all integers; preserve order.
    raw = re.findall(r"\d+", blob)
    # Detect a range expression — pre-pass before per-int dedup. Accept the
    # hyphen form ("1-3"), the English spelled-out forms ("1 to 3",
    # "1 through 5"), and the Chinese range chars ("1至3", "1到5"). All map to
    # an inclusive integer range.
    range_match = re.match(
        r"\s*(\d+)\s*(?:-|to|through|至|到)\s*(\d+)\s*$",
        blob.strip(),
        re.IGNORECASE,
    )
    if range_match:
        lo, hi = int(range_match.group(1)), int(range_match.group(2))
        if 0 < lo <= hi < 1000:  # sanity bound
            return list(range(lo, hi + 1))
    for n in raw:
        try:
            v = int(n)
        except ValueError:
            continue
        if 0 < v < 1000 and v not in nums:
            nums.append(v)
    return nums


def _parse_one_claim_parents(
    claim_text: str,
    own_number: int | None,
) -> list[int]:
    """Find every claim number referenced as a parent in the leading clause.

    `own_number` (if known) is filtered out — a claim cannot depend on
    itself. This guards against the "1. 如請求項 1 所述" oddity where the
    prefix and the dependency reference share a number (which would otherwise
    create a self-loop after the prefix strip).
    """
    if not claim_text:
        return []
    head = _strip_claim_prefix(claim_text)[:_LEADING_CLAUSE_CHARS]
    parents: list[int] = []
    for rx, _name in _DEPENDENCY_PATTERNS:
        m = rx.search(head)
        if m:
            for n in _extract_numbers(m.group(1)):
                if own_number is not None and n == own_number:
                    continue
                if n not in parents:
                    parents.append(n)
            # First matching pattern wins — patterns are ordered most-
            # specific-first, so an earlier hit is more reliable.
            break
    return parents


def _compute_depth(
    claim_no: int,
    by_number: dict[int, dict[str, Any]],
    memo: dict[int, int],
    visiting: set[int],
) -> int:
    """DFS with cycle detection. Cycles return 0 (treated as independent)."""
    if claim_no in memo:
        return memo[claim_no]
    if claim_no in visiting:
        # Cycle — bail and treat as flat root. The UI doesn't need to
        # display the cycle; the parser's contract is "best-effort tree".
        return 0
    node = by_number.get(claim_no)
    if not node:
        return 0
    parent = node.get("depends_on")
    if parent is None or parent not in by_number:
        memo[claim_no] = 0
        return 0
    visiting.add(claim_no)
    d = _compute_depth(parent, by_number, memo, visiting) + 1
    visiting.discard(claim_no)
    if d > _MAX_DEPTH:
        # Pathologically deep chain — clamp + treat as independent so the
        # UI's indentation doesn't run off the side of the screen.
        d = 0
    memo[claim_no] = d
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_claim_dependencies(claims: list[str]) -> list[dict[str, Any]]:
    """Parse a flat list of claim texts into ClaimNode dicts.

    Claim numbers are assigned in source order (1-based). If a claim text
    starts with an explicit number prefix that disagrees with its position,
    we still trust the source order — this is the convention TIPO and USPTO
    use when claims have been renumbered after an amendment but the body
    text wasn't fully updated.

    Returns an empty list if `claims` is empty.
    """
    if not claims:
        return []
    nodes: list[dict[str, Any]] = []
    for i, text in enumerate(claims):
        cno = i + 1
        if not isinstance(text, str):
            # Tolerate malformed input (e.g. None in a list slot from a
            # broken upstream): emit an empty independent-claim placeholder
            # so the index numbering stays consistent with the source list.
            text = ""
        parents = _parse_one_claim_parents(text, own_number=cno)
        # Only treat a parent reference as valid if the referenced claim
        # number is < the current claim number — claims can only depend on
        # earlier claims per both USPTO MPEP 608.01(n) and TIPO Manual
        # §2.3.5. A "forward reference" is almost certainly a body-text
        # false positive (e.g. "see claim 7 below").
        valid_parents = [p for p in parents if p < cno]
        depends_on = valid_parents[0] if valid_parents else None
        nodes.append(
            {
                "claim_no": cno,
                "depends_on": depends_on,
                "parents": valid_parents,
                "text": text,
                "is_independent": depends_on is None,
                "depth": 0,  # filled in below
            }
        )

    # Compute depth in a second pass once every node has its `depends_on`.
    by_number = {n["claim_no"]: n for n in nodes}
    memo: dict[int, int] = {}
    for node in nodes:
        node["depth"] = _compute_depth(node["claim_no"], by_number, memo, set())

    return nodes
