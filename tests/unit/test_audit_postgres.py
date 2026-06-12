"""Q13 — Postgres audit backend (``AUDIT_BACKEND=postgres``).

Mirrors the Qdrant pattern in test_vector_store_robustness.py: the suite stays
green with no container (every test skips cleanly when Postgres is
unreachable), and runs the full battery when the compose Postgres is up
(``docker compose up -d postgres`` — host port **15432** on the delivery box).

Each test session runs inside a throwaway schema (``audit_test_<hex>``) so a
shared dev Postgres is never polluted and a tamper test's deliberately-broken
chain can never leak into another run. The schema is dropped on teardown
(DDL is not blocked by the row-level append-only triggers — same posture as
SQLite, where deleting the .db file is also outside the trigger's reach; the
WORM archive is the defence for that class of attack).

What must hold (parity with the SQLite backend):

  * same hash-chain format — write via Postgres, verify via the SHARED
    ``_BaseAuditWriter`` verify logic;
  * append-only enforced server-side — direct UPDATE / DELETE are refused by
    the plpgsql trigger;
  * tamper detection — a DBA who disables the trigger and edits a row is
    caught by verify_chain / verify_global_chain;
  * the WORM archiver (audit_archive.py) seals + verifies straight off the
    Postgres store via ``audit.read_live_rows``.
"""

from __future__ import annotations

import uuid

import pytest

from backend.gateway import audit, audit_archive
from backend.shared import config
from backend.shared.config import settings
from backend.shared.models import User, UserRole

psycopg = pytest.importorskip("psycopg")

# The compose container binds host port 15432 (5432 is taken on the delivery
# box), but config's generic default says 5432 — try both so the test works
# with either a real .env or the bare compose defaults.
_CANDIDATE_DSNS = [
    settings.POSTGRES_URL,
    "postgresql://patentmind:patentmind@localhost:15432/patentmind",
]


def _dsn_or_skip() -> str:
    last_exc: Exception | None = None
    for dsn in dict.fromkeys(_CANDIDATE_DSNS):
        try:
            conn = psycopg.connect(dsn, connect_timeout=2)
            conn.close()
            return dsn
        except Exception as exc:  # pragma: no cover - env-dependent
            last_exc = exc
    pytest.skip(f"Postgres not reachable (tried {_CANDIDATE_DSNS}): {last_exc}")


@pytest.fixture()
def pg(tmp_path):
    """A PostgresAuditWriter bound to a fresh throwaway schema."""
    dsn = _dsn_or_skip()
    schema = f"audit_test_{uuid.uuid4().hex[:10]}"
    writer = audit.PostgresAuditWriter(dsn=dsn, schema=schema)
    yield {"writer": writer, "dsn": dsn, "schema": schema}
    writer.close()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _user(tenant_id: str = "tenant_a") -> User:
    return User(
        user_id="alice",
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name="Alice",
    )


def _write_rows(writer, n: int, tenant_id: str = "tenant_a", start: int = 0) -> list[str]:
    ids = []
    for i in range(start, start + n):
        ids.append(
            writer.write(
                user=_user(tenant_id),
                case_id=f"case-{i}",
                endpoint="/v1/analyze",
                request_payload={"q": i},
                response_payload={"a": i},
                masked_rules=["pii.email"],
                model_used="mock",
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
                policy_decisions={"redacted": True},
            )
        )
    return ids


def _raw(pg_ctx):
    """Fresh autocommit connection scoped to the test schema (the 'DBA')."""
    conn = psycopg.connect(pg_ctx["dsn"], autocommit=True)
    conn.execute(f'SET search_path TO "{pg_ctx["schema"]}"')
    return conn


# ---------------------------------------------------------------------------
# 1. Chain semantics — identical to SQLite.
# ---------------------------------------------------------------------------
def test_write_and_verify_chain_ok(pg):
    ids = _write_rows(pg["writer"], 5)
    rep = pg["writer"].verify_chain("tenant_a")
    assert rep["verified"] == 5
    assert rep["broken"] == []
    # Insertion order is preserved by the row_seq walk.
    assert [r["audit_id"] for r in pg["writer"].read_all_rows()] == ids


