"""§26 claim-support lint — 撰稿側確定性檢查 (no LLM).

專利法 §26 第 2 項：請求項必須「為說明書所支持」。撰稿階段最常見、也最容易在送件
前被審查官挑出的缺陷之一，就是**請求項出現了說明書從未描述的技術特徵**
(an unsupported limitation)。這是一個 *確定性可檢查* 的 smell：把每個請求項的實質
技術用語抽出來，逐一比對說明書字面上有沒有對應；完全找不到對應的用語，就是 §26
支持度的高風險點。

設計哲學 (呼應 docs/research 知識地圖的兩條原則)：
  1. **確定性 lint 先於 LLM** — 純字串比對，可重現、零幻覺、可解釋。
  2. **human-in-the-loop** — 這是 LINT 不是法律判斷。它只回答「說明書字面上有沒有提到
     這個請求項用語」。同義詞 / 上位下位 / 語意等同造成的「實質支持」本模組看不出來
     (那需要語意比對)，所以本 lint 會有 false positive。每個結果都標為「待專利師覆核」
     而非斷言違法。

與既有純解析模組 (`claim_tree.py` / `element_table.py`) 同血統：自含、無外部依賴、有 CLI。
NOT wired into the orchestrator — callers import `check_claim_support` explicitly.

CLI:
    python -m backend.ai_engine.claim_support
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field

from backend.ai_engine.element_table import _EN_STOPWORDS

# ---------------------------------------------------------------------------
# Tokenisation (deterministic, two scripts)
# ---------------------------------------------------------------------------
# A "support unit" is the atom we check for presence in the spec:
#   - Latin: a lowercased content word (>= 2 chars, not a stopword). Whole-word
#     so "microchannel" must appear as such, not be faked by a shared substring.
#   - CJK: a character BIGRAM. Patents have no whitespace, and a unigram match is
#     far too permissive (almost every Han char appears *somewhere* in a spec),
#     so bigrams are the granularity that makes "this term is in the spec" mean
#     something. This mirrors the lexical embedder's bigram trick in rag.py.

_LATIN_WORD_RE = re.compile(r"[a-z][a-z\-]{1,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

# CJK boilerplate that is structural claim language, NEVER a technical feature.
# These bigrams are excluded from the claim's checked units (so we don't flag
# "所述" as an unsupported "term"). Kept deliberately tight — category words like
# 方法/裝置/系統 are NOT here because they are real (and usually appear in the spec
# anyway).
_ZH_BOILERPLATE_BIGRAMS = {
    "所述",
    "其中",
    "一種",
    "前述",
    "包含",
    "包括",
    "以及",
    "根據",
    "依據",
    "該等",
    "複數",
    "至少",
    "特徵",
    "及其",
    "或其",
    "用以",
    "用於",
    "藉以",
    "以使",
    "其特",
    "徵在",
}

# Latin claim boilerplate beyond the shared stopword set.
_EN_CLAIM_STOPWORDS = {
    "claim",
    "claims",
    "wherein",
    "comprising",
    "consisting",
    "according",
    "method",
    "apparatus",
    "system",
    "device",
    "plurality",
    "least",
    "one",
    "first",
    "second",
    "third",
    "configured",
    "adapted",
    "said",
    "least",
}

# Claim cross-reference clauses to strip BEFORE extracting terms, so a dependent
# claim's "如請求項1所述之方法" / "according to claim 1" doesn't pollute the term
# set with the referenced claim's structural words.
_XREF_PATTERNS = [
    # ZH: 如/依/依據/根據 (前述) 請求項 第?N (項) 所述 之 ...，含 N、M 或 N至M 之範圍。
    re.compile(r"如?(?:依|依據|根據)?(?:前述)?請求項第?[\d\s、,，或至到\-~]+項?所述之?"),
    re.compile(r"請求項第?[\d\s、,，或至到\-~]+項?(?:所述)?"),
    # EN: "according to claim 1", "of claim 1", "as claimed in claim 1", "as in claim 1"
    re.compile(r"\b(?:according to|of|as claimed in|as recited in|as in)\s+claims?\s+[\d\s,and\-]+", re.I),
]

# Leading "一種" preamble (TW claim preamble) — strip so it isn't counted.
_ZH_PREAMBLE = re.compile(r"^\s*一種")
# Leading claim numbering "1." / "1、" / "1．"
_CLAIM_NUM_PREFIX = re.compile(r"^\s*\d+\s*[\.\．、]\s*")


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _spec_index(spec_text: str) -> tuple[set[str], set[str]]:
    """Build the spec's support index: (latin_words, cjk_bigrams)."""
    norm = _normalise(spec_text).lower()
    words = {w for w in _LATIN_WORD_RE.findall(norm) if w not in _EN_STOPWORDS}
    bigrams: set[str] = set()
    for run in _CJK_RUN_RE.findall(_normalise(spec_text)):  # case-irrelevant for CJK
        for i in range(len(run) - 1):
            bigrams.add(run[i : i + 2])
    return words, bigrams


def _strip_xrefs(claim_text: str) -> str:
    out = _CLAIM_NUM_PREFIX.sub("", claim_text)
    for pat in _XREF_PATTERNS:
        out = pat.sub(" ", out)
    out = _ZH_PREAMBLE.sub(" ", out)
    return out


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ClaimSupport:
    claim_no: int
    is_independent: bool
    support_ratio: float  # supported units / total checked units, in [0, 1]
    total_units: int
    unsupported_fragments: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        """True if the claim has ANY unsupported fragment — i.e. a term the spec
        never literally mentions. A flagged claim is a §26-support REVIEW prompt,
        not a defect finding."""
        return bool(self.unsupported_fragments)


