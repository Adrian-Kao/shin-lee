"""Q14 second-stage verifier — unit tests.

CLAUDE.md §4 invariant #5 ("Citations in drafts MUST come from the grounded
set; verify_citations is the hard wall") + §9 ("Don't skip the verifier").

Two concerns are covered here:

  1. `MockLLM._mock_verify` is now a REAL deterministic check, not a canned
     rubber stamp. It parses the grounded keys + the draft body out of the
     verifier `user` message and independently re-checks every citation.

  2. Verifier-model independence (Q14 FU + config invariant): on the PUBLIC
     path `route_model(intent="verify_citations")` must return the dedicated
     LLM_MODEL_VERIFIER, and that must differ from the reasoning model used by
     parse_oa / draft_response. (Confidential routes everything local — that is
     expected and is NOT what we assert here.)
"""
from __future__ import annotations

import json

from backend.ai_engine.llm_client import MockLLM, route_model
from backend.shared.config import settings


# The verifier `user` message shape is built by oa_analyzer.verify_citations:
#
#     DRAFT:
#     <untrusted_input>
#     ...cleaned draft...
#     </untrusted_input>
#
#     GROUNDED_SET keys: ['[GROUNDED_REF_1]', '[GROUNDED_REF_2]']
#
#     Confirm cleaned draft only references the keys above.
def _build_verifier_msg(draft_text: str, grounded_keys: list[str]) -> str:
    return (
        f"DRAFT:\n<untrusted_input>\n{draft_text}\n</untrusted_input>\n\n"
        f"GROUNDED_SET keys: {grounded_keys}\n\n"
        "Confirm cleaned draft only references the keys above."
    )


def _verify(draft_text: str, grounded_keys: list[str]) -> dict:
    msg = _build_verifier_msg(draft_text, grounded_keys)
    return json.loads(MockLLM._mock_verify(msg))


def test_flags_ungrounded_grounded_ref_slot():
    """A draft citing [GROUNDED_REF_99] — a slot that was never retrieved — is
    flagged invalid even though it *looks* like a legitimate grounded token."""
    res = _verify(
        "Per [GROUNDED_REF_1] the channels differ. See also [GROUNDED_REF_99].",
        ["[GROUNDED_REF_1]", "[GROUNDED_REF_2]"],
    )
    assert "[GROUNDED_REF_99]" in res["invalid_citations"]
    assert "[GROUNDED_REF_1]" in res["valid_citations"]
    assert res["valid"] is False


def test_passes_draft_citing_only_listed_keys():
    """The legit demo draft cites GROUNDED_REF_1/2, both grounded → clean."""
    res = _verify(
        "See Patent No. [GROUNDED_REF_1]. The cited [GROUNDED_REF_2] teaches away.",
        ["[GROUNDED_REF_1]", "[GROUNDED_REF_2]"],
    )
    assert res["valid"] is True
    assert res["invalid_citations"] == []
    assert "[GROUNDED_REF_1]" in res["valid_citations"]
    assert "[GROUNDED_REF_2]" in res["valid_citations"]


def test_allows_statute_refs_not_in_grounded_set():
    """Statute refs (專利法第N條 / 35 U.S.C. § N) come from the OA and are
    publicly verifiable — allowed even though they are not grounded keys."""
    res = _verify(
        "These conclusions follow under 專利法第26條第2項 and 35 U.S.C. § 103.",
        ["[GROUNDED_REF_1]"],
    )
    assert res["valid"] is True
    assert res["invalid_citations"] == []
    assert "專利法第26條第2項" in res["valid_citations"]
    assert any("103" in c for c in res["valid_citations"])


def test_confidence_drops_when_invalids_present():
    clean = _verify("Only [GROUNDED_REF_1] is cited.", ["[GROUNDED_REF_1]"])
    dirty = _verify(
        "Cites [GROUNDED_REF_1], [GROUNDED_REF_98] and [GROUNDED_REF_99].",
        ["[GROUNDED_REF_1]"],
    )
    assert clean["verifier_confidence"] > dirty["verifier_confidence"]
    # More fabrications → strictly lower confidence (monotonic penalty).
    one_bad = _verify(
        "Cites [GROUNDED_REF_1] and [GROUNDED_REF_99].", ["[GROUNDED_REF_1]"]
    )
    assert dirty["verifier_confidence"] < one_bad["verifier_confidence"]


def test_ungrounded_external_patent_is_flagged():
    res = _verify(
        "Applicant distinguishes US9999999, never retrieved.", ["[GROUNDED_REF_1]"]
    )
    assert any("9999999" in c for c in res["invalid_citations"])
    assert res["valid"] is False


def test_empty_grounded_keys_treats_grounded_ref_as_ungrounded():
    """Conservative direction: with no listed keys, any GROUNDED_REF is suspect."""
    res = _verify("Per [GROUNDED_REF_1] the channels differ.", [])
    assert "[GROUNDED_REF_1]" in res["invalid_citations"]
    assert res["valid"] is False


# ---------------------------------------------------------------------------
# Verifier-model independence (Q14 FU)
# ---------------------------------------------------------------------------

def test_verifier_model_differs_from_reasoning_on_public_path():
    verifier_model = route_model(
        intent="verify_citations", security_level="public", circuit_open=False
    )
    parse_model = route_model(
        intent="parse_oa", security_level="public", circuit_open=False
    )
    draft_model = route_model(
        intent="draft_response", security_level="public", circuit_open=False
    )

    # The verifier must be the dedicated, independent verifier model...
    assert verifier_model == settings.LLM_MODEL_VERIFIER
    # ...and the reasoning intents must use the (different) reasoning model.
    assert parse_model == settings.LLM_MODEL_REASONING
    assert draft_model == settings.LLM_MODEL_REASONING
    # Independence: a second opinion from the SAME model is no opinion at all.
    assert verifier_model != parse_model
    assert verifier_model != draft_model
    assert settings.LLM_MODEL_VERIFIER != settings.LLM_MODEL_REASONING
