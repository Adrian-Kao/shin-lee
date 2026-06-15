"""§26 claim-support lint (backend/ai_engine/claim_support.py).

The lint is deterministic and honest-scoped: it flags claim terms the spec does
NOT literally contain (a strong 「請求項未為說明書支持」smell), as a REVIEW prompt,
not a legal finding. These tests pin the behaviour that matters for the UI/badge:
fully-supported claims stay clean, a claim that introduces a term the spec never
mentions gets flagged with that term, cross-reference boilerplate is ignored, and
both scripts work.
"""

from __future__ import annotations

from backend.ai_engine.claim_support import check_claim_support, support_summary

_TW_SPEC = (
    "【技術領域】本發明關於一種電動車充電管理方法。\n"
    "【發明內容】本發明的充電管理方法，由伺服器接收每個充電樁的最大可供電功率，"
    "並動態下發能源管理方案以最佳化整體供電。伺服器依據電網負載調整各充電樁的輸出。\n"
    "【實施方式】在較佳實施例中，伺服器與複數個充電樁通訊。"
)


def test_fully_supported_claim_not_flagged():
    claims = [
        "一種電動車充電管理方法，包含：由伺服器接收每個充電樁的最大可供電功率；"
        "以及動態下發能源管理方案。"
    ]
    [r] = check_claim_support(claims, _TW_SPEC, "TW")
    assert r.claim_no == 1
    assert r.is_independent is True
    assert r.flagged is False
    assert r.unsupported_fragments == []
    assert r.support_ratio >= 0.9


def test_unsupported_term_is_flagged_with_the_term():
    claims = [
        "一種電動車充電管理方法。",  # supported
        "如請求項1所述之方法，其中該能源管理方案透過區塊鏈結算進行計費。",  # 區塊鏈結算 absent
    ]
    results = check_claim_support(claims, _TW_SPEC, "TW")
    assert results[0].flagged is False
    flagged = results[1]
    assert flagged.claim_no == 2
    assert flagged.is_independent is False  # dependent claim
    assert flagged.flagged is True
    # The novel term the spec never mentions shows up in a fragment.
    joined = "".join(flagged.unsupported_fragments)
    assert "區塊鏈結算" in joined
    # Cross-reference + preamble boilerplate is NOT flagged.
    assert "請求項" not in joined
    assert "所述" not in joined


def test_cross_reference_boilerplate_does_not_flag_referenced_structure():
    # A dependent claim whose only new content IS supported should pass even
    # though it carries "如請求項1所述之方法".
    claims = [
        "一種充電管理方法。",
        "如請求項1所述之方法，其中伺服器依據電網負載調整各充電樁的輸出。",
    ]
    results = check_claim_support(claims, _TW_SPEC, "TW")
    assert results[1].flagged is False, results[1].unsupported_fragments


def test_english_claim_support():
    spec = (
        "The cooling apparatus comprises a substrate and a heat sink mounted "
        "thereon. The heat sink includes a microchannel having a non-uniform "
        "cross section."
    )
    claims = [
        "A cooling apparatus comprising a substrate and a heat sink with a microchannel.",
        "The apparatus of claim 1, wherein the microchannel contains a piezoelectric pump.",
    ]
    results = check_claim_support(claims, spec, "US")
    assert results[0].flagged is False, results[0].unsupported_fragments
    # 'piezoelectric' and 'pump' are absent from the spec.
    frags = set(results[1].unsupported_fragments)
    assert "piezoelectric" in frags
    assert "pump" in frags
    # 'claim'/'wherein'/'apparatus' boilerplate is never flagged.
    assert "claim" not in frags
    assert "apparatus" not in frags


def test_empty_spec_flags_substantive_terms():
    claims = ["一種電動車充電管理方法，包含區塊鏈結算。"]
    [r] = check_claim_support(claims, "", "TW")
    assert r.flagged is True
    # Against an empty spec only structural boilerplate (e.g. 包含) can count as
    # "supported", so the substantive support ratio is near zero.
    assert r.support_ratio < 0.2
    assert "區塊鏈結算" in "".join(r.unsupported_fragments)


def test_support_summary_rollup():
    claims = [
        "一種充電管理方法。",
        "如請求項1所述之方法，其中透過區塊鏈結算計費。",
    ]
    results = check_claim_support(claims, _TW_SPEC, "TW")
    s = support_summary(results)
    assert s["claims_total"] == 2
    assert s["claims_flagged"] == 1
    assert s["flagged_claim_nos"] == [2]
    assert s["all_supported"] is False
    assert 0.0 <= s["min_support_ratio"] <= 1.0


def test_no_claims_is_safe():
    assert check_claim_support([], _TW_SPEC, "TW") == []
    assert support_summary([])["all_supported"] is True


def test_deterministic():
    claims = ["如請求項1所述之方法，其中透過區塊鏈結算進行計費。"]
    a = check_claim_support(claims, _TW_SPEC, "TW")
    b = check_claim_support(claims, _TW_SPEC, "TW")
    assert a[0].unsupported_fragments == b[0].unsupported_fragments
    assert a[0].support_ratio == b[0].support_ratio
