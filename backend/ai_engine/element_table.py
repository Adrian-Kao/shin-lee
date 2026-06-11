"""Reference-numeral → element-table extractor (Q8, OCR baseline).

Patents describe figures by *reference numerals*: "a heat sink 200",
"the substrate 10", "first electrode 102", and in Chinese "基板 10",
"第一電極 102".  Office Action rejections constantly reason across these
numerals — e.g. "element 102 of the present application corresponds to
element 200 of the cited reference".  A text-only RAG that cannot build
the element table is blind to that reasoning.

This module is the **OCR-baseline** half of the Q8 decision
("OCR + Vision LLM 混合; OCR 必跑、Vision LLM 介面 stub", see
docs/DECISIONS.md / docs/QUESTIONS.md §Q8).  It extracts numerals purely
from the *text layer* of the specification / OA — no images required —
which is the basic patent-search competency that must run on every case.

The complementary **Vision-LLM figure analysis stays a stub**: it lives in
`backend/ai_engine/pdf_parser.py` (page-level `llm_client.vision_ocr`
fallback) and `backend/ai_engine/llm_client.py::vision_ocr`.  Wiring a real
figure-understanding model ("is figure 3 here the same structure as figure
2 of the cited reference?") is the future P1 work; this module deliberately
does NOT depend on it.

Scope note: this is a self-contained module + CLI + tests.  It is NOT wired
into the orchestrator pipeline — callers import `extract_element_table` /
`correlate` explicitly.

CLI:
    python -m backend.ai_engine.element_table
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Tunables / heuristics
# ---------------------------------------------------------------------------

# Reference numerals in patent drawings are small integers (typically 1-4
# digits, often using a hundreds-block-per-figure convention: 100s, 200s).
# Anything with 5+ digits is almost certainly a patent number, an application
# number, a statute citation fragment, etc.  We cap at 4 digits.
_MAX_NUMERAL = 9999
_MIN_NUMERAL = 1

# Words we never want to keep as the *description* — articles, and a handful
# of structural words that would otherwise leak in as the leading token.
_EN_STOPWORDS = {
    "a",
    "an",
    "the",
    "said",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "with",
    "by",
    "as",
    "is",
    "are",
    "be",
    # prepositions / connectives that can lead the captured window but are
    # never part of the element name itself ("mounted on the substrate 10").
    "on",
    "at",
    "from",
    "into",
    "onto",
    "upon",
    "through",
    "between",
    "over",
    "under",
    "within",
    "about",
    "via",
    "per",
    "that",
    "which",
    "wherein",
    "whereby",
    # spec verbs / connectives that lead a captured window but aren't the name
    "comprising",
    "comprises",
    "comprise",
    "including",
    "includes",
    "include",
    "having",
    "has",
    "have",
    "defining",
    "defines",
    "define",
    "disposed",
    "mounted",
    "provided",
    "arranged",
    "formed",
    "coupled",
    "connected",
    "thereon",
    "thereof",
    "therein",
    "thereto",
}

# Tokens that, when they *precede* a number, mark it as NOT a reference
# numeral (claim/section/figure/paragraph/citation references, money, etc.).
# Matched case-insensitively against the word immediately before the number.
_EN_BLOCKLIST_PREV = {
    "claim",
    "claims",
    "fig",
    "figs",
    "figure",
    "figures",
    "page",
    "pages",
    "paragraph",
    "paragraphs",
    "para",
    "section",
    "sections",
    "step",
    "steps",
    "no",
    "no.",
    "u.s.c",
    "usc",
    "§",
    "chapter",
    "item",
    "example",
    "table",
    "embodiment",
    "column",
    "col",
    "line",
    "lines",
    "row",
    "rows",
    "version",
    "part",
    "vol",
    "volume",
}

# Subset of the above that is NEVER a legitimate element head noun.  Used to
# reject when the captured phrase *itself ends* with one of these
# ("claim 1", "Fig 3").  Deliberately excludes "section/column/line/part/
# row/table/item" which routinely appear as element names in specs.
_STRUCTURAL_HEADWORDS = {
    "claim",
    "claims",
    "fig",
    "figs",
    "figure",
    "figures",
    "page",
    "pages",
    "paragraph",
    "paragraphs",
    "para",
    "step",
    "steps",
    "no",
    "u.s.c",
    "usc",
    "chapter",
    "embodiment",
}

# Chinese counterpart of the above — when one of these characters/words
# directly precedes the number, it is a structural reference, not an element.
_ZH_BLOCKLIST_PREV = {
    "請求項",
    "圖",
    "第",
    "頁",
    "段",
    "節",
    "步驟",
    "項",
    "條",
    "款",
    "例",
    "表",
    "欄",
    "列",
    "行",
    "卷",
    "冊",
    "章",
    "民國",
    "年",
    "月",
    "日",
    "號",
}

# Chinese measure words / units that, when they FOLLOW the number, mark it as
# a quantity / address / date / citation rather than a drawing reference
# numeral — "2 段", "113 年", "185 號", "3 樓", "1 千元", "10 項", "第 1 條".
# (In a spec, "基板 10" is followed by punctuation/space/another noun, not by
# one of these unit characters.)
_ZH_BLOCKLIST_NEXT = {
    "段",
    "節",
    "頁",
    "項",
    "條",
    "款",
    "章",
    "卷",
    "冊",
    "號",
    "樓",
    "室",
    "年",
    "月",
    "日",
    "時",
    "分",
    "秒",
    "個",
    "份",
    "件",
    "次",
    "種",
    "類",
    "千",
    "萬",
    "億",
    "元",
    "角",
    "度",
    "級",
    "層",
    "排",
    "組",
    "步",
    "名",
    "位",
    "人",
    "家",
    "間",
    "棟",
    "台",
    "輛",
    "張",
    "片",
    "枚",
    "顆",
}

# A bare 4-digit number in the plausible-year range is almost always a year,
# not a reference numeral, *unless* it carries a descriptive phrase that
# clearly makes it an element.  We treat 1900-2099 as suspect.
_YEAR_LO, _YEAR_HI = 1900, 2099


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ElementMention:
    """One occurrence of a numeral with its candidate description phrase."""

    numeral: int
    phrase: str
    raw_context: str = ""


@dataclass
class Element:
    """Aggregated view of one reference numeral across the whole document."""

    numeral: int
    description: str
    mention_count: int = 0
    candidate_phrases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# English extraction
# ---------------------------------------------------------------------------

# A descriptive phrase (1-4 words, letters/hyphens), optional space, then a
# 1-4 digit number that is a standalone token (word boundary on both sides).
# We capture a generous leading window and trim it down afterwards.
_EN_PHRASE = re.compile(
    r"(?P<phrase>(?:[A-Za-z][A-Za-z\-]*\s+){0,4}[A-Za-z][A-Za-z\-]*)"
    r"\s+(?P<num>\d{1,4})\b"
)


def _clean_en_phrase(phrase: str) -> str:
    """Strip leading articles/stopwords; keep the trailing 1-3 content words."""
    words = phrase.strip().split()
    # Keep at most the last 3 words — the noun phrase nearest the numeral is
    # almost always the element name ("non-uniform cross section").
    if len(words) > 3:
        words = words[-3:]
    # Strip leading articles/stopwords ("the", "a", "said", ...).  Done AFTER
    # the window trim so an article that slips into the last-3 window
    # ("a heat sink") is still removed.
    while words and words[0].lower() in _EN_STOPWORDS:
        words.pop(0)
    return " ".join(words).strip()


# Only ever need a few chars on either side of a match to read the adjacent
# word. Bounding the slice turns the per-match neighbour lookup from O(n)
# (slicing `text[:start]` copies up to the whole doc each call) into O(1), so
# extraction over a large spec / OA stays linear instead of quadratic. 64 chars
# comfortably covers the longest single word + surrounding punctuation.
_NEIGHBOUR_WINDOW = 64


def _en_prev_word(text: str, start: int) -> str:
    """Return the lowercase word ending just before index `start`, if any.

    Slices only a bounded window before `start` (see `_NEIGHBOUR_WINDOW`) so
    this is O(1) per call rather than O(start) — critical on large documents
    where thousands of matches would otherwise make extraction quadratic.
    """
    left = text[max(0, start - _NEIGHBOUR_WINDOW) : start].rstrip()
    m = re.search(r"([A-Za-z§\.]+)$", left)
    return m.group(1).lower() if m else ""


def _extract_en(text: str) -> list[ElementMention]:
    mentions: list[ElementMention] = []
    for m in _EN_PHRASE.finditer(text):
        num = int(m.group("num"))
        if not (_MIN_NUMERAL <= num <= _MAX_NUMERAL):
            continue
        phrase = _clean_en_phrase(m.group("phrase"))
        if not phrase:
            continue
        # Blocklist: the word immediately before the whole match
        # ("claim 1", "Fig 3", "page 5", "§ 103") is a structural reference.
        prev = _en_prev_word(text, m.start())
        if prev in _EN_BLOCKLIST_PREV:
            continue
        # The *last* word of the phrase is the head noun.  Reject only when it
        # is an unambiguously-structural word that is NEVER a real element name
        # ("claim 1", "Fig 3", "paragraph 23").  Words like "section",
        # "column", "line", "part", "row", "table" CAN be element heads
        # ("cross section 305"), so they are excluded from this stricter set.
        last_word = phrase.split()[-1].lower()
        if last_word in _STRUCTURAL_HEADWORDS:
            continue
        # Statute / citation context: "35 U.S.C. § 103", "§ 103", "Title 35".
        # The word *after* the number disambiguates these from elements.
        nxt = _en_next_word(text, m.end())
        if nxt in {"u.s.c", "usc", "cfr", "c.f.r"}:
            continue
        # Year heuristic: a 4-digit number in year range with a phrase that is
        # itself non-technical is suspect; but a real element like "buffer
        # 2010" is rare.  We reject only when it *looks* like a date context.
        if _YEAR_LO <= num <= _YEAR_HI and _looks_like_year(text, m):
            continue
        mentions.append(ElementMention(num, phrase, m.group(0).strip()))
    return mentions


def _en_next_word(text: str, end: int) -> str:
    """Return the lowercase word starting just after index `end`, if any.

    Trailing periods are stripped so "U.S.C." normalises to "u.s.c".

    Slices only a bounded window after `end` (see `_NEIGHBOUR_WINDOW`) so this
    is O(1) per call — see `_en_prev_word` for the quadratic-blowup rationale.
    """
    right = text[end : end + _NEIGHBOUR_WINDOW].lstrip()
    m = re.match(r"([A-Za-z\.]+)", right)
    return m.group(1).lower().strip(".") if m else ""


def _looks_like_year(text: str, m: re.Match) -> bool:
    """True if a 4-digit number sits in an obvious date/citation context."""
    window = text[max(0, m.start() - 12) : m.end() + 4].lower()
    # "in 1999", "© 2020", "(2018)", month names, "20xx-" date fragments.
    if re.search(r"(?:in|since|©|\(|year)\s*\d{4}", window):
        return True
    if re.search(r"\b\d{4}[-/]\d", window):  # 2025-04, 2025/04
        return True
    months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    if any(mon in window for mon in months):
        return True
    return False


# ---------------------------------------------------------------------------
# Chinese / TW extraction
# ---------------------------------------------------------------------------

# A run of CJK chars (the element name) optionally separated by a space from a
# 1-4 digit number.  After NFKC the digits are halfwidth.
_ZH_PHRASE = re.compile(r"(?P<phrase>[一-鿿]{1,8})\s*(?P<num>\d{1,4})\b")

# Leading Chinese connectives / particles that get greedily swept into the
# captured phrase but are not part of the element name — strip from the front.
# ("與第二電極 104" -> "第二電極 104").  Note 第 is NOT here (它 leads 第一/第二).
# NOTE: deliberately conservative.  Directional chars (上下內外前後左右) are
# NOT stripped because they are frequently part of element names
# ("上電極" upper electrode, "內層" inner layer).  We only strip clear
# connectives / particles.
_ZH_LEADING_PARTICLES = "與及和或之的該本但而則並又且亦也乃即把將從往向"


def _strip_zh_leading(phrase: str) -> str:
    while phrase and phrase[0] in _ZH_LEADING_PARTICLES:
        phrase = phrase[1:]
    return phrase


def _extract_zh(text: str) -> list[ElementMention]:
    mentions: list[ElementMention] = []
    for m in _ZH_PHRASE.finditer(text):
        num = int(m.group("num"))
        if not (_MIN_NUMERAL <= num <= _MAX_NUMERAL):
            continue
        phrase = _strip_zh_leading(m.group("phrase").strip())
        if not phrase:
            continue
        # Blocklist (preceding): structural markers that end the phrase
        # ("請求項 9", "圖 3", "第 1", "114 年").  Chinese has no spaces, so the
        # marker is glued onto the captured phrase — check the phrase tail.
        if any(phrase.endswith(b) or phrase == b for b in _ZH_BLOCKLIST_PREV):
            continue
        # Blocklist (following): a measure word / unit right after the number
        # (skipping intervening whitespace) marks a quantity / address / date,
        # not a drawing numeral — "2 段", "185 號", "3 樓", "1 千元", "10 項".
        tail = text[m.end() : m.end() + 4].lstrip()
        if tail and tail[0] in _ZH_BLOCKLIST_NEXT:
            continue
        # Year-ish: a 4-digit Gregorian year in a date context.
        if _YEAR_LO <= num <= _YEAR_HI:
            window = text[max(0, m.start() - 6) : m.end() + 2]
            if "年" in window or "民國" in window or re.search(r"\d{4}[-/]\d", window):
                continue
        mentions.append(ElementMention(num, phrase, m.group(0).strip()))
    return mentions


# ---------------------------------------------------------------------------
# Aggregation + public API
# ---------------------------------------------------------------------------


def _aggregate(mentions: list[ElementMention]) -> dict[int, Element]:
    """Collapse mentions to one Element per numeral.

    Tie-break rule for picking the canonical description:
      1. Among phrases seen for a numeral, prefer the one that appears most
         frequently (most agreed-upon name).
      2. Break ties by the *longest* phrase (more specific / descriptive,
         e.g. "non-uniform cross section" over "section").
      3. Final tie-break: lexicographically smallest, for determinism.
    """
    by_num: dict[int, list[str]] = defaultdict(list)
    for men in mentions:
        by_num[men.numeral].append(men.phrase)

    out: dict[int, Element] = {}
    for num, phrases in by_num.items():
        counts = Counter(phrases)
        best = max(
            counts.keys(),
            key=lambda p: (counts[p], len(p), _neg_lexicographic(p)),
        )
        out[num] = Element(
            numeral=num,
            description=best,
            mention_count=len(phrases),
            candidate_phrases=sorted(set(phrases)),
        )
    return out


def _neg_lexicographic(s: str):
    """Sort key so that 'smaller string wins' under max()."""
    # max() wants the *largest*; we want lexicographically smallest as the
    # final tie-break, so invert by mapping each char to its negative ordinal.
    return tuple(-ord(c) for c in s)


def extract_elements(text: str, jurisdiction: str = "US") -> dict[int, Element]:
    """Full extraction returning rich `Element` objects keyed by numeral.

    Always NFKC-normalises first (fullwidth digits → halfwidth, etc.).  Runs
    both the English and Chinese extractors regardless of `jurisdiction` —
    real filings are routinely bilingual — and merges the mentions.  The
    `jurisdiction` arg is advisory and reserved for future locale tuning.
    """
    norm = unicodedata.normalize("NFKC", text or "")
    mentions = _extract_en(norm) + _extract_zh(norm)
    return _aggregate(mentions)


def extract_element_table(text: str, jurisdiction: str = "US") -> dict[int, str]:
    """Return the flat `numeral -> best description phrase` mapping.

    This is the headline entry point.  See `extract_elements` for the
    richer per-numeral view (mention counts, candidate phrases).
    """
    return {num: el.description for num, el in extract_elements(text, jurisdiction).items()}


# ---------------------------------------------------------------------------
# Correlation across an application table and a cited-reference table
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z一-鿿]+")


def _tokens(phrase: str) -> set[str]:
    """Lowercase token set; CJK split per-character so '基板' overlaps '基板層'."""
    toks: set[str] = set()
    for chunk in _TOKEN_RE.findall(phrase.lower()):
        if re.search(r"[一-鿿]", chunk):
            toks.update(chunk)  # per-character for CJK
        else:
            toks.add(chunk)  # whole word for latin
    # Drop pure stopwords from the comparison set.
    return {t for t in toks if t not in _EN_STOPWORDS}


def _similarity(a: str, b: str) -> float:
    """Jaccard token overlap in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def correlate(
    app_table: dict,
    cited_table: dict,
    threshold: float = 0.34,
) -> list[dict]:
    """Propose `app numeral ↔ cited numeral` correspondences by description.

    This is the "element 102 ↔ element 200" mapping the examiner reasons
    about.  Similarity is a simple shared-token (Jaccard) score — intentionally
    cheap; a real system would add embeddings / synonym tables.

    Args accept either `{numeral: str}` tables (from `extract_element_table`)
    or `{numeral: Element}` tables (from `extract_elements`).

    Returns a list of dicts sorted by descending score, each:
        {"app_numeral", "app_description",
         "cited_numeral", "cited_description", "score"}
    Only pairs scoring >= `threshold` are returned.  Each app numeral keeps
    only its single best match (greedy, highest score wins).
    """
    app = _as_str_table(app_table)
    cited = _as_str_table(cited_table)

    candidates: list[dict] = []
    for an, adesc in app.items():
        best = None
        for cn, cdesc in cited.items():
            score = _similarity(adesc, cdesc)
            if score >= threshold and (best is None or score > best["score"]):
                best = {
                    "app_numeral": an,
                    "app_description": adesc,
                    "cited_numeral": cn,
                    "cited_description": cdesc,
                    "score": round(score, 3),
                }
        if best is not None:
            candidates.append(best)

    candidates.sort(key=lambda d: (-d["score"], d["app_numeral"]))
    return candidates


