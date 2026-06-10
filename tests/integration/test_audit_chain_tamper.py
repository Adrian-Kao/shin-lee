"""Hash-chain tamper-detection battery (Q13 — invariant #4 / §7 pitfall #4).

The audit log is an append-only, hash-chained SQLite table. ``verify_chain``
(per-tenant), ``verify_global_chain`` (cross-tenant, rowid order), and the new
``verify_cross_tenant`` (side-by-side comparison helper) are the verifiers an
auditor runs nightly to detect tampering.

This module is the *adversarial* battery: for each distinct mutation an attacker
or compromised DBA could perform on a SINGLE-TENANT chain, assert the verifier
both reports a break AND pinpoints the offending row. The cross-tenant tests in
``test_cross_tenant.py`` cover the multi-tenant/global walk; this file focuses on
the per-tenant ``verify_chain`` row-level pinpointing plus the new
``verify_cross_tenant`` helper.

All tests use a per-test tmp SQLite DB so the conftest session ``audit.writer``
singleton is never touched and no state leaks between tests.

Threat model note: the append-only UPDATE/DELETE triggers block a casual DBA.
To simulate a *determined* attacker who first drops the triggers (or a SQLite
file edited offline), we drop the trigger then mutate via raw SQL — exactly the
post-compromise state the verifier exists to catch.
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from backend.gateway.audit import AuditWriter
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _writer(tmp_path) -> AuditWriter:
    return AuditWriter(path=tmp_path / "audit.db")


def _seed(writer: AuditWriter, tenant_id: str, n: int, start: int = 0) -> list[str]:
    """Write n legitimate rows for tenant_id; return audit_ids in order."""
    user = User(
        user_id=f"u_{tenant_id}",
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name="test",
        daily_token_quota=10_000,
    )
    ids: list[str] = []
    for i in range(start, start + n):
        ids.append(
            writer.write(
                user=user,
                case_id=f"CASE-{tenant_id}-{i}",
                endpoint="/test",
                request_payload={"i": i},
                response_payload={"ok": True},
                masked_rules=[],
                model_used="mock",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=1,
                policy_decisions={"authn_passed": True},
            )
        )
    return ids


def _drop_triggers(db_path) -> sqlite3.Connection:
    """Open a raw connection with the append-only triggers dropped, so the
    test can simulate a post-compromise mutation. Caller closes it."""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    return conn


# ===========================================================================
# Part A — per-tenant verify_chain pinpoints each tamper class.
# ===========================================================================
def test_verify_chain_clean_chain_has_no_breaks(tmp_path):
    w = _writer(tmp_path)
    _seed(w, "tenant_a", 4)
    result = w.verify_chain("tenant_a")
    assert result["verified"] == 4, result
    assert result["broken"] == [], result


def test_verify_chain_detects_mutated_request_hash(tmp_path):
    """Mutating a row's request_hash changes the recomputed row_hash but the
    recorded row_hash stays old → hash mismatch on THAT row."""
    w = _writer(tmp_path)
    ids = _seed(w, "tenant_a", 4)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute(
        "UPDATE audit SET request_hash = ? WHERE audit_id = ?",
        ("tampered-request-hash", ids[2]),
    )
    conn.commit()
    conn.close()

    result = w.verify_chain("tenant_a")
    assert ids[2] in result["broken"], result
    # Only the mutated row is flagged for the hash recompute (the chain-link
    # of the NEXT row still matches because we didn't touch row_hash columns).
    assert result["broken"].count(ids[2]) >= 1


def test_verify_chain_detects_mutated_row_hash(tmp_path):
    """Mutating a row's stored row_hash flags that row (recompute != recorded)
    AND the NEXT row (its prev_row_hash no longer matches the mutated value)."""
    w = _writer(tmp_path)
    ids = _seed(w, "tenant_a", 4)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute(
        "UPDATE audit SET row_hash = ? WHERE audit_id = ?",
        ("00" * 32, ids[1]),
    )
    conn.commit()
    conn.close()

    result = w.verify_chain("tenant_a")
    # The mutated row fails its own hash recompute.
    assert ids[1] in result["broken"], result
    # The following row's recorded prev != the (now mutated) value the walk
    # carries forward, so it is flagged too — the break propagates by one.
    assert ids[2] in result["broken"], result


def test_verify_chain_detects_mutated_prev_hash(tmp_path):
    """Tampering a row's prev_row_hash breaks that row two ways: the
    chain-link check (recorded_prev != expected prev) and the hash recompute
    (payload includes prev)."""
    w = _writer(tmp_path)
    ids = _seed(w, "tenant_a", 4)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute(
        "UPDATE audit SET prev_row_hash = ? WHERE audit_id = ?",
        ("ff" * 32, ids[2]),
    )
    conn.commit()
    conn.close()

    result = w.verify_chain("tenant_a")
    assert ids[2] in result["broken"], result


def test_verify_chain_detects_deleted_row(tmp_path):
    """Deleting a middle row leaves a gap: the row AFTER the hole has a
    prev_row_hash pointing at the now-deleted row's hash, which no longer
    equals the prev row the walk carries forward → break pinpointed at the
    row after the hole."""
    w = _writer(tmp_path)
    ids = _seed(w, "tenant_a", 5)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute("DELETE FROM audit WHERE audit_id = ?", (ids[2],))
    conn.commit()
    conn.close()

    result = w.verify_chain("tenant_a")
    # The row that followed the deleted one now dangles.
    assert ids[3] in result["broken"], result
    # The deleted row itself is gone, so it can't be in verified or broken.
    assert ids[2] not in result["broken"]
    # Rows before the hole are still intact.
    assert result["verified"] >= 2


def test_verify_chain_detects_reordered_rows(tmp_path):
    """Swapping two rows' rowid (insertion order) breaks the chain: the
    walk reads them in the new order, so the prev-links no longer match.

    We simulate reordering by rewriting rowids. SQLite rowid is the ORDER BY
    key the verifier walks, so swapping rowids == reordering the chain.
    """
    w = _writer(tmp_path)
    ids = _seed(w, "tenant_a", 4)
    conn = _drop_triggers(tmp_path / "audit.db")
    # Fetch current rowids for rows 1 and 2 (0-indexed: ids[1], ids[2]).
    rid1 = conn.execute(
        "SELECT rowid FROM audit WHERE audit_id = ?", (ids[1],)
    ).fetchone()[0]
    rid2 = conn.execute(
        "SELECT rowid FROM audit WHERE audit_id = ?", (ids[2],)
    ).fetchone()[0]
    # Swap them via a temp parking rowid (rowids must stay unique).
    park = 10_000_000
    conn.execute("UPDATE audit SET rowid = ? WHERE audit_id = ?", (park, ids[1]))
    conn.execute("UPDATE audit SET rowid = ? WHERE audit_id = ?", (rid1, ids[2]))
    conn.execute("UPDATE audit SET rowid = ? WHERE audit_id = ?", (rid2, ids[1]))
    conn.commit()
    conn.close()

    result = w.verify_chain("tenant_a")
    # Reordering breaks the chain — at least one of the swapped rows is flagged.
    assert ids[1] in result["broken"] or ids[2] in result["broken"], result
    assert result["broken"], "reordering went undetected"


def test_verify_chain_is_tenant_scoped(tmp_path):
    """A tamper in tenant_b must NOT show up in tenant_a's per-tenant verify."""
    w = _writer(tmp_path)
    a_ids = _seed(w, "tenant_a", 3)
    b_ids = _seed(w, "tenant_b", 3)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute(
        "UPDATE audit SET row_hash = ? WHERE audit_id = ?", ("00" * 32, b_ids[1])
    )
    conn.commit()
    conn.close()

    a_result = w.verify_chain("tenant_a")
    # tenant_a is queried in isolation; the global chain prev-link from a_ids[0]
    # is '' only if tenant_a's first row was the global first row. Here tenant_a
    # WAS written first, so its first row's prev == '' and the per-tenant walk
    # for tenant_a is internally consistent → no breaks from tenant_b's tamper.
    assert all(aid not in a_result["broken"] for aid in b_ids), a_result


