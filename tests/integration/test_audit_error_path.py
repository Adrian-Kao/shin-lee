"""Integration tests for the H-7 audit-on-error fix.

Invariant #4 in CLAUDE.md §4 says:

  > Every gateway request writes exactly one audit row. Even cache hits.
  > Even errors (TODO).

Pre-fix the cache-hit path explicitly wrote an audit row, but the error
paths (403 ACL, 429 RPM, 5xx orchestrator exception, 413 upload size)
raised HTTPException before reaching the audit.write call — so the rows
were silently lost. The audit log therefore under-counted blocked / failed
requests, which is exactly the data the auditor needs to spot abuse.

Post-fix the gateway endpoints wrap their handler bodies in a try/finally
so the audit row is written even on error. The row carries
``policy_decisions["error"] == True`` so the auditor can filter them.

This module covers the four most-load-bearing error paths plus a
safety-net test for the audit writer itself failing.
"""

from __future__ import annotations

import pytest

_FOREIGN_CASE = "CASE-DEMO-099"  # alice has no ACL on this
_ALICE_CASE = "CASE-2025-001"  # alice has ACL


def _login_auditor(client) -> str:
    """audit_dave is tenant_a like alice — so /v1/audit/recent surfaces
    alice's rows including the error rows we want to assert on."""
    return client.post(
        "/v1/auth/login",
        json={"user_id": "audit_dave", "password": "demo-audit_dave"},
    ).json()["token"]


def _recent_rows(client, auditor_token: str, limit: int = 200) -> list[dict]:
    resp = client.get(
        "/v1/audit/recent",
        params={"limit": limit},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. 403 ACL: the C-3 bypass attempt MUST still write one audit row so a
#    series of probing requests shows up in the auditor view.
# ---------------------------------------------------------------------------
def test_analyze_403_writes_audit_row_with_error_flag(
    gateway_client, alice_token, patched_ai_engine
):
    """Foreign case_id → 403 → /v1/audit/recent must show a row tagged
    with policy_decisions.error=True and policy_decisions.authz_passed=False
    so the auditor can grep for bypass attempts."""
    auditor_token = _login_auditor(gateway_client)
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "x",
            "case_id": _FOREIGN_CASE,
            "target_patent_no": "p",
        },
    )
    assert resp.status_code == 403, resp.text

    rows_after = _recent_rows(gateway_client, auditor_token)
    assert len(rows_after) == rows_before + 1, (rows_before, len(rows_after))
    row = rows_after[0]  # most-recent-first
    assert row["user_id"] == "alice", row
    assert row["endpoint"] == "/v1/oa/analyze", row
    assert row["case_id"] == _FOREIGN_CASE, row
    pd = row["policy_decisions"]
    assert pd.get("error") is True, pd
    assert pd.get("authz_passed") is False, pd
    # authn_passed should remain True — the JWT was valid; only ACL refused.
    assert pd.get("authn_passed") is True, pd


