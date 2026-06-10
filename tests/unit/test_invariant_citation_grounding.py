"""Invariant #5 (CLAUDE.md §4): citations in drafts MUST come from the grounded
set. `verify_citations` is the hard wall — it strips, via regex, any citation
that is neither a valid GROUNDED_REF slot nor a whitelisted statute, BEFORE the
verifier LLM runs (so the wall holds even if the verifier is compromised by an
injected prompt). These tests exercise the stripping logic directly.
"""
from backend.ai_engine import oa_analyzer
from backend.shared.models import DraftResponse, RetrievalHit


def _draft(text: str) -> DraftResponse:
    return DraftResponse(
        rejection_id="R1",
        strategy="strategy",
        draft_text=text,
        grounded_citations=[],
        confidence=0.9,
    )


def test_ungrounded_citations_are_stripped_grounded_ones_survive():
    grounded = [
        RetrievalHit(patent_no="US7654321", section="claim_1",
                     text="microchannel with non-uniform cross-section", score=0.9),
    ]
    draft = _draft(
        "Per [GROUNDED_REF_1] the channels differ in cross-section. "
        "The examiner relies on [GROUNDED_REF_9], a slot that does not exist. "
        "Applicant further distinguishes US9999999, which was never retrieved. "
        "These conclusions follow under 專利法第26條第2項 and 35 U.S.C. § 103."
    )

    result, _meta = oa_analyzer.verify_citations(draft, grounded)

    # Grounded slot + both statutes are kept.
    assert "[GROUNDED_REF_1]" in result["valid_citations"]
    assert "專利法第26條第2項" in result["valid_citations"]
    assert any("103" in c for c in result["valid_citations"])

    # Non-existent slot + ungrounded external patent are rejected.
    assert "[GROUNDED_REF_9]" in result["invalid_citations"]
    assert any("9999999" in c for c in result["invalid_citations"])

    # The hard wall: invalid citations are scrubbed from the returned text;
    # grounded ones remain verbatim.
    cleaned = result["cleaned_draft_text"]
    assert "[GROUNDED_REF_9]" not in cleaned
    assert "US9999999" not in cleaned
    assert "[CITATION_REMOVED]" in cleaned
    assert "[GROUNDED_REF_1]" in cleaned
    assert "專利法第26條第2項" in cleaned

    # Overall verdict reflects that ungrounded citations were present.
    assert result["valid"] is False


def test_fully_grounded_draft_passes_clean():
    grounded = [
        RetrievalHit(patent_no="US7654321", section="claim_1", text="x", score=0.9),
    ]
    draft = _draft("Only [GROUNDED_REF_1] and 35 U.S.C. § 103 are cited here.")

    result, _meta = oa_analyzer.verify_citations(draft, grounded)

    assert result["invalid_citations"] == []
    assert result["valid"] is True
    assert "[CITATION_REMOVED]" not in result["cleaned_draft_text"]