def _as_str_table(table: dict) -> dict[int, str]:
    """Coerce {numeral: Element|str} → {numeral: str}."""
    out: dict[int, str] = {}
    for k, v in table.items():
        out[int(k)] = v.description if isinstance(v, Element) else str(v)
    return out


# ---------------------------------------------------------------------------
# CLI — mirrors `python -m backend.ai_engine.deadline`
# ---------------------------------------------------------------------------


def _print_table(label: str, path: Path, jurisdiction: str) -> dict[int, str]:
    print("=" * 64)
    print(f"{label}  ({path})")
    print("=" * 64)
    if not path.exists():
        print("  (sample not found — skipped)")
        return {}
    text = path.read_text(encoding="utf-8")
    elements = extract_elements(text, jurisdiction)
    if not elements:
        print("  (no reference numerals found)")
        return {}
    print(f"  {'numeral':>8}  {'cnt':>3}  description")
    print(f"  {'-' * 8}  {'-' * 3}  {'-' * 32}")
    for num in sorted(elements):
        el = elements[num]
        print(f"  {num:>8}  {el.mention_count:>3}  {el.description}")
    return {n: e.description for n, e in elements.items()}


# Spec-style demo text.  The shipped OA samples are pure argument/admin prose
# with NO drawing reference numerals, so they (correctly) yield empty tables.
# These snippets exercise the populated-table + correlation path end to end.
_DEMO_APP_SPEC = (
    "The cooling apparatus comprises a substrate 10 and a heat sink 200 "
    "mounted thereon. A first electrode 102 and a second electrode 104 are "
    "disposed on the substrate 10. The heat sink 200 includes a microchannel "
    "300 having a non-uniform cross section 305."
)
_DEMO_CITED_SPEC = (
    "The reference discloses a base plate 5 carrying a heat sink 50. "
    "An electrode 12 contacts the base plate 5. The heat sink 50 defines a "
    "channel 60 of varying cross section 65."
)
_DEMO_TW_SPEC = "如圖一所示，基板 10 上設有第一電極 102 與第二電極 104，散熱片 ２００ 位於頂部。"