# ---------------------------------------------------------------------------
# 2. 429 RPM: exhausting the per-user RPM bucket must still produce an
#    audit row for the rejected request.
# ---------------------------------------------------------------------------
def test_analyze_rate_limit_exceeded_writes_audit_row(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """Pin DEFAULT_RPM=1. The first request consumes the token (200), the
    second hits the empty bucket (429). The 429 must still write an audit
    row — pre-fix it silently disappeared."""
    from backend.shared import config as cfg

    monkeypatch.setattr(cfg.settings, "DEFAULT_RPM", 1)
    auditor_token = _login_auditor(gateway_client)
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    payload = {
        "oa_text": "Some OA text for RPM test.",
        "case_id": _ALICE_CASE,
        "target_patent_no": "US17000002",
    }
    r1 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    assert r1.status_code == 200, r1.text

    r2 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    assert r2.status_code == 429, r2.text

    rows_after = _recent_rows(gateway_client, auditor_token)
    # Two new rows: the 200 and the 429.
    assert len(rows_after) == rows_before + 2, (rows_before, len(rows_after))
    # Most-recent first → the 429 row is index 0.
    err_row = rows_after[0]
    assert err_row["endpoint"] == "/v1/oa/analyze", err_row
    pd = err_row["policy_decisions"]
    assert pd.get("error") is True, pd
    assert pd.get("authz_passed") is True, pd  # ACL passed
    assert pd.get("rate_limit_passed") is False, pd  # this is the failure


# ---------------------------------------------------------------------------
# 3. Orchestrator exception: any 5xx-class failure inside the orchestrator
#    must still leave an audit row.
# ---------------------------------------------------------------------------
def test_analyze_orchestrate_exception_writes_audit_row(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """Monkey-patch ``orchestrate_analysis`` to raise. The handler should
    propagate the exception (so the client sees the failure) AND still
    write an audit row tagged with policy_decisions.error=True."""
    from backend.gateway import main as gw_main

    async def _boom(_user, _body, **_kwargs):
        raise RuntimeError("orchestrator simulated crash")

    monkeypatch.setattr(gw_main, "orchestrate_analysis", _boom)

    auditor_token = _login_auditor(gateway_client)
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    # Starlette's TestClient re-raises the unhandled exception out of the
    # client call rather than surfacing it as 500 — production has
    # ASGI-level exception handlers that would render 500, but for the
    # purpose of this test the important property is that the audit row is
    # written DESPITE the crash. We catch the re-raise so we can still
    # assert on the audit-recent endpoint.
    with pytest.raises(RuntimeError, match="orchestrator simulated crash"):
        gateway_client.post(
            "/v1/oa/analyze",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "oa_text": "OA text for orchestrator-crash test.",
                "case_id": _ALICE_CASE,
                "target_patent_no": "US17000003",
            },
        )

    rows_after = _recent_rows(gateway_client, auditor_token)
    assert len(rows_after) == rows_before + 1, (rows_before, len(rows_after))
    row = rows_after[0]
    assert row["endpoint"] == "/v1/oa/analyze", row
    pd = row["policy_decisions"]
    assert pd.get("error") is True, pd
    # All the pre-orchestrate gates passed — only the orchestrate call itself failed.
    assert pd.get("authz_passed") is True, pd
    assert pd.get("rate_limit_passed") is True, pd
    assert pd.get("quota_passed") is True, pd


# ---------------------------------------------------------------------------
# 4. /v1/oa/upload 413 — the size-cap rejection must also write a row.
# ---------------------------------------------------------------------------
def test_upload_size_413_writes_audit_row(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    from backend.shared import config as cfg

    monkeypatch.setattr(cfg.settings, "MAX_UPLOAD_MB", 1)
    auditor_token = _login_auditor(gateway_client)
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    big_bytes = b"%PDF-1.4\n" + (b"A" * (2 * 1024 * 1024))
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("big.pdf", big_bytes, "application/pdf")},
    )
    assert resp.status_code == 413, resp.text

    rows_after = _recent_rows(gateway_client, auditor_token)
    assert len(rows_after) == rows_before + 1, (rows_before, len(rows_after))
    row = rows_after[0]
    assert row["endpoint"] == "/v1/oa/upload", row
    pd = row["policy_decisions"]
    assert pd.get("error") is True, pd
    assert pd.get("upload_size_passed") is False, pd
    # authz_passed should be True — header carried a valid case_id.
    assert pd.get("authz_passed") is True, pd


# ---------------------------------------------------------------------------
# 5. Audit writer failure must NOT mask the real error / response.
# ---------------------------------------------------------------------------
def test_audit_writer_failure_does_not_mask_response_error(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """If the audit DB itself is broken (disk full, file locked, etc.) the
    finally-block must SWALLOW the writer exception — never let it mask
    the genuine 403/500 the user is about to see. Failing audit writes are
    logged for ops to alert on, but the response surface is unchanged.

    We test against a 403 path (ACL foreign case) because (a) it's the
    simplest deterministic error to trigger, and (b) it exercises the
    code path that pre-fix didn't write an audit row at all — so a buggy
    finally that propagated the writer error would now produce a 500
    instead of the expected 403."""
    from backend.gateway import audit as audit_mod

    original_write = audit_mod.writer.write
    call_count = {"n": 0}

    def _failing_write(**kwargs):
        call_count["n"] += 1
        raise RuntimeError("simulated audit DB outage")

    monkeypatch.setattr(audit_mod.writer, "write", _failing_write)

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "x",
            "case_id": _FOREIGN_CASE,
            "target_patent_no": "p",
        },
    )
    # Pre-fix: 403 with no audit row.
    # Post-fix with bad audit: STILL 403; the writer crash is swallowed and logged.
    assert resp.status_code == 403, resp.text
    # The finally block must have actually called the writer (even though it failed).
    assert call_count["n"] >= 1, "audit writer was never invoked on the 403 path"

    # Restore so subsequent tests don't see the crippled writer.
    monkeypatch.setattr(audit_mod.writer, "write", original_write)