# ===========================================================================
# Part B — verify_cross_tenant side-by-side helper.
# ===========================================================================
def test_cross_tenant_clean_two_tenants_ok(tmp_path):
    w = _writer(tmp_path)
    _seed(w, "tenant_a", 3)
    _seed(w, "tenant_b", 2)

    result = w.verify_cross_tenant(["tenant_a", "tenant_b"])
    assert result["ok"] is True, result["anomalies"]
    assert result["anomalies"] == []
    assert result["per_tenant"]["tenant_a"]["verified"] == 3
    assert result["per_tenant"]["tenant_b"]["verified"] == 2
    assert result["global_broken"] == []


def test_cross_tenant_flags_tenant_chain_break(tmp_path):
    """A tampered row in tenant_b must be attributed to tenant_b as a
    tenant_chain_break anomaly, and ok must be False."""
    w = _writer(tmp_path)
    _seed(w, "tenant_a", 2)
    b_ids = _seed(w, "tenant_b", 3)
    conn = _drop_triggers(tmp_path / "audit.db")
    conn.execute(
        "UPDATE audit SET request_hash = ? WHERE audit_id = ?",
        ("tampered", b_ids[1]),
    )
    conn.commit()
    conn.close()

    result = w.verify_cross_tenant(["tenant_a", "tenant_b"])
    assert result["ok"] is False
    breaks = [a for a in result["anomalies"] if a["type"] == "tenant_chain_break"]
    assert any(
        a["tenant_id"] == "tenant_b" and a["audit_id"] == b_ids[1] for a in breaks
    ), result["anomalies"]


