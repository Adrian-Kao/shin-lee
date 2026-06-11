"""Integration tests for the C-3 ACL-bypass fix.

Pre-fix behaviour: ``auth_dependency`` tried to peek at ``request.state.
_cached_body`` to pick up a body-supplied ``case_id`` when the X-Case-Id
header was missing. That attribute was NEVER set anywhere in the codebase
(``grep -r _cached_body`` returned only the read site), so JSON POSTs that
omitted the header but carried a foreign ``case_id`` in the body silently
bypassed ACL. The frontend always sends the header, but a malicious client
doesn't have to.

Post-fix behaviour:

  * The dependency only consults the X-Case-Id header / ?case_id= query
    string. It NEVER reads the body.
  * Each JSON POST handler that takes a ``case_id`` in its body re-invokes
    ``authorize_case_access(user, body.case_id)`` explicitly after Pydantic
    has parsed the request.
  * When BOTH the X-Case-Id header and the body ``case_id`` are present the
    handler rejects mismatches with 400 (confused-deputy guard).
  * The ACL check runs BEFORE rate-limit / quota work so a 403 doesn't burn
    the user's RPM token.

These tests guard those properties. If any of them goes red the security
hardening for C-3 has regressed.
"""

from __future__ import annotations

# Cases alice does NOT have ACL on. Both are valid case_id strings — the
# point is that they're outside ``_CASE_ACL["alice"]``.
_FOREIGN_CASE = "CASE-DEMO-099"
_ALICE_CASE = "CASE-2025-001"


# ---------------------------------------------------------------------------
# 1. /v1/oa/analyze
# ---------------------------------------------------------------------------
def test_analyze_with_only_body_case_id_for_foreign_case_returns_403(
    gateway_client, alice_token, patched_ai_engine
):
    """The headline C-3 regression test.

    Pre-fix this returned 200 because auth_dependency saw no X-Case-Id, looked
    at the non-existent ``_cached_body`` attribute, and concluded ``case_id is
    None`` — which ``authorize_case_access`` treats as "endpoint doesn't need
    a case" and lets through. Post-fix the handler does an explicit re-check
    on body.case_id and surfaces 403."""
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "irrelevant body",
            "case_id": _FOREIGN_CASE,
            "target_patent_no": "US17000000",
        },
    )
    assert resp.status_code == 403, resp.text
    assert _FOREIGN_CASE in resp.text or "no access" in resp.text.lower(), resp.text


def test_analyze_with_header_and_body_case_id_mismatch_is_rejected_400(
    gateway_client, alice_token, patched_ai_engine
):
    """Confused-deputy guard: when both an X-Case-Id header AND a body
    case_id are present they must agree. Mismatch → 400 (NOT 403). This
    blocks an attacker from showing one case_id to an upstream header-based
    ACL while running orchestration against another.

    We deliberately use two cases that alice DOES have ACL on, so an ACL
    failure can't mask the mismatch failure."""
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-001",
        },
        json={
            "oa_text": "irrelevant body",
            "case_id": "CASE-2025-002",  # alice has ACL on both
            "target_patent_no": "US17000000",
        },
    )
    assert resp.status_code == 400, resp.text
    body_text = resp.text.lower()
    assert "case_id" in body_text and "mismatch" in body_text, resp.text


def test_analyze_with_matching_header_and_body_case_id_succeeds(
    gateway_client, alice_token, patched_ai_engine
):
    """Sanity counter-test for the mismatch guard: when both are present
    AND equal, the request runs normally (200). Without this the previous
    test could be satisfied by an over-broad guard that 400s on every
    request with both fields set — which would break the SPA."""
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": "Some OA text for matching-case sanity check.",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US17000001",
        },
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 2. /v1/oa/upload — multipart body so no JSON ``case_id`` field exists.
#     The endpoint requires X-Case-Id. We assert that a foreign case_id is
#     rejected before the file body is read.
# ---------------------------------------------------------------------------
def test_upload_with_only_body_case_id_for_foreign_case_returns_403(
    gateway_client, alice_token, patched_ai_engine
):
    """/v1/oa/upload reads case_id from the X-Case-Id header only (the body
    is a multipart stream with no JSON case_id field). Sending a foreign
    case_id in the header must 403. This is the upload-side mirror of the
    /v1/oa/analyze ACL bypass test — it asserts the same authorize_case_access
    re-check is wired through the upload handler."""
    pdf_bytes = b"%PDF-1.4\n%%EOF"  # well-formed enough for the type gate
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _FOREIGN_CASE,
        },
        files={"file": ("x.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 403, resp.text
    assert _FOREIGN_CASE in resp.text or "no access" in resp.text.lower(), resp.text


# ---------------------------------------------------------------------------
# 3. /v1/redact — header-only endpoint; foreign case_id must 403.
# ---------------------------------------------------------------------------
def test_redact_with_foreign_case_id_returns_403(gateway_client, alice_token):
    """/v1/redact accepts case_id via X-Case-Id only. The endpoint now
    re-checks ``authorize_case_access`` after the header parse — pre-fix
    this happened in auth_dependency, but the dependency check is the only
    one left now that ``_cached_body`` was removed, so we need to be sure
    the redact path still 403s on foreign cases."""
    resp = gateway_client.post(
        "/v1/redact",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _FOREIGN_CASE,
        },
        json={"text": "alice@apex-ip.com"},
    )
    assert resp.status_code == 403, resp.text
    assert _FOREIGN_CASE in resp.text or "no access" in resp.text.lower(), resp.text


# ---------------------------------------------------------------------------
# 4. ACL must run BEFORE rate-limit — a 403 attempt should NOT burn a token.
# ---------------------------------------------------------------------------
def test_acl_check_runs_before_rate_limit(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """If ACL ran AFTER rate-limit, an attacker probing case_ids would burn
    one RPM token per probe and could DoS the legitimate user. Verify the
    order by setting DEFAULT_RPM=1, sending one foreign-case request (403,
    must NOT consume the token), then sending one valid-case request (200,
    must succeed because the token is still there)."""
    from backend.shared import config as cfg

    monkeypatch.setattr(cfg.settings, "DEFAULT_RPM", 1)

    # 1) Foreign case_id → 403; this must NOT consume the bucket token.
    r1 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "x",
            "case_id": _FOREIGN_CASE,
            "target_patent_no": "p",
        },
    )
    assert r1.status_code == 403, r1.text

    # 2) Legitimate case_id → 200; the RPM bucket must still have its token.
    r2 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "x",
            "case_id": _ALICE_CASE,
            "target_patent_no": "p",
        },
    )
    assert r2.status_code == 200, (r1.text, r2.text)
