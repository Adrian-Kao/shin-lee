"""Tests for the digiRunner-compatibility HTTP endpoints (Compat Refactor 2).

These cover the two endpoints that digiRunner plugins/hooks will call out of
process (so the gateway can no longer rely on in-process orchestrator calls):

    - POST /v1/redact            — first-class redaction (pre-LLM transform)
    - POST /v1/debug/redaction_preview — deprecated alias of /v1/redact
    - POST /v1/audit/append      — append one audit row from a post-LLM hook

All tests reuse the shared `gateway_client` + `alice_token` fixtures from
`tests/conftest.py`.
"""
from __future__ import annotations


_ALICE_CASE = "CASE-2025-001"   # Alice has ACL for this case (see auth._CASE_ACL)


# ---------------------------------------------------------------------------
# /v1/redact (first-class)
# ---------------------------------------------------------------------------
def test_redact_endpoint_first_class(gateway_client, alice_token):
    """POST /v1/redact returns 200 + the expected shape (`redacted`,
    `rules_triggered`) for a body containing an email — which the email rule
    in PII_RULES is guaranteed to catch."""
    resp = gateway_client.post(
        "/v1/redact",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": "Please contact alice@apex-ip.com about the OA."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "redacted" in body, body
    assert "rules_triggered" in body, body
    assert isinstance(body["rules_triggered"], list), body
    # email regex should fire — redacted text must not contain the literal email
    assert "alice@apex-ip.com" not in body["redacted"], body


# ---------------------------------------------------------------------------
# /v1/debug/redaction_preview (deprecated alias)
# ---------------------------------------------------------------------------
def test_redact_legacy_debug_alias_still_works(gateway_client, alice_token):
    """The legacy alias must keep working — the frontend (Analyze.jsx via
    api.redactionPreview, and OAUpload.jsx indirectly) depends on this path."""
    resp = gateway_client.post(
        "/v1/debug/redaction_preview",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": "Contact alice@apex-ip.com please."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Same shape as /v1/redact
    assert "redacted" in body, body
    assert "rules_triggered" in body, body


def test_redact_legacy_debug_sets_deprecation_header(gateway_client, alice_token):
    """RFC 9745-compliant Deprecation header — Structured-Field Date format
    (`@<unix-timestamp>`) so API clients can flag in dashboards / alerts.
    Pairs with a Sunset header (RFC 8594) giving the planned removal date."""
    resp = gateway_client.post(
        "/v1/debug/redaction_preview",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": "hello"},
    )
    assert resp.status_code == 200, resp.text
    headers = {k.lower(): v for k, v in resp.headers.items()}
    # Deprecation must be a structured-field Date: '@<unix-seconds>'.
    assert "deprecation" in headers, dict(resp.headers)
    assert headers["deprecation"].startswith("@"), headers["deprecation"]
    assert headers["deprecation"][1:].isdigit(), headers["deprecation"]
    # Sunset paired so callers know the planned removal date (RFC 8594).
    assert "sunset" in headers, dict(resp.headers)
    # Link header points at the successor endpoint.
    assert "link" in headers and "/v1/redact" in headers["link"], dict(resp.headers)


# ---------------------------------------------------------------------------
# /v1/audit/append
# ---------------------------------------------------------------------------
def test_audit_append_writes_row(gateway_client, alice_token):
    """POST /v1/audit/append → 200; subsequent /v1/audit/recent (auditor
    role) shows a row whose user_id is the gateway-tagged Alice."""
    # 1. Append a row as Alice.
    resp = gateway_client.post(
        "/v1/audit/append",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "endpoint": "/v1/audit/append-test",
            "model_used": "mock-llm",
            "prompt_tokens": 42,
            "completion_tokens": 7,
            "latency_ms": 150,
            "masked_field_rules": ["email"],
            "policy_decisions": {"authz_passed": True, "rate_limit_passed": True},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"appended": True}

    # 2. Read it back as the auditor (audit_dave is in tenant_a, same as alice).
    auditor_token = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "audit_dave", "password": "demo-audit_dave"},
    ).json()["token"]
    recent = gateway_client.get(
        "/v1/audit/recent",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert recent.status_code == 200, recent.text
    rows = recent.json()
    # Filter for the test endpoint name to isolate this row across re-runs.
    matching = [r for r in rows if r["endpoint"] == "/v1/audit/append-test"]
    assert matching, f"no audit row for /v1/audit/append-test in {rows!r}"
    row = matching[0]
    assert row["user_id"] == "alice", row     # gateway-trusted, not body-supplied
    assert row["case_id"] == _ALICE_CASE, row
    assert row["model_used"] == "mock-llm", row
    assert row["prompt_tokens"] == 42, row
    assert row["completion_tokens"] == 7, row


def test_audit_append_rejects_forgery_with_422(gateway_client, alice_token):
    """Security invariant (tightened post-review): the AuditAppendRequest
    schema has `extra="forbid"`, so a body containing user_id / tenant_id
    (or any unexpected key) is REJECTED with 422 — not silently dropped.

    This is the load-bearing test for the "no audit forgery" property: if
    a future Pydantic config change flips extra back to `ignore`, this test
    goes red instead of silently degrading to "rows are tagged alice anyway"."""
    resp = gateway_client.post(
        "/v1/audit/append",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "endpoint": "/v1/audit/forge-test",
            "user_id": "bob",            # extra — must trigger 422
            "tenant_id": "tenant_b",     # extra — must trigger 422
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1,
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Pydantic v2 reports the offending field in the error detail.
    detail_str = str(body).lower()
    assert "user_id" in detail_str or "extra" in detail_str, body


def test_audit_append_acl_blocks_foreign_case_id(gateway_client, alice_token):
    """Case ACL: alice (tenant_a, ACL = CASE-2025-001/002/003) cannot append
    a row for a case_id she doesn't own. Without this check any logged-in
    user could pollute their tenant's audit chain with rows referencing
    arbitrary (or attacker-chosen) case_ids — caught by Day 8B review."""
    resp = gateway_client.post(
        "/v1/audit/append",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": "CASE-9999-CARROT",   # NOT in Alice's ACL
            "endpoint": "/v1/audit/foreign-case-test",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1,
        },
    )
    assert resp.status_code == 403, resp.text


def test_audit_append_paralegal_role_gated(gateway_client):
    """Role gate: PARALEGAL is excluded from /v1/audit/append per the
    _AUDIT_APPEND_ROLES whitelist (ATTORNEY / IT_ADMIN / AUDITOR only).
    Bob is the demo paralegal — his token authenticates but the endpoint
    must refuse with 403 before any audit row is written."""
    bob_token = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "bob", "password": "demo-bob"},
    ).json()["token"]
    resp = gateway_client.post(
        "/v1/audit/append",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={
            "case_id": _ALICE_CASE,          # Bob has ACL on this case
            "endpoint": "/v1/audit/paralegal-test",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1,
        },
    )
    assert resp.status_code == 403, resp.text
    assert "paralegal" in resp.text.lower() or "role" in resp.text.lower(), resp.text


def test_audit_append_length_caps_reject_huge_strings(gateway_client, alice_token):
    """Length caps on the audit append schema prevent a 10 MB endpoint
    string from ballooning the hash-chained log."""
    resp = gateway_client.post(
        "/v1/audit/append",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "endpoint": "x" * 10_000,   # exceeds max_length=256
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1,
        },
    )
    assert resp.status_code == 422, resp.text


def test_audit_append_requires_auth(gateway_client):
    """No Authorization header → 401, before any audit row is written."""
    resp = gateway_client.post(
        "/v1/audit/append",
        json={
            "case_id": _ALICE_CASE,
            "endpoint": "/v1/audit/should-be-rejected",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0,
        },
    )
    assert resp.status_code == 401, resp.text
