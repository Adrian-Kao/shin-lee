"""Integration tests for the durable audit outbox (Q13 — invariant #4 backstop).

Invariant #4 (CLAUDE.md §4) promises *exactly one* audit row per gateway
request — even on errors. ``_safe_audit_write`` deliberately swallows any
exception from the primary SQLite audit writer so a broken audit DB can't mask
the genuine response the caller is about to see. Pre-outbox, that swallow lost
the row forever → zero rows → invariant #4 silently violated.

The outbox (``backend.gateway.audit_outbox``) closes the hole: on primary-write
failure the full payload is appended (fsync'd) to a durable JSONL file, and a
``replay_outbox()`` job drains it back into the audit DB once the DB recovers.

These tests cover:
  1. Writer failure → request still returns its normal response (no 500 leaks
     from audit) AND a row lands in the outbox file, JSON-parseable, carrying
     the expected endpoint/case_id.
  2. ``replay_outbox()`` drains the outbox into the real audit DB once writes
     succeed again, leaving ``outbox_depth() == 0`` and the replayed row
     visible to the auditor.
  3. ``replay_outbox`` / ``outbox_depth`` tolerate a missing/empty file.

The audit failure is simulated exactly as ``test_audit_error_path.py`` does:
monkeypatch ``backend.gateway.audit.writer.write`` to raise. The outbox path is
pinned to a per-test ``tmp_path`` via ``config.AUDIT_OUTBOX_PATH`` so the real
``data/`` tree is never touched and tests don't see each other's backlog.
"""
from __future__ import annotations

import json

import pytest

_ALICE_CASE = "CASE-2025-001"     # alice has ACL


@pytest.fixture()
def outbox_path(tmp_path, monkeypatch):
    """Pin the outbox to a fresh tmp file for this test.

    ``audit_outbox._outbox_path()`` reads ``config.AUDIT_OUTBOX_PATH`` lazily
    on every call, so monkeypatching the config constant is enough — no module
    re-import needed.
    """
    from backend.shared import config

    p = tmp_path / "audit_outbox.jsonl"
    monkeypatch.setattr(config, "AUDIT_OUTBOX_PATH", p)
    return p


@pytest.fixture()
def failing_audit_writer(monkeypatch):
    """Make the primary audit writer raise, as if the SQLite DB were down.

    Returns the call-count dict so a test can assert the writer was actually
    invoked (and thus the outbox enqueue path was reached).
    """
    from backend.gateway import audit as audit_mod

    calls = {"n": 0}

    def _failing_write(**kwargs):
        calls["n"] += 1
        raise RuntimeError("simulated audit DB outage")

    monkeypatch.setattr(audit_mod.writer, "write", _failing_write)
    return calls


def _login_auditor(client) -> str:
    """audit_dave is tenant_a like alice — so /v1/audit/recent surfaces
    alice's rows after a successful replay."""
    return client.post(
        "/v1/auth/login",
        json={"user_id": "audit_dave", "password": "demo-audit_dave"},
    ).json()["token"]