def _looks_independent(claim_text: str) -> bool:
    # Mirror rag._looks_independent: dependent claims back-reference another claim.
    return not re.search(
        r"\baccording to claim\b|\b依.{0,5}請求項\b|\bof claim\b|請求項第?\s*\d", claim_text, re.I
    )


def _cjk_unsupported_fragments(run: str, bigrams: set[str]) -> tuple[list[str], int, int]:
    """For one CJK run, return (fragments, total_units, supported_units).

    Units are character BIGRAMS (n-1 of them for a run of length n); a bigram is
    "supported" if the spec has it, or it is structural boilerplate. Single-char
    runs carry no checkable unit (a lone Han char is almost always a particle),
    so they contribute nothing. Reported fragments are maximal uncovered
    substrings of length >= 2 — a one-char gap (e.g. the determiner 該 between two
    supported terms) is dropped as noise rather than flagged as a missing term."""
    n = len(run)
    if n < 2:
        return [], 0, 0
    covered = [False] * n
    supported = 0
    for i in range(n - 1):
        bg = run[i : i + 2]
        if bg in bigrams or bg in _ZH_BOILERPLATE_BIGRAMS:
            covered[i] = covered[i + 1] = True
            supported += 1
    frags: list[str] = []
    i = 0
    while i < n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j < n and not covered[j]:
            j += 1
        if j - i >= 2:  # drop single-char gaps (particles / determiners)
            frags.append(run[i:j])
        i = j
    return frags, n - 1, supported


def check_claim_support(
    claims: list[str],
    spec_text: str,
    jurisdiction: str = "TW",
) -> list[ClaimSupport]:
    """Lint each claim for §26 literal support in the specification.

    Returns one ClaimSupport per claim (claim_no is 1-based, matching the
    convention in rag.chunk_patent). ``jurisdiction`` is advisory — both scripts
    are always checked because filings are routinely bilingual.

    Honest-scope reminder: a flagged term means "the spec does not LITERALLY
    contain this term", which is a strong §26 smell but NOT a legal conclusion
    (synonyms / generic-species support are invisible to a literal check)."""
    words, bigrams = _spec_index(spec_text)
    results: list[ClaimSupport] = []
    for i, claim in enumerate(claims):
        cno = i + 1
        cleaned = _normalise(_strip_xrefs(claim))

        total = 0
        supported = 0
        frags: list[str] = []

        # Latin units (word-level).
        for w in _LATIN_WORD_RE.findall(cleaned.lower()):
            if w in _EN_STOPWORDS or w in _EN_CLAIM_STOPWORDS or len(w) < 2:
                continue
            total += 1
            if w in words:
                supported += 1
            else:
                frags.append(w)

        # CJK units (bigram-coverage, readable fragments).
        for run in _CJK_RUN_RE.findall(cleaned):
            run_frags, run_total, run_covered = _cjk_unsupported_fragments(run, bigrams)
            total += run_total
            supported += run_covered
            frags.extend(run_frags)

        ratio = 1.0 if total == 0 else round(supported / total, 3)
        results.append(
            ClaimSupport(
                claim_no=cno,
                is_independent=_looks_independent(claim),
                support_ratio=ratio,
                total_units=total,
                unsupported_fragments=frags,
            )
        )
    return results


def support_summary(results: list[ClaimSupport]) -> dict:
    """Roll-up for a draft / UI badge."""
    flagged = [r for r in results if r.flagged]
    worst = min((r.support_ratio for r in results), default=1.0)
    return {
        "claims_total": len(results),
        "claims_flagged": len(flagged),
        "flagged_claim_nos": [r.claim_no for r in flagged],
        "min_support_ratio": worst,
        "all_supported": not flagged,
    }


# ---------------------------------------------------------------------------
# CLI — mirrors `python -m backend.ai_engine.element_table`
# ---------------------------------------------------------------------------

_DEMO_SPEC = (
    "【技術領域】本發明關於一種電動車充電管理方法。\n"
    "【發明內容】本發明的充電管理方法，由伺服器接收每個充電樁的最大可供電功率，"
    "並動態下發能源管理方案以最佳化整體供電。伺服器依據電網負載調整各充電樁的輸出。\n"
    "【實施方式】在較佳實施例中，伺服器與複數個充電樁通訊。"
)
_DEMO_CLAIMS = [
    # claim 1: every feature is in the spec → should be well-supported.
    "一種電動車充電管理方法，包含：由伺服器接收每個充電樁的最大可供電功率；"
    "以及動態下發能源管理方案。",
    # claim 2: introduces 「區塊鏈結算」 which the spec NEVER mentions → §26 smell.
    "如請求項1所述之方法，其中該能源管理方案透過區塊鏈結算進行計費。",
]


def _main() -> None:
    print("=" * 64)
    print("claim_support lint — DEMO (TW)")
    print("=" * 64)
    results = check_claim_support(_DEMO_CLAIMS, _DEMO_SPEC, "TW")
    for r in results:
        tag = "⚠ REVIEW" if r.flagged else "✓ ok"
        kind = "indep" if r.is_independent else "dep"
        print(f"  claim {r.claim_no} [{kind}] {tag}  support={r.support_ratio}")
        if r.unsupported_fragments:
            print(f"      spec 未提及: {r.unsupported_fragments}")
    print()
    print("  summary:", support_summary(results))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _main()
