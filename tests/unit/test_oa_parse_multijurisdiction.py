"""Multi-jurisdiction OA parsing — EP / CN / KR (completing Day-11N).

Day 11N added EP/CN/KR *deadline* rules, but the mock OA parser
(`MockLLM._mock_parse_oa`) only recognised TW + US rejection language, so an
EP/CN/KR office action could not be turned into `Rejection`s — the analyze
pipeline only computed their deadline. These tests pin the gap-closing work:

  1. Each new jurisdiction's office-action language maps to the EXISTING
     `RejectionType` values (no new enum members — models.py is frozen):
        - inventive step  → 103_obviousness
        - novelty         → 102_novelty
        - clarity/support/added-matter/記載不備 → other
  2. The 簡體 CN cues (条/款, 创造性, 新颖性) and the 繁體 TW cues (條/項,
     進步性, 新穎性) are DISTINCT code points, so a CN OA never fires a TW
     branch and a TW OA never fires a CN branch (no cross-fire).
  3. US + TW parsing is UNCHANGED (regression pin).
  4. The seed corpus has at least one indexed patent per new jurisdiction.

The `_mock_parse_oa` heuristics are deterministic + dependency-free, so we call
them directly (no network, no LLM mode juggling).
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.ai_engine.llm_client import MockLLM
from backend.shared.models import Rejection, RejectionType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OA_DIR = _REPO_ROOT / "data" / "oa_samples"


def _parse(text: str) -> list[dict]:
    """Run the mock parser and return the raw rejection dicts."""
    out = json.loads(MockLLM._mock_parse_oa(text))
    return out["rejections"]


def _types(rejections: list[dict]) -> set[str]:
    return {r["rejection_type"] for r in rejections}


def _sample(name: str) -> str:
    return (_OA_DIR / name).read_text(encoding="utf-8")


def _assert_models_validate(rejections: list[dict]) -> None:
    """Every emitted rejection must round-trip through the frozen Pydantic
    model with extra='forbid' (catches a stray key / bad enum / type drift)."""
    for r in rejections:
        Rejection(**r)


# ---------------------------------------------------------------------------
# EP (EPO) — Art. NN EPC
# ---------------------------------------------------------------------------


def test_ep_sample_maps_inventive_step_novelty_clarity_added_matter():
    rejections = _parse(_sample("sample_oa_ep.txt"))
    _assert_models_validate(rejections)
    types = _types(rejections)
    # Art. 56 → obviousness, Art. 54 → novelty, Art. 84 + Art. 123(2) → other
    assert RejectionType.OBVIOUSNESS_103.value in types
    assert RejectionType.NOVELTY_102.value in types
    assert RejectionType.OTHER.value in types
    # claims should have been extracted from "Claims 1-3 ... Claim 4 ... Claim 5"
    affected = {c for r in rejections for c in r["affected_claims"]}
    assert {1, 2, 3}.issubset(affected)


def test_ep_inline_inventive_step_only():
    text = "Claims 1-2 do not involve an inventive step within the meaning of Art. 56 EPC."
    rejections = _parse(text)
    _assert_models_validate(rejections)
    assert _types(rejections) == {RejectionType.OBVIOUSNESS_103.value}
    assert rejections[0]["affected_claims"] == [1, 2]


def test_ep_added_subject_matter_is_other():
    text = (
        "The amendment to claim 1 introduces subject-matter extending beyond the "
        "application as filed, contrary to Art. 123(2) EPC."
    )
    rejections = _parse(text)
    _assert_models_validate(rejections)
    assert RejectionType.OTHER.value in _types(rejections)


# ---------------------------------------------------------------------------
# CN (CNIPA) — 专利法第N条第M款 (简体)
# ---------------------------------------------------------------------------


def test_cn_sample_maps_creativity_novelty_disclosure():
    rejections = _parse(_sample("sample_oa_cn.txt"))
    _assert_models_validate(rejections)
    types = _types(rejections)
    # 第22条第3款 创造性 → obviousness, 第22条第2款 新颖性 → novelty,
    # 第26条第3款 充分公开 → other
    assert RejectionType.OBVIOUSNESS_103.value in types
    assert RejectionType.NOVELTY_102.value in types
    assert RejectionType.OTHER.value in types
    affected = {c for r in rejections for c in r["affected_claims"]}
    assert {1, 2, 3}.issubset(affected)  # 权利要求 1-3


def test_cn_inline_inventive_step_only():
    text = "权利要求 1-3 不具备创造性，不符合专利法第22条第3款的规定。"
    rejections = _parse(text)
    _assert_models_validate(rejections)
    assert _types(rejections) == {RejectionType.OBVIOUSNESS_103.value}
    assert rejections[0]["affected_claims"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# KR (KIPO) — 특허법 제N조제M항 (한글)
# ---------------------------------------------------------------------------


def test_kr_sample_maps_inventive_step_novelty_description_defect():
    rejections = _parse(_sample("sample_oa_kr.txt"))
    _assert_models_validate(rejections)
    types = _types(rejections)
    # 제29조제2항 진보성 → obviousness, 제29조제1항 신규성 → novelty,
    # 제42조 기재불비 → other
    assert RejectionType.OBVIOUSNESS_103.value in types
    assert RejectionType.NOVELTY_102.value in types
    assert RejectionType.OTHER.value in types
    affected = {c for r in rejections for c in r["affected_claims"]}
    assert {1, 2, 3}.issubset(affected)  # 청구항 1-3


def test_kr_inline_inventive_step_only():
    text = "청구항 1-3 은 인용발명에 의하여 진보성이 없으므로 특허법 제29조제2항의 규정에 의하여 거절이유를 통지합니다."
    rejections = _parse(text)
    _assert_models_validate(rejections)
    assert _types(rejections) == {RejectionType.OBVIOUSNESS_103.value}
    assert rejections[0]["affected_claims"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Cross-fire guards: TW (繁體) vs CN (简体) are mutually exclusive
# ---------------------------------------------------------------------------


def test_cn_simplified_does_not_trigger_tw_argument_text():
    """A pure 简体 CN OA must NOT produce a TW-flavoured examiner_argument.

    Both jurisdictions share the 102/103 RejectionType values, so we can't
    distinguish on type alone — we assert on the *argument language*: the CN
    branch emits 简体 (审查员/创造性/不符合), the TW branch emits 繁體
    (審查官/進步性/核駁). No rejection here may carry the TW 繁體 markers.
    """
    text = "权利要求 1-3 不具备创造性，不符合专利法第22条第3款的规定。"
    rejections = _parse(text)
    args = " ".join(r["examiner_argument"] for r in rejections)
    # 繁體-only markers that the TW branch would have emitted:
    for tw_marker in ("審查官", "進步性", "核駁", "請求項"):
        assert tw_marker not in args, f"CN OA leaked TW marker {tw_marker!r}: {args}"
    # And it really did parse as CN (简体 marker present):
    assert "创造性" in args or "审查员" in args


def test_tw_traditional_does_not_trigger_cn_argument_text():
    """A pure 繁體 TW OA must NOT produce a 简体 CN examiner_argument."""
    text = "請求項 1-3 不具進步性，依專利法第22條第2項規定核駁。"
    rejections = _parse(text)
    args = " ".join(r["examiner_argument"] for r in rejections)
    # 简体-only markers that the CN branch would have emitted:
    for cn_marker in ("审查员", "创造性", "新颖性", "权利要求", "不符合专利法"):
        assert cn_marker not in args, f"TW OA leaked CN marker {cn_marker!r}: {args}"
    assert "進步性" in args or "審查官" in args


# ---------------------------------------------------------------------------
# Regression: US + TW parse EXACTLY as before
# ---------------------------------------------------------------------------


def test_us_sample_unchanged():
    rejections = _parse(_sample("sample_oa_us.txt"))
    _assert_models_validate(rejections)
    # US sample: §103 obviousness + §102 novelty (claims aggregate to 1-5).
    by_type = {r["rejection_type"]: r for r in rejections}
    assert RejectionType.OBVIOUSNESS_103.value in by_type
    assert RejectionType.NOVELTY_102.value in by_type
    assert by_type[RejectionType.OBVIOUSNESS_103.value]["affected_claims"] == [1, 2, 3, 4, 5]
    assert by_type[RejectionType.NOVELTY_102.value]["affected_claims"] == [1, 2, 3, 4, 5]
    # US must NOT pick up any EP/CN/KR clause language.
    args = " ".join(r["examiner_argument"] for r in rejections)
    for foreign in ("EPC", "审查员", "심사관"):
        assert foreign not in args


def test_tw_sample_unchanged_antecedent_basis():
    rejections = _parse(_sample("sample_oa_tw.txt"))
    _assert_models_validate(rejections)
    types = _types(rejections)
    # The TW sample is an antecedent-basis (先行詞) 第26條第2項 rejection.
    assert RejectionType.ANTECEDENT_BASIS.value in types
    # It must NOT fire any CN/EP/KR branch.
    args = " ".join(r["examiner_argument"] for r in rejections)
    for foreign in ("EPC", "审查员", "심사관", "创造性"):
        assert foreign not in args


# ---------------------------------------------------------------------------
# Seed corpus: an indexed patent per new jurisdiction
# ---------------------------------------------------------------------------


def test_seed_has_patent_per_new_jurisdiction():
    from backend.patent_db.seed import DEMO_PATENTS

    jurisdictions = {p["jurisdiction"] for p in DEMO_PATENTS}
    for j in ("EP", "CN", "KR"):
        assert j in jurisdictions, f"seed corpus missing a {j} patent for retrieval"
    # Original jurisdictions must still be present (don't drop existing seeds).
    for j in ("US", "TW"):
        assert j in jurisdictions
