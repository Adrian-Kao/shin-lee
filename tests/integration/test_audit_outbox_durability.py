"""Outbox durability deep battery (Q13 — invariant #4 backstop).

``test_audit_outbox.py`` covers the single-row gateway path. This file is the
*durability* battery the Day-13G track requires, exercising the outbox directly
(no gateway) so we can drive multi-row + ordering + idempotency scenarios
precisely:

  * **Multi-row replay preserves order** — N rows enqueued out of a forced
    failure replay back into the audit DB in the SAME order, and the resulting
    audit chain verifies (no gaps/dupes).
  * **Idempotent replay** — replaying a fully-drained outbox a second time
    writes nothing (no duplicate audit rows).
  * **Partial failure** — when SOME replays fail, the failures are retained
    in order and the successes are not re-applied on the next drain.
  * **Chain integrity after replay** — the rows written by replay chain onto
    whatever was already in the audit DB; ``verify_chain`` reports no breaks.

The outbox + audit DB are both pinned to tmp paths; the audit writer is a
private AuditWriter bound to the tmp DB, and ``audit.writer`` (the module
singleton that ``replay_outbox`` calls) is monkeypatched to it so replay lands
in OUR tmp DB, never the conftest session DB.
"""
from __future__ import annotations

import json

import pytest

from backend.gateway import audit, audit_outbox
from backend.shared import config
from backend.shared.models import User, UserRole


@pytest.fixture()
def tmp_outbox(tmp_path, monkeypatch):
    """Pin outbox + audit DB to tmp paths and point the module singleton at a
    private writer bound to the tmp DB, so replay_outbox writes into OUR DB."""
    outbox_p = tmp_path / "audit_outbox.jsonl"
    db_p = tmp_path / "audit.db"
    monkeypatch.setattr(config, "AUDIT_OUTBOX_PATH", outbox_p)
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db_p)

    private_writer = audit.AuditWriter(path=db_p)
    # replay_outbox() calls ``audit.writer.write`` (the module singleton).
    monkeypatch.setattr(audit, "writer", private_writer)
    return {"outbox": outbox_p, "db": db_p, "writer": private_writer}


def _user() -> User:
    return User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice",
        daily_token_quota=10_000,
    )


def _enqueue_row(i: int) -> None:
    """Enqueue one audit-row payload exactly as _safe_audit_write would on a
    primary-write failure."""
    audit_outbox.enqueue(
        user=_user(),
        case_id=f"CASE-{i}",
        endpoint="/v1/oa/analyze",
        request_payload={"i": i},
        response_payload={"ok": i},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
        policy_decisions={"authn_passed": True, "seq": i},
    )


# ===========================================================================
# 1. Multi-row replay preserves order + chain verifies.
# ===========================================================================
def test_multi_row_replay_preserves_order_and_chain(tmp_outbox):
    N = 5
    for i in range(N):
        _enqueue_row(i)
    assert audit_outbox.outbox_depth() == N

    summary = audit_outbox.replay_outbox()
    assert summary == {"replayed": N, "remaining": 0}, summary
    assert audit_outbox.outbox_depth() == 0
    assert not tmp_outbox["outbox"].exists()

    # Rows landed in the audit DB in the SAME order they were enqueued.
    rows = tmp_outbox["writer"].list_for_tenant("tenant_a", limit=100)
    # list_for_tenant is most-recent-first → reverse to insertion order.
    insertion = list(reversed(rows))
    case_seq = [r["case_id"] for r in insertion]
    assert case_seq == [f"CASE-{i}" for i in range(N)], case_seq

    # The chain the replay built must verify with no breaks or gaps.
    chain = tmp_outbox["writer"].verify_chain("tenant_a")
    assert chain["broken"] == [], chain
    assert chain["verified"] == N, chain


# ===========================================================================
# 2. Idempotent replay — second drain writes nothing (no duplicates).
# ===========================================================================
def test_replay_is_idempotent_no_duplicates(tmp_outbox):
    for i in range(3):
        _enqueue_row(i)

    first = audit_outbox.replay_outbox()
    assert first == {"replayed": 3, "remaining": 0}, first
    rows_after_first = tmp_outbox["writer"].list_for_tenant("tenant_a", limit=100)
    assert len(rows_after_first) == 3

    # Drain again — file is gone, so nothing happens. No duplicate rows.
    second = audit_outbox.replay_outbox()
    assert second == {"replayed": 0, "remaining": 0}, second
    rows_after_second = tmp_outbox["writer"].list_for_tenant("tenant_a", limit=100)
    assert len(rows_after_second) == 3, "replay duplicated rows"