def _print_dict_table(label: str, elements: dict[int, Element]) -> None:
    print("=" * 64)
    print(label)
    print("=" * 64)
    if not elements:
        print("  (no reference numerals found)")
        return
    print(f"  {'numeral':>8}  {'cnt':>3}  description")
    print(f"  {'-' * 8}  {'-' * 3}  {'-' * 32}")
    for num in sorted(elements):
        el = elements[num]
        print(f"  {num:>8}  {el.mention_count:>3}  {el.description}")


def _main() -> None:
    root = Path(__file__).resolve().parents[2]
    samples = root / "data" / "oa_samples"

    # 1. Real shipped samples (expected empty — they carry no figure numerals).
    _print_table("US sample", samples / "sample_oa_us.txt", "US")
    print()
    _print_table("TW sample", samples / "sample_oa_tw.txt", "TW")

    # 2. Spec-style demo so the populated path is visible.
    print()
    app = extract_elements(_DEMO_APP_SPEC, "US")
    _print_dict_table("DEMO application spec (EN)", app)
    print()
    cited = extract_elements(_DEMO_CITED_SPEC, "US")
    _print_dict_table("DEMO cited reference spec (EN)", cited)
    print()
    tw_demo = extract_elements(_DEMO_TW_SPEC, "TW")
    _print_dict_table("DEMO application spec (TW, incl. fullwidth digits)", tw_demo)

    # 3. Examiner-style "102 <-> 200" correspondence between app and cited.
    print()
    print("=" * 64)
    print("correlate(): DEMO application spec  <->  DEMO cited reference")
    print("=" * 64)
    pairs = correlate(app, cited)
    if not pairs:
        print("  (no correspondences above threshold)")
    for p in pairs:
        print(
            f"  app {p['app_numeral']:>4} ({p['app_description']!r})"
            f"  <->  cited {p['cited_numeral']:>4} ({p['cited_description']!r})"
            f"   score={p['score']}"
        )


if __name__ == "__main__":
    # Windows consoles default to cp1252 and choke on CJK / box chars.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _main()