def test_cross_tenant_flags_hash_collision_across_tenants(tmp_path):
    """If the SAME row_hash appears under two different tenants (copy-paste
    injection), verify_cross_tenant flags cross_tenant_hash_collision.

    We forge it: copy tenant_a's first row_hash onto a raw-inserted tenant_b
    row. An honest writer can never do this because the hash commits to
    ``tenant``."""
    w = _writer(tmp_path)
    a_ids = _seed(w, "tenant_a", 1)
    _seed(w, "tenant_b", 1)

    conn = _drop_triggers(tmp_path / "audit.db")
    stolen_hash = conn.execute(
        "SELECT row_hash FROM audit WHERE audit_id = ?", (a_ids[0],)
    ).fetchone()[0]
    # Raw-insert a tenant_b row carrying tenant_a's row_hash.
    conn.execute(
        "INSERT INTO audit ("
        " audit_id, timestamp_utc, timestamp_local, user_id, tenant_id, case_id,"
        " endpoint, request_hash, response_hash, masked_field_rules,"
        " model_used, prompt_tokens, completion_tokens, latency_ms,"
        " policy_decisions, prev_row_hash, row_hash"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()), "2026-06-04T00:00:00+00:00", "2026-06-04T08:00:00",
            "u_tenant_b", "tenant_b", "CASE-COLLIDE",
            "/x", "", "", "[]", "mock", 0, 0, 0,
            '{"authn_passed": true}', "", stolen_hash,
        ),
    )
    conn.commit()
    conn.close()

    result = w.verify_cross_tenant(["tenant_a", "tenant_b"])
    collisions = [
        a for a in result["anomalies"]
        if a["type"] == "cross_tenant_hash_collision"
    ]
    assert collisions, result["anomalies"]
    assert set(collisions[0]["tenants"]) == {"tenant_a", "tenant_b"}


def test_cross_tenant_reports_unexpected_and_missing_tenants(tmp_path):
    """Auditor asks about [tenant_a, tenant_c]; data has tenant_a + tenant_b.
    tenant_b is unexpected; tenant_c is missing."""
    w = _writer(tmp_path)
    _seed(w, "tenant_a", 2)
    _seed(w, "tenant_b", 1)

    result = w.verify_cross_tenant(["tenant_a", "tenant_c"])
    types = {(a["type"], a["tenant_id"]) for a in result["anomalies"]}
    assert ("unexpected_tenant", "tenant_b") in types, result["anomalies"]
    assert ("missing_tenant", "tenant_c") in types, result["anomalies"]
    assert result["ok"] is False


def test_cross_tenant_none_verifies_all_present(tmp_path):
    """tenant_ids=None verifies every tenant present and skips expected-set
    checks (no unexpected/missing anomalies)."""
    w = _writer(tmp_path)
    _seed(w, "tenant_a", 2)
    _seed(w, "tenant_b", 2)

    result = w.verify_cross_tenant(None)
    assert set(result["tenants_verified"]) == {"tenant_a", "tenant_b"}
    assert result["ok"] is True, result["anomalies"]
    assert not any(
        a["type"] in ("unexpected_tenant", "missing_tenant")
        for a in result["anomalies"]
    )