# ===========================================================================
# 3. Partial failure — failing rows retained in order; successes not re-applied.
# ===========================================================================
def test_partial_replay_retains_failures_without_reapplying_successes(
    tmp_outbox, monkeypatch
):
    for i in range(4):
        _enqueue_row(i)

    # Make the writer fail for CASE-2 only; everything else succeeds.
    real_write = tmp_outbox["writer"].write
    flip = {"down": True}

    def _selective_write(**kwargs):
        if kwargs.get("case_id") == "CASE-2" and flip["down"]:
            raise RuntimeError("simulated row-specific failure")
        return real_write(**kwargs)

    monkeypatch.setattr(tmp_outbox["writer"], "write", _selective_write)

    first = audit_outbox.replay_outbox()
    # 3 succeed (0,1,3), 1 stays (2).
    assert first == {"replayed": 3, "remaining": 1}, first
    assert audit_outbox.outbox_depth() == 1

    # The remaining line must be CASE-2 (order/identity preserved).
    remaining = [
        json.loads(l)
        for l in tmp_outbox["outbox"].read_text("utf-8").splitlines()
        if l.strip()
    ]
    assert len(remaining) == 1
    assert remaining[0]["kwargs"]["case_id"] == "CASE-2"

    # DB recovers; drain again. CASE-2 lands, and the 3 already-written rows
    # are NOT re-applied (no duplicates).
    flip["down"] = False
    second = audit_outbox.replay_outbox()
    assert second == {"replayed": 1, "remaining": 0}, second

    rows = tmp_outbox["writer"].list_for_tenant("tenant_a", limit=100)
    cases = sorted(r["case_id"] for r in rows)
    assert cases == ["CASE-0", "CASE-1", "CASE-2", "CASE-3"], cases
    # Exactly 4 — no duplicates from the two-phase drain.
    assert len(rows) == 4

    # And the chain is still intact after the out-of-original-order arrival.
    chain = tmp_outbox["writer"].verify_chain("tenant_a")
    assert chain["broken"] == [], chain
    assert chain["verified"] == 4, chain


# ===========================================================================
# 4. Replay chains onto pre-existing audit rows (no reset to prev='').
# ===========================================================================
def test_replay_chains_onto_existing_rows(tmp_outbox):
    # Seed two rows directly into the DB (the "already there" history).
    w = tmp_outbox["writer"]
    for i in range(2):
        w.write(
            user=_user(),
            case_id=f"SEED-{i}",
            endpoint="/seed",
            request_payload={"s": i},
            response_payload={"ok": True},
            masked_rules=[],
            model_used="mock",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
            policy_decisions={"authn_passed": True},
        )

    # Now enqueue + replay two more.
    for i in range(2):
        _enqueue_row(i)
    assert audit_outbox.replay_outbox() == {"replayed": 2, "remaining": 0}

    # 4 rows total, all chained, no breaks.
    rows = w.list_for_tenant("tenant_a", limit=100)
    assert len(rows) == 4
    chain = w.verify_chain("tenant_a")
    assert chain["broken"] == [], chain
    assert chain["verified"] == 4, chain


# ===========================================================================
# 5. Corrupt outbox line is retained, not silently dropped, and never
#    duplicated by re-replay.
# ===========================================================================
def test_corrupt_line_retained_and_not_replayed(tmp_outbox):
    _enqueue_row(0)
    # Append a non-JSON line to the outbox.
    with open(tmp_outbox["outbox"], "a", encoding="utf-8") as fh:
        fh.write("this is not json\n")

    assert audit_outbox.outbox_depth() == 2

    summary = audit_outbox.replay_outbox()
    # The good row replays; the corrupt line is retained for inspection.
    assert summary == {"replayed": 1, "remaining": 1}, summary
    assert audit_outbox.outbox_depth() == 1

    remaining = [
        l for l in tmp_outbox["outbox"].read_text("utf-8").splitlines() if l.strip()
    ]
    assert remaining == ["this is not json"], remaining

    # Re-replaying does not duplicate the good row (it's already drained) and
    # keeps the corrupt line.
    again = audit_outbox.replay_outbox()
    assert again == {"replayed": 0, "remaining": 1}, again
    rows = tmp_outbox["writer"].list_for_tenant("tenant_a", limit=100)
    assert len(rows) == 1