# ---------------------------------------------------------------------------
# 1. Writer failure → normal response returned + row durably in the outbox.
# ---------------------------------------------------------------------------
def test_writer_failure_enqueues_to_outbox_and_does_not_mask_response(
    gateway_client, alice_token, patched_ai_engine, outbox_path, failing_audit_writer
):
    """A valid analyze request whose audit write fails must:
      - still return 200 with the real analysis (the audit outage is invisible
        to the caller), and
      - leave exactly one JSON-parseable row in the outbox file carrying the
        right endpoint + case_id.
    """
    from backend.gateway import audit_outbox

    assert audit_outbox.outbox_depth() == 0  # fresh tmp file

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "Some OA text for the outbox durability test.",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US17000002",
        },
    )
    # Audit outage must NOT surface to the caller.
    assert resp.status_code == 200, resp.text
    # The primary writer was actually attempted (and failed).
    assert failing_audit_writer["n"] >= 1

    # Exactly one row landed in the durable outbox.
    assert audit_outbox.outbox_depth() == 1
    assert outbox_path.exists()

    lines = [l for l in outbox_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, lines
    record = json.loads(lines[0])  # must be JSON-parseable

    # The flattened User identity is stored, not the live object.
    assert record["user"]["user_id"] == "alice"
    assert record["user"]["tenant_id"] == "tenant_a"
    # role is serialised as its plain enum value.
    assert isinstance(record["user"]["role"], str)

    kwargs = record["kwargs"]
    assert kwargs["endpoint"] == "/v1/oa/analyze"
    assert kwargs["case_id"] == _ALICE_CASE
    # No live User object leaked into the serialised kwargs.
    assert "user" not in kwargs


# ---------------------------------------------------------------------------
# 2. replay_outbox drains into the real audit DB once writes succeed again.
# ---------------------------------------------------------------------------
def test_replay_drains_outbox_into_audit_db(
    gateway_client, alice_token, patched_ai_engine, outbox_path, monkeypatch
):
    """Force the write to fail (row → outbox), then restore the real writer and
    replay. The row must land in the audit DB, be visible via /v1/audit/recent,
    and the outbox must drain to depth 0."""
    from backend.gateway import audit as audit_mod
    from backend.gateway import audit_outbox

    # Phase 1 — break the writer so the request's audit row goes to the outbox.
    real_write = audit_mod.writer.write

    def _failing_write(**kwargs):
        raise RuntimeError("simulated audit DB outage")

    monkeypatch.setattr(audit_mod.writer, "write", _failing_write)

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "OA text whose audit row will be replayed.",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US17000003",
        },
    )
    assert resp.status_code == 200, resp.text
    assert audit_outbox.outbox_depth() == 1

    # Phase 2 — DB recovers. Restore the real writer and count rows before replay.
    monkeypatch.setattr(audit_mod.writer, "write", real_write)
    auditor_token = _login_auditor(gateway_client)
    rows_before = gateway_client.get(
        "/v1/audit/recent",
        params={"limit": 200},
        headers={"Authorization": f"Bearer {auditor_token}"},
    ).json()
    # Filter to the replayed endpoint/case so the auditor's own login rows
    # don't confuse the count.
    n_target_before = sum(
        1
        for r in rows_before
        if r["endpoint"] == "/v1/oa/analyze" and r["case_id"] == _ALICE_CASE
    )

    summary = audit_outbox.replay_outbox()
    assert summary == {"replayed": 1, "remaining": 0}, summary
    assert audit_outbox.outbox_depth() == 0
    # File is removed once fully drained.
    assert not outbox_path.exists()

    # The replayed row is now in the real audit DB.
    rows_after = gateway_client.get(
        "/v1/audit/recent",
        params={"limit": 200},
        headers={"Authorization": f"Bearer {auditor_token}"},
    ).json()
    n_target_after = sum(
        1
        for r in rows_after
        if r["endpoint"] == "/v1/oa/analyze" and r["case_id"] == _ALICE_CASE
    )
    assert n_target_after == n_target_before + 1, (n_target_before, n_target_after)

    # A second replay on the now-empty outbox is a no-op (idempotent-safe).
    assert audit_outbox.replay_outbox() == {"replayed": 0, "remaining": 0}


# ---------------------------------------------------------------------------
# 3. replay / depth tolerate a missing or empty outbox file.
# ---------------------------------------------------------------------------
def test_replay_and_depth_tolerate_missing_file(outbox_path):
    from backend.gateway import audit_outbox

    assert not outbox_path.exists()
    assert audit_outbox.outbox_depth() == 0
    assert audit_outbox.replay_outbox() == {"replayed": 0, "remaining": 0}

    # Empty file (touched but no rows) is also tolerated.
    outbox_path.write_text("", encoding="utf-8")
    assert audit_outbox.outbox_depth() == 0
    assert audit_outbox.replay_outbox() == {"replayed": 0, "remaining": 0}


# ---------------------------------------------------------------------------
# 4. A row that fails replay again stays queued (no silent drop).
# ---------------------------------------------------------------------------
def test_replay_keeps_rows_that_fail_again(
    gateway_client, alice_token, patched_ai_engine, outbox_path, monkeypatch
):
    from backend.gateway import audit as audit_mod
    from backend.gateway import audit_outbox

    def _failing_write(**kwargs):
        raise RuntimeError("audit DB still down")

    monkeypatch.setattr(audit_mod.writer, "write", _failing_write)

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "OA text whose replay will fail again.",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US17000004",
        },
    )
    assert resp.status_code == 200, resp.text
    assert audit_outbox.outbox_depth() == 1

    # Writer is STILL broken at replay time → row must be retained, not dropped.
    summary = audit_outbox.replay_outbox()
    assert summary == {"replayed": 0, "remaining": 1}, summary
    assert audit_outbox.outbox_depth() == 1
    assert outbox_path.exists()