def test_verify_global_chain_ok_multi_tenant(pg):
    _write_rows(pg["writer"], 2, tenant_id="tenant_a")
    _write_rows(pg["writer"], 2, tenant_id="tenant_b")
    _write_rows(pg["writer"], 1, tenant_id="tenant_a")
    rep = pg["writer"].verify_global_chain()
    assert rep["verified"] == 5
    assert rep["broken"] == []
    # The chain is GLOBAL: tenant_b's first row chains off tenant_a's last —
    # the per-tenant view of tenant_b would look broken, the global one not.
    assert rep["by_tenant"]["tenant_b"]["verified"] == 2


def test_chain_links_prev_row_hash(pg):
    _write_rows(pg["writer"], 3)
    rows = pg["writer"].read_all_rows()
    assert rows[0]["prev_row_hash"] == ""
    assert rows[1]["prev_row_hash"] == rows[0]["row_hash"]
    assert rows[2]["prev_row_hash"] == rows[1]["row_hash"]


def test_hash_format_is_shared_with_sqlite():
    """Both backends inherit the ONE _hash_payload — the chain format cannot
    drift between them."""
    payload = {"audit_id": "x", "ts": "t", "user": "u", "tenant": "tenant_a"}
    assert (
        audit.AuditWriter._hash_payload(payload)
        == audit.PostgresAuditWriter._hash_payload(payload)
        == audit._BaseAuditWriter._hash_payload(payload)
    )
    assert audit.PostgresAuditWriter.verify_chain is audit.AuditWriter.verify_chain
    assert audit.PostgresAuditWriter.verify_global_chain is audit.AuditWriter.verify_global_chain


def test_list_for_tenant_shape(pg):
    _write_rows(pg["writer"], 3)
    rows = pg["writer"].list_for_tenant("tenant_a", limit=2)
    assert len(rows) == 2
    # Most recent first; JSON columns decoded.
    assert rows[0]["case_id"] == "case-2"
    assert rows[0]["masked_field_rules"] == ["pii.email"]
    assert rows[0]["policy_decisions"] == {"redacted": True}


# ---------------------------------------------------------------------------
# 2. Append-only — the plpgsql trigger refuses UPDATE / DELETE.
# ---------------------------------------------------------------------------
def test_direct_update_is_refused_by_trigger(pg):
    ids = _write_rows(pg["writer"], 2)
    conn = _raw(pg)
    try:
        with pytest.raises(psycopg.Error, match="append-only"):
            conn.execute(
                "UPDATE audit SET row_hash = %s WHERE audit_id = %s",
                ("deadbeef" * 8, ids[0]),
            )
    finally:
        conn.close()
    # Nothing changed — chain still verifies.
    assert pg["writer"].verify_chain("tenant_a")["broken"] == []


def test_direct_delete_is_refused_by_trigger(pg):
    ids = _write_rows(pg["writer"], 2)
    conn = _raw(pg)
    try:
        with pytest.raises(psycopg.Error, match="append-only"):
            conn.execute("DELETE FROM audit WHERE audit_id = %s", (ids[1],))
    finally:
        conn.close()
    assert len(pg["writer"].read_all_rows()) == 2


# ---------------------------------------------------------------------------
# 3. Tamper detection — a DBA who disables the trigger still breaks the chain.
# ---------------------------------------------------------------------------
def test_tamper_after_trigger_disable_breaks_chain(pg):
    ids = _write_rows(pg["writer"], 3)
    conn = _raw(pg)
    try:
        conn.execute("ALTER TABLE audit DISABLE TRIGGER audit_no_update")
        conn.execute(
            "UPDATE audit SET response_hash = %s WHERE audit_id = %s",
            ("ff" * 32, ids[1]),
        )
        conn.execute("ALTER TABLE audit ENABLE TRIGGER audit_no_update")
    finally:
        conn.close()

    rep = pg["writer"].verify_chain("tenant_a")
    assert ids[1] in rep["broken"]

    grep = pg["writer"].verify_global_chain()
    assert ("tenant_a", ids[1]) in grep["broken"]


