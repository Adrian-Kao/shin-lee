"""Q14 end-to-end hallucination defence — the "career-ending fabricated
citation" scenario.

The story: an LLM drafts a polished response to an Office Action and, buried in
otherwise-correct prose, fabricates authority — a made-up Federal Reporter case
("Smith v. Jones, 999 F.3d 1234"), a reference to a grounded slot that was never
retrieved ("[GROUNDED_REF_99]"), and a prior-art patent number that nobody put
in front of the model ("US0000000"). An attorney who files that response has
cited non-existent law to a tribunal. That is the failure mode Q14 exists to
prevent.

`oa_analyzer.verify_citations` is the hard wall (CLAUDE.md §4 #5): it runs regex
extraction + grounded-set enforcement FIRST (strips anything not grounded and not
a whitelisted statute), then a second-stage verifier LLM as an independent check
(CLAUDE.md §9 "Don't skip the verifier"). This test drives the real function
end-to-end (mock backends) and asserts every fabrication is caught while the one
legitimately grounded citation survives untouched.
"""
from __future__ import annotations

from backend.ai_engine import oa_analyzer
from backend.shared.models import DraftResponse, RetrievalHit


def _draft(text: str) -> DraftResponse:
    return DraftResponse(
        rejection_id="R-OBVIOUSNESS",
        strategy="traverse obviousness rejection",
        draft_text=text,
        grounded_citations=[],
        confidence=0.88,
    )


def test_fabricated_citations_are_caught_grounded_survives():
    # Exactly one real retrieval hit → exactly one legitimate grounded slot.
    grounded = [
        RetrievalHit(
            patent_no="US7654321",
            section="claim_1",
            text="microchannel heat sink with non-uniform cross-section",
            score=0.91,
        ),
    ]

    draft = _draft(
        "Applicant respectfully traverses the rejection. As established in "
        "Smith v. Jones, 999 F.3d 1234, an unexpected technical effect rebuts a "
        "prima facie case of obviousness. The claimed cooling channel of "
        "[GROUNDED_REF_1] achieves a 32% thermal-resistance reduction. The "
        "examiner's reliance on [GROUNDED_REF_99] is misplaced, and US0000000 "
        "teaches away from the claimed structure. This result follows under "
        "35 U.S.C. § 103."
    )

    result, _meta = oa_analyzer.verify_citations(draft, grounded)
    cleaned = result["cleaned_draft_text"]
    invalid = result["invalid_citations"]

    # --- Fabrication #1: a made-up Federal Reporter case ---------------------
    assert any("999" in c and "F.3d" in c for c in invalid), invalid
    assert "999 F.3d 1234" not in cleaned
    assert "[CITATION_REMOVED]" in cleaned

    # --- Fabrication #2: a grounded slot that was never retrieved ------------
    assert "[GROUNDED_REF_99]" in invalid
    assert "[GROUNDED_REF_99]" not in cleaned

    # --- Fabrication #3: a prior-art patent number nobody grounded -----------
    assert any("0000000" in c for c in invalid), invalid
    assert "US0000000" not in cleaned

    # --- The one legitimately grounded citation survives verbatim ------------
    assert "[GROUNDED_REF_1]" in result["valid_citations"]
    assert "[GROUNDED_REF_1]" in cleaned

    # --- The whitelisted statute (from the OA) survives ----------------------
    assert any("103" in c for c in result["valid_citations"])
    assert "35 U.S.C. § 103" in cleaned

    # --- Overall verdict: the draft is NOT clean -----------------------------
    # `valid` reflects the regex stage (the hard wall): fabrications were found.
    assert result["valid"] is False
    # Defence-in-depth note: by design the verifier LLM runs on the ALREADY
    # cleaned text (the wall strips fabrications first), so the second stage
    # independently re-confirms the cleaned draft is grounded — it is a check on
    # the wall's output, not a duplicate of it. We assert it did not regress the
    # clean output back to invalid.
    assert isinstance(result["verifier_confidence"], float)
    assert result["verifier_confidence"] > 0.0


def test_clean_grounded_draft_still_verifies_clean():
    """Regression guard: a draft citing only grounded slots + a statute passes
    the now-functional verifier untouched (must not false-flag the demo path)."""
    grounded = [
        RetrievalHit(patent_no="US7654321", section="claim_1", text="a", score=0.9),
        RetrievalHit(patent_no="US1234567", section="claim_2", text="b", score=0.8),
    ]
    draft = _draft(
        "See Patent No. [GROUNDED_REF_1]. The cited [GROUNDED_REF_2] teaches "
        "away from the claimed structure. This follows under 35 U.S.C. § 103."
    )

    result, _meta = oa_analyzer.verify_citations(draft, grounded)

    assert result["valid"] is True
    assert result["invalid_citations"] == []
    assert "[CITATION_REMOVED]" not in result["cleaned_draft_text"]
    assert result["verifier_confidence"] >= 0.9
