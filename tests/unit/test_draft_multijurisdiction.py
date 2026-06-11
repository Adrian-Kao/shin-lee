"""Jurisdiction-aware mock response drafts — CN / KR / EP / JP (+ TW/US pins).

Day 11N/11O/11P made deadline + OA parsing + retrieval multi-jurisdiction, but
`MockLLM._mock_draft` only produced a TW 申復書 (antecedent basis) or a generic
ENGLISH non-obviousness draft. So analysing a CN/KR/EP office action yielded an
English draft that didn't match the OA's language — jarring in a demo to a
CN/KR/EP firm.

These tests pin the gap-closing work:

  1. For each of CN / KR / EP (and JP), `_mock_draft` produces a draft in the
     OA's own language, arguing against the parsed rejection_type.
  2. Every jurisdiction draft cites a `[GROUNDED_REF_N]` that is INSIDE the
     grounded set the prompt offered (verifier-safe), `grounded_citations` is
     non-empty, and `confidence` ∈ (0, 1].
  3. Regression: the existing TW antecedent-basis 申復書 path and the
     US/generic English path are UNCHANGED (known phrase still appears).
  4. End-to-end via `oa_analyzer.draft_response` (mock mode): a CN rejection
     yields a 简体 `DraftResponse.draft_text` whose `grounded_citations` ⊆ the
     grounded set.

`_mock_draft` is deterministic + dependency-free, so we drive it directly; the
e2e check goes through `draft_response` exactly as the orchestrator does.
"""

from __future__ import annotations

import json
import re

from backend.ai_engine.llm_client import MockLLM
from backend.shared.models import Rejection, RejectionType, RetrievalHit

# ---------------------------------------------------------------------------
# Helpers — build the `user` message exactly like oa_analyzer.draft_response.
# ---------------------------------------------------------------------------


def _first_rejection(oa_text: str) -> dict:
    """Parse an OA snippet and return its first rejection dict (realistic
    examiner_argument language per jurisdiction)."""
    return json.loads(MockLLM._mock_parse_oa(oa_text))["rejections"][0]


def _draft_user_msg(rejection: dict, refs=("[GROUNDED_REF_1]", "[GROUNDED_REF_2]")) -> str:
    """Reproduce the `user` message oa_analyzer.draft_response builds:
    REJECTION json + GROUNDED_SET block listing [GROUNDED_REF_N] keys."""
    grounded_block = "\n\n".join(
        f"{r} patent=XX123 section=spec_para_1 score=0.80\n  some grounded text" for r in refs
    )
    return (
        f"REJECTION:\n{json.dumps(rejection, ensure_ascii=False, indent=2)}\n\n"
        f"GROUNDED_SET:\n{grounded_block}\n\n"
        f"ATTORNEY_HINT:\n<untrusted_input>\n(none)\n</untrusted_input>\n\n"
        "Produce the draft."
    )


def _run_draft(oa_text: str, refs=("[GROUNDED_REF_1]", "[GROUNDED_REF_2]")) -> dict:
    rej = _first_rejection(oa_text)
    user = _draft_user_msg(rej, refs)
    return json.loads(MockLLM._mock_draft(user))


def _assert_grounded_shape(draft: dict, allowed_refs: set[str]) -> None:
    """Common invariants for every jurisdiction draft."""
    cites = draft["grounded_citations"]
    assert cites, f"grounded_citations empty: {draft}"
    # Every cited [GROUNDED_REF_N] must be inside the offered grounded set.
    ref_cites = [c for c in cites if re.fullmatch(r"\[GROUNDED_REF_\d+\]", c)]
    assert ref_cites, f"no grounded ref cited: {cites}"
    for c in ref_cites:
        assert c in allowed_refs, f"cited {c} not in grounded set {allowed_refs}"
    # The cited ref must also literally appear in the draft body.
    for c in ref_cites:
        assert c in draft["draft_text"], f"{c} cited but absent from body"
    assert 0.0 < draft["confidence"] <= 1.0, draft["confidence"]


_ALLOWED = {"[GROUNDED_REF_1]", "[GROUNDED_REF_2]"}


# ---------------------------------------------------------------------------
# CN (CNIPA) — 简体 意见陈述书
# ---------------------------------------------------------------------------


def test_cn_inventive_step_draft_is_simplified_chinese():
    d = _run_draft("权利要求 1-3 不具备创造性，不符合专利法第22条第3款的规定。")
    text = d["draft_text"]
    # 简体 cues: 创造性 / 答复(意见陈述书) — and NOT 繁體 markers.
    assert "创造性" in text
    assert "意见陈述书" in text or "答复" in text
    assert "進步性" not in text and "申復書" not in text  # not 繁體 TW
    _assert_grounded_shape(d, _ALLOWED)


def test_cn_novelty_draft_argues_novelty():
    d = _run_draft("权利要求 1 不具备新颖性，不符合专利法第22条第2款的规定。")
    assert "新颖性" in d["draft_text"]
    _assert_grounded_shape(d, _ALLOWED)


# ---------------------------------------------------------------------------
# KR (KIPO) — 한글 의견서
# ---------------------------------------------------------------------------


def test_kr_inventive_step_draft_is_hangul():
    d = _run_draft(
        "청구항 1-3 은 진보성이 없으므로 특허법 제29조제2항의 규정에 의하여 거절이유를 통지합니다."
    )
    text = d["draft_text"]
    assert "진보성" in text
    assert "의견" in text  # 의견서
    _assert_grounded_shape(d, _ALLOWED)


def test_kr_novelty_draft_argues_novelty():
    d = _run_draft(
        "청구항 1 은 인용발명에 의하여 신규성이 없으므로 특허법 제29조제1항의 규정에 의하여 거절이유를 통지합니다."
    )
    assert "신규성" in d["draft_text"]
    _assert_grounded_shape(d, _ALLOWED)