def test_tampered_row_hash_breaks_chain_and_referential_pass(pg):
    ids = _write_rows(pg["writer"], 3)
    conn = _raw(pg)
    try:
        conn.execute("ALTER TABLE audit DISABLE TRIGGER audit_no_update")
        conn.execute(
            "UPDATE audit SET row_hash = %s WHERE audit_id = %s",
            ("deadbeef" * 8, ids[0]),
        )
        conn.execute("ALTER TABLE audit ENABLE TRIGGER audit_no_update")
    finally:
        conn.close()

    rep = pg["writer"].verify_global_chain()
    broken_ids = {aid for (_tid, aid) in rep["broken"]}
    # Row 0's recomputed hash mismatches; row 1's prev now dangles → both flagged.
    assert ids[0] in broken_ids
    assert ids[1] in broken_ids


# ---------------------------------------------------------------------------
# 4. WORM archiver runs unchanged on the Postgres backend.
# ---------------------------------------------------------------------------
@pytest.fixture()
def pg_archive(pg, tmp_path, monkeypatch):
    """Point the archiver's live-DB read at the Postgres writer."""
    monkeypatch.setattr(config.settings, "AUDIT_BACKEND", "postgres")
    monkeypatch.setattr(config.settings, "ARCHIVE_BACKEND", "local", raising=False)
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", tmp_path / "audit_archive")
    monkeypatch.setattr(audit, "writer", pg["writer"])
    return pg


def test_archive_seals_and_verifies_from_postgres(pg_archive):
    _write_rows(pg_archive["writer"], 3)
    result = audit_archive.seal_next_segment(now_iso="2026-06-12T00:00:00+00:00")
    assert result["sealed"] is True
    assert result["row_count"] == 3

    rep = audit_archive.verify_archive()
    assert rep["ok"] is True, rep["anomalies"]
    assert rep["rows_archived"] == 3


def test_archive_detects_live_postgres_tamper(pg_archive):
    ids = _write_rows(pg_archive["writer"], 3)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    conn = _raw(pg_archive)
    try:
        conn.execute("ALTER TABLE audit DISABLE TRIGGER audit_no_update")
        conn.execute(
            "UPDATE audit SET row_hash = %s WHERE audit_id = %s",
            ("deadbeef" * 8, ids[2]),
        )
        conn.execute("ALTER TABLE audit ENABLE TRIGGER audit_no_update")
    finally:
        conn.close()

    rep = audit_archive.verify_archive()
    assert rep["ok"] is False
    tampered = [a for a in rep["anomalies"] if a["type"] == "live_row_tampered"]
    assert any(a["audit_id"] == ids[2] for a in tampered)


# ---------------------------------------------------------------------------
# 5. Outbox replay targets whatever writer is live (invariant #4 backstop).
# ---------------------------------------------------------------------------
def test_outbox_replays_into_postgres(pg, tmp_path, monkeypatch):
    from backend.gateway import audit_outbox

    monkeypatch.setattr(config, "AUDIT_OUTBOX_PATH", tmp_path / "outbox.jsonl")
    monkeypatch.setattr(audit, "writer", pg["writer"])

    audit_outbox.enqueue(
        user=_user(),
        case_id="case-ob",
        endpoint="/v1/analyze",
        request_payload={"q": 1},
        response_payload={"a": 1},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
        policy_decisions={"redacted": True},
    )
    assert audit_outbox.outbox_depth() == 1

    summary = audit_outbox.replay_outbox()
    assert summary == {"replayed": 1, "remaining": 0}
    rows = pg["writer"].read_all_rows()
    assert len(rows) == 1
    assert pg["writer"].verify_chain("tenant_a")["broken"] == []
