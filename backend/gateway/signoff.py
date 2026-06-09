"""Q16 — human-in-the-loop sign-off helpers (responsibility boundary).

The Q16 decision (docs/DECISIONS.md, docs/QUESTIONS.md §Q16) requires more
than a lone ``DraftResponse.requires_attorney_review`` boolean. It requires:

  * a real RESPONSIBILITY BOUNDARY — the system records which sentences are
    AI-generated, which the attorney rewrote, and which the attorney added;
  * a HARD EXPORT GATE — the attorney must tick "我已逐項確認" (a checkbox
    mapped to ``ExportRequest.attorney_signoff``) before any document is
    produced. Not ticked → no document.

This module holds the pure (no-FastAPI, no-DB) building blocks the
``/v1/oa/export`` handler in ``main.py`` composes:

  * ``assemble_document``  — concatenate the ACCEPTED segments in order.
  * ``summarise_provenance`` — count segments by source (the responsibility
    boundary, distilled to integers for the audit row).
  * ``content_hash``       — SHA-256 of the assembled document, so the audit
    row can prove WHICH document was signed off WITHOUT storing the raw text
    (CLAUDE.md §9: don't put raw draft text in the hash-chained log).

Keeping these here (rather than inline in the handler) makes them unit-testable
and keeps the handler focused on the policy gates (auth, role, ACL, signoff).
"""
from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import HTTPException, status

from backend.shared.models import ProvenanceSegment, ProvenanceSummary, User, UserRole

# ---------------------------------------------------------------------------
# Agent F (Day 13F) — sign-off authority is an ATTORNEY act.
#
# The /v1/oa/export route already role-gates the ENDPOINT to ATTORNEY via
# require_roles(UserRole.ATTORNEY). This helper makes the authority an explicit,
# unit-testable function so (a) any future caller (batch export, e-signature
# webhook) can reuse the SAME rule rather than re-deriving it, and (b) the
# decision is auditable in isolation. Defence-in-depth: even if a future
# refactor loosened the endpoint gate, this check still refuses a non-attorney
# sign-off.
# ---------------------------------------------------------------------------
SIGNOFF_AUTHORITY_ROLES: frozenset[UserRole] = frozenset({UserRole.ATTORNEY})


def assert_signoff_authority(user: User) -> None:
    """Raise 403 unless ``user`` holds a role permitted to sign off an export.

    Q16 responsibility boundary: the legal accountability for the final filed
    document rests with a licensed ATTORNEY. Paralegals assist with analysis but
    cannot sign. AUDITOR / IT_ADMIN have no role in drafting at all.
    """
    if user.role not in SIGNOFF_AUTHORITY_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Role '{user.role.value}' may not sign off an export. "
            f"Sign-off authority: {sorted(r.value for r in SIGNOFF_AUTHORITY_ROLES)}.",
        )


def signoff_audit_fields(user: User, signed_off: bool) -> dict:
    """Return the audit-row fields that record WHO exercised sign-off authority.

    Pure (no I/O) so the export handler can splice these into its single audit
    row. ``signed_off`` is the outcome (True only when the hard gate passed).
    """
    return {
        "signoff_authority_role": user.role.value,
        "signoff_by": user.user_id,
        "signoff_passed": bool(signed_off),
    }

# Separator used when concatenating accepted segments into the final document.
# A blank line between segments keeps paragraph boundaries readable and is
# stable so ``content_hash`` is deterministic for a given set of segments.
_SEGMENT_JOINER = "\n\n"


def assemble_document(segments: list[ProvenanceSegment]) -> str:
    """Concatenate the ACCEPTED segments, in supplied order, into one document.

    Rejected segments (``accepted is False``) are dropped — the attorney
    declined that sentence, so it must not appear in the exported response.
    The order of ``segments`` is preserved (the front-end supplies them in
    document order).
    """
    return _SEGMENT_JOINER.join(s.text for s in segments if s.accepted)


def summarise_provenance(segments: list[ProvenanceSegment]) -> ProvenanceSummary:
    """Distil the per-segment provenance into aggregate counts.

    Counts cover ALL supplied segments (accepted or not) by source, plus the
    total and accepted totals. This is the responsibility boundary the audit
    row records — and the ``attorney_edited`` / ``attorney_added`` counts double
    as the lightweight feedback signal Q16 asks for (high edit ratios flag
    where the AI draft was weakest, mineable by a future training loop).
    """
    summary = ProvenanceSummary()
    summary.total_segments = len(segments)
    for seg in segments:
        if seg.accepted:
            summary.accepted_segments += 1
        if seg.source == "ai_generated":
            summary.ai_generated += 1
        elif seg.source == "attorney_edited":
            summary.attorney_edited += 1
        elif seg.source == "attorney_added":
            summary.attorney_added += 1
        elif seg.source == "paralegal_edited":
            summary.paralegal_edited += 1
        elif seg.source == "paralegal_added":
            summary.paralegal_added += 1
    return summary


def content_hash(document: str) -> str:
    """SHA-256 hex digest of the assembled document.

    Stored in the audit row in place of the raw text so an auditor can later
    prove WHICH document the attorney signed off (re-hash a stored copy and
    compare) without the privileged draft content ever entering the audit DB.
    """
    return hashlib.sha256(document.encode("utf-8")).hexdigest()