# ---------------------------------------------------------------------------
# EP (EPO) — English EPC response
# ---------------------------------------------------------------------------


def test_ep_inventive_step_draft_is_english_epc():
    d = _run_draft("Claims 1-3 do not involve an inventive step within the meaning of Art. 56 EPC.")
    text = d["draft_text"]
    assert "Art." in text
    assert "inventive step" in text.lower()
    assert "EPC" in text
    _assert_grounded_shape(d, _ALLOWED)


def test_ep_novelty_draft_argues_novelty():
    d = _run_draft(
        "The subject-matter of the claims lacks novelty under Art. 54 EPC, all features disclosed in D1."
    )
    text = d["draft_text"]
    assert "novelty" in text.lower()
    assert "Art." in text
    _assert_grounded_shape(d, _ALLOWED)


# ---------------------------------------------------------------------------
# JP (JPO) — 日本語 意見書
# ---------------------------------------------------------------------------


def test_jp_inventive_step_draft_is_japanese():
    # Build a JP rejection directly (the parser focuses on TW/US/EP/CN/KR);
    # the draft router keys on 進歩性 / 拒絶理由 / 特許法第 cues.
    rej = {
        "rejection_id": "rej-1",
        "rejection_type": "103_obviousness",
        "affected_claims": [1, 2, 3],
        "cited_prior_art": ["JP2021012345"],
        "examiner_argument": (
            "審査官は、本願請求項が引用文献に基づき進歩性を欠き、"
            "特許法第29条第2項の規定により拒絶理由を通知する。"
        ),
        "confidence": 0.88,
    }
    d = json.loads(MockLLM._mock_draft(_draft_user_msg(rej)))
    text = d["draft_text"]
    assert "意見書" in text
    assert "進歩性" in text
    _assert_grounded_shape(d, _ALLOWED)


# ---------------------------------------------------------------------------
# Grounded-set membership: the cited ref tracks the offered keys
# ---------------------------------------------------------------------------


def test_cited_ref_inside_single_ref_grounded_set():
    """When the prompt offers only [GROUNDED_REF_1], the draft must cite that
    one (never a [GROUNDED_REF_2] the verifier would strip)."""
    d = _run_draft(
        "权利要求 1-3 不具备创造性，不符合专利法第22条第3款的规定。",
        refs=("[GROUNDED_REF_1]",),
    )
    _assert_grounded_shape(d, {"[GROUNDED_REF_1]"})
    assert "[GROUNDED_REF_2]" not in d["draft_text"]


# ---------------------------------------------------------------------------
# Regression: TW antecedent-basis + US/generic paths unchanged
# ---------------------------------------------------------------------------


def test_tw_antecedent_basis_draft_unchanged():
    # The antecedent-basis branch keys on "antecedent_basis"/"先行詞" and is
    # checked FIRST, so any user msg with that cue still hits the TIPO 申復書.
    user = "REJECTION: antecedent_basis 先行詞 ... GROUNDED_SET: [GROUNDED_REF_1]"
    d = json.loads(MockLLM._mock_draft(user))
    assert "申請人謹依鈞局" in d["draft_text"]
    assert "專利法第26條第2項" in d["draft_text"]
    assert "[GROUNDED_REF_1]" in d["grounded_citations"]


def test_us_generic_draft_unchanged():
    # A US §103 rejection (English "obvious", no EP/CN/KR/TW/JP cues) must fall
    # through to the generic English non-obviousness draft.
    d = _run_draft("Claims 1-5 are rejected under 35 U.S.C. § 103 as obvious over US7654321.")
    text = d["draft_text"]
    assert "Applicant respectfully traverses the rejection" in text
    assert "[GROUNDED_REF_1]" in d["grounded_citations"]
    assert "[GROUNDED_REF_2]" in d["grounded_citations"]


# ---------------------------------------------------------------------------
# END-TO-END via oa_analyzer.draft_response (mock mode)
# ---------------------------------------------------------------------------


def test_e2e_cn_draft_response_is_simplified_and_grounded():
    from backend.ai_engine import oa_analyzer

    rej_dict = _first_rejection("权利要求 1-3 不具备创造性，不符合专利法第22条第3款的规定。")
    rejection = Rejection(
        rejection_id=rej_dict["rejection_id"],
        rejection_type=RejectionType(rej_dict["rejection_type"]),
        affected_claims=rej_dict["affected_claims"],
        cited_prior_art=rej_dict["cited_prior_art"],
        examiner_argument=rej_dict["examiner_argument"],
        confidence=rej_dict["confidence"],
    )
    grounded_set = [
        RetrievalHit(
            patent_no="CN101234567",
            section="spec_para_1",
            text="本实施例中所述技术方案取得了预料不到的技术效果。",
            score=0.81,
        ),
        RetrievalHit(
            patent_no="CN101234567",
            section="claim_1",
            text="一种装置，其特征在于……",
            score=0.74,
        ),
    ]

    draft, meta = oa_analyzer.draft_response(
        rejection=rejection,
        grounded_set=grounded_set,
        user_hint=None,
        security_level="public",
    )

    # 简体 result
    assert "创造性" in draft.draft_text
    assert "意见陈述书" in draft.draft_text or "答复" in draft.draft_text
    # grounded_citations ⊆ the grounded set keys ([GROUNDED_REF_1], [GROUNDED_REF_2])
    allowed = {f"[GROUNDED_REF_{i + 1}]" for i in range(len(grounded_set))}
    ref_cites = {c for c in draft.grounded_citations if c.startswith("[GROUNDED_REF_")}
    assert ref_cites, draft.grounded_citations
    assert ref_cites <= allowed, (ref_cites, allowed)
