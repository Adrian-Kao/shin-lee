"""Integration tests for Security Chunk C — H-6 role-gate enforcement.

Pre-fix any authenticated role could call /v1/oa/analyze, /v1/oa/upload,
and /v1/redact. The audit finding flagged that IT_ADMIN (whose POC role
description is "管理 connector、看儀表板") and AUDITOR (read-only audit
log) had no legitimate reason to run patent analysis, yet the only gates
were authn + case ACL — both of which they could pass.

Post-fix:

  * ``/v1/oa/analyze``  → ATTORNEY + PARALEGAL
  * ``/v1/oa/upload``   → ATTORNEY + PARALEGAL
  * ``/v1/redact``      → ATTORNEY + PARALEGAL
  * ``/v1/quota``       → any authenticated role (read-only dashboard)
  * ``/v1/audit/recent``→ AUDITOR + IT_ADMIN
  * ``/v1/audit/verify``→ AUDITOR + IT_ADMIN

Implementation: ``require_roles(*roles)`` in ``backend/gateway/auth.py``
returns a FastAPI dependency that wraps ``auth_dependency`` and 403s on
role mismatch. The wrap means we cannot mis-wire an endpoint that has
the role check but forgot the auth check — they're a single dependency.

Demo user roles (from ``backend/gateway/auth.py:_USERS``):
  * alice         → ATTORNEY  (tenant_a, ACL: CASE-2025-001/002/003)
  * bob           → PARALEGAL (tenant_a, ACL: CASE-2025-001/002)
  * carol         → IT_ADMIN  (tenant_b, ACL: ∅)
  * audit_dave    → AUDITOR   (tenant_a, ACL: '*')
"""
from __future__ import annotations

import pytest


_ALICE_CASE = "CASE-2025-001"   # both alice and bob have ACL
_PDF_BYTES = b"%PDF-1.4\n%%EOF"  # well-formed enough for the type gate


def _login(client, user_id: str) -> str:
    """Helper: log in as ``user_id`` using the demo password convention."""
    resp = client.post(
        "/v1/auth/login",
        json={"user_id": user_id, "password": f"demo-{user_id}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# /v1/oa/analyze — ATTORNEY + PARALEGAL allowed; IT_ADMIN + AUDITOR refused
# ---------------------------------------------------------------------------
def test_paralegal_can_analyze(gateway_client, patched_ai_engine):
    """Bob (PARALEGAL) is the demo paralegal. Paralegals assist attorneys
    in the POC workflow — they ARE allowed to run analysis on cases in
    their ACL. Test fails if the role gate accidentally excluded PARALEGAL.

    Bob's ACL includes CASE-2025-001, so a 200 here proves both the role
    gate and the case ACL passed."""
    bob_token = _login(gateway_client, "bob")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={
            "oa_text": "sample OA text for the paralegal test",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 200, resp.text


def test_it_admin_cannot_analyze(gateway_client, patched_ai_engine):
    """Carol (IT_ADMIN, tenant_b) must NOT be able to run analysis even
    on a case_id she could otherwise reach. Role gate fires BEFORE case
    ACL — we use a case that's never in any ACL so the failure mode is
    unambiguously role-driven, not ACL-driven.

    Expect 403 with a message naming the role + allowed role list."""
    carol_token = _login(gateway_client, "carol")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {carol_token}"},
        json={
            "oa_text": "any",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 403, resp.text
    body_text = resp.text.lower()
    assert "it_admin" in body_text, resp.text
    assert "attorney" in body_text or "paralegal" in body_text, resp.text


def test_auditor_cannot_analyze(gateway_client, patched_ai_engine):
    """audit_dave (AUDITOR) has tenant-wildcard ACL ('*' in _CASE_ACL),
    so case ACL alone is permissive. The role gate is what blocks them
    here — auditors are read-only on the audit chain; running analysis
    would smear the audit log with rows authored by the auditor.

    Expect 403."""
    auditor_token = _login(gateway_client, "audit_dave")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={
            "oa_text": "any",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# /v1/oa/upload — same role matrix as /v1/oa/analyze
# ---------------------------------------------------------------------------
def test_paralegal_can_upload(gateway_client, patched_ai_engine):
    """Bob (PARALEGAL) can upload — same role gate as analyze. We use a
    minimal well-formed PDF and expect 200 (or a downstream failure such
    as 415/422 from pdf_parser) — the load-bearing assertion is that the
    role gate does NOT 403."""
    bob_token = _login(gateway_client, "bob")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {bob_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("x.pdf", _PDF_BYTES, "application/pdf")},
    )
    # Role gate must NOT 403. Downstream may 400/500 because the
    # minimal PDF isn't really parseable, but that's a different concern.
    assert resp.status_code != 403, resp.text


def test_it_admin_cannot_upload(gateway_client, patched_ai_engine):
    """Carol (IT_ADMIN) is blocked at the role gate BEFORE any file
    bytes are read. This is important: a 30MB PDF from a wrong-role caller
    should not even reach the memory cap check, let alone the AI engine."""
    carol_token = _login(gateway_client, "carol")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {carol_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("x.pdf", _PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 403, resp.text


def test_auditor_cannot_upload(gateway_client, patched_ai_engine):
    """audit_dave (AUDITOR) blocked at the role gate. Belt-and-braces:
    even though the auditor's wildcard ACL would let them pass the case
    ACL, the role gate refuses."""
    auditor_token = _login(gateway_client, "audit_dave")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {auditor_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("x.pdf", _PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# /v1/quota — ANY authenticated role (dashboard is read-only)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "user_id",
    ["alice", "bob", "carol", "audit_dave"],
)
def test_any_authenticated_role_can_read_quota(gateway_client, user_id):
    """The quota / cost-dashboard endpoint is read-only and harmless —
    every role should be able to see their own daily token usage. If a
    future change locks this down to one role only, expect a flood of
    "I can't see my own quota" support tickets.

    Parameterised across all four demo roles for a complete role matrix
    in one test."""
    token = _login(gateway_client, user_id)
    resp = gateway_client.get(
        "/v1/quota",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 or 403 — 200 is the success path; 403 would be a regression.
    # Auditor / IT_admin both have empty/limited ACLs but quota is per-USER
    # so it works regardless of case access.
    assert resp.status_code == 200, (user_id, resp.text)


# ---------------------------------------------------------------------------
# /v1/audit/recent + /v1/audit/verify — AUDITOR + IT_ADMIN
# ---------------------------------------------------------------------------
def test_auditor_can_read_audit(gateway_client):
    """audit_dave (AUDITOR) is the load-bearing demo auditor — they must
    be able to read /v1/audit/recent. If this test fails, the auditor's
    primary daily workflow is broken."""
    auditor_token = _login(gateway_client, "audit_dave")
    resp = gateway_client.get(
        "/v1/audit/recent",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list), resp.json()


def test_attorney_cannot_read_audit(gateway_client):
    """Alice (ATTORNEY) is blocked from /v1/audit/recent — the audit log
    is auditor / IT_admin territory only. Without this gate any attorney
    could read every other attorney's case activity in the tenant."""
    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.get(
        "/v1/audit/recent",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 403, resp.text


def test_auditor_can_verify_chain(gateway_client):
    """audit_dave can verify the per-tenant hash chain. Same gate as
    /v1/audit/recent — the two endpoints share the auditor / it_admin
    whitelist in the handler."""
    auditor_token = _login(gateway_client, "audit_dave")
    resp = gateway_client.get(
        "/v1/audit/verify",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 200, resp.text
