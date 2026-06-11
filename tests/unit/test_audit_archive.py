"""Unit tests for the Q13 WORM archiver (backend/gateway/audit_archive.py).

These tests point both the live audit DB and the archive directory at tmp
paths via monkeypatching ``backend.shared.config`` (mirroring how conftest
redirects AUDIT_DB_PATH). Each test gets its own fresh AuditWriter bound to the
tmp DB so the global ``audit.writer`` singleton (already bound to the conftest
session DB) is never touched.
"""

from __future__ import annotations

import os
import sqlite3
import stat

import pytest

from backend.gateway import audit, audit_archive
from backend.shared import config
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_archive(tmp_path, monkeypatch):
    """Redirect the live audit DB + the archive dir at fresh tmp paths and
    hand back a private AuditWriter bound to the tmp DB."""
    db_path = tmp_path / "audit.db"
    arc_dir = tmp_path / "audit_archive"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db_path)
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", arc_dir)

    writer = audit.AuditWriter(path=db_path)
    return {"db_path": db_path, "arc_dir": arc_dir, "writer": writer}


def _write_rows(writer: audit.AuditWriter, n: int, start: int = 0) -> list[str]:
    """Write ``n`` audit rows; return their audit_ids in insertion order."""
    user = User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice",
    )
    ids = []
    for i in range(start, start + n):
        aid = writer.write(
            user=user,
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
        ids.append(aid)
    return ids


# ---------------------------------------------------------------------------
# 1. Sealing produces a segment + manifest with correct count + stable root.
# ---------------------------------------------------------------------------
def test_seal_creates_segment_and_manifest(tmp_archive):
    _write_rows(tmp_archive["writer"], 3)

    # rows pending before seal == 3
    assert audit_archive.archive_status()["rows_pending"] == 3

    result = audit_archive.seal_next_segment(now_iso="2026-01-01T00:00:00+00:00")
    assert result["sealed"] is True
    assert result["segment_index"] == 1
    assert result["row_count"] == 3

    arc = tmp_archive["arc_dir"]
    seg = arc / "segment-0001.jsonl"
    man = arc / "segment-0001.manifest.json"
    assert seg.exists() and man.exists()

    import json

    manifest = json.loads(man.read_text(encoding="utf-8"))
    assert manifest["row_count"] == 3
    assert manifest["row_offset_start"] == 0
    assert manifest["row_offset_end"] == 2
    assert manifest["prev_root"] == ""
    assert manifest["merkle_root"]  # non-empty
    assert manifest["sealed_at"] == "2026-01-01T00:00:00+00:00"

    # segment file has exactly 3 json lines
    lines = [line for line in seg.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3

    # rows pending after seal == 0
    assert audit_archive.archive_status()["rows_pending"] == 0


def test_merkle_root_is_stable(tmp_archive):
    """Same rows + same prev_root => identical recomputed root."""
    _write_rows(tmp_archive["writer"], 2)
    r1 = audit_archive.seal_next_segment(now_iso="2026-01-01T00:00:00+00:00")
    # Recompute independently from the segment rows.
    seg_rows = audit_archive._read_segment_rows(tmp_archive["arc_dir"] / "segment-0001.jsonl")
    recomputed = audit_archive._merkle_root(seg_rows, "")
    assert recomputed == r1["merkle_root"]


# ---------------------------------------------------------------------------
# 2. Idempotency — re-sealing with no new rows is a no-op.
# ---------------------------------------------------------------------------
def test_reseal_no_new_rows_is_noop(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    first = audit_archive.seal_next_segment()
    assert first["sealed"] is True

    second = audit_archive.seal_next_segment()
    assert second["sealed"] is False
    assert second["reason"] == "no_pending_rows"

    # Only one segment file exists.
    segs = list(tmp_archive["arc_dir"].glob("segment-*.jsonl"))
    assert len(segs) == 1


# ---------------------------------------------------------------------------
# 3. Second batch -> segment 2 chained to segment 1's root.
# ---------------------------------------------------------------------------
def test_second_batch_chains_to_first(tmp_archive):
    import json

    _write_rows(tmp_archive["writer"], 2)
    r1 = audit_archive.seal_next_segment()
    assert r1["segment_index"] == 1

    _write_rows(tmp_archive["writer"], 3, start=100)
    r2 = audit_archive.seal_next_segment()
    assert r2["segment_index"] == 2
    assert r2["row_count"] == 3
    assert r2["row_offset_start"] == 2  # after first 2 rows

    man2 = json.loads(
        (tmp_archive["arc_dir"] / "segment-0002.manifest.json").read_text(encoding="utf-8")
    )
    assert man2["prev_root"] == r1["merkle_root"]


# ---------------------------------------------------------------------------
# 4a. verify_archive returns ok=True on an intact archive.
# ---------------------------------------------------------------------------
def test_verify_ok_on_intact_archive(tmp_archive):
    _write_rows(tmp_archive["writer"], 3)
    audit_archive.seal_next_segment()
    _write_rows(tmp_archive["writer"], 2, start=50)
    audit_archive.seal_next_segment()

    result = audit_archive.verify_archive()
    assert result["ok"] is True, result["anomalies"]
    assert result["segments"] == 2
    assert result["rows_archived"] == 5
    assert result["anomalies"] == []


# ---------------------------------------------------------------------------
# 4b. Tampering the LIVE DB row after archival is detected.
# ---------------------------------------------------------------------------
def test_live_tamper_after_archive_detected(tmp_archive):
    ids = _write_rows(tmp_archive["writer"], 3)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    # Tamper a live audit row's row_hash directly via sqlite. The append-only
    # UPDATE trigger blocks normal UPDATEs, so a real attacker would have to
    # drop the trigger; we simulate that by dropping it then editing.
    conn = sqlite3.connect(tmp_archive["db_path"])
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute(
        "UPDATE audit SET row_hash = ? WHERE audit_id = ?",
        ("deadbeef" * 8, ids[1]),
    )
    conn.commit()
    conn.close()

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    types = {a["type"] for a in result["anomalies"]}
    assert "live_row_tampered" in types
    tampered = [a for a in result["anomalies"] if a["type"] == "live_row_tampered"]
    assert any(a["audit_id"] == ids[1] for a in tampered)


# ---------------------------------------------------------------------------
# 4c. Mutating a sealed segment file is detected (Merkle mismatch).
# ---------------------------------------------------------------------------
def test_segment_rowhash_mutation_detected(tmp_archive):
    _write_rows(tmp_archive["writer"], 3)
    audit_archive.seal_next_segment()

    seg = tmp_archive["arc_dir"] / "segment-0001.jsonl"
    os.chmod(seg, stat.S_IWUSR | stat.S_IRUSR)
    rows = audit_archive._read_segment_rows(seg)
    # Corrupt the first row's stored row_hash.
    rows[0]["row_hash"] = "00" * 32
    import json

    new_content = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    seg.write_text(new_content, encoding="utf-8")

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    types = {a["type"] for a in result["anomalies"]}
    # Changing the stored row_hash changes the Merkle leaf -> root mismatch,
    # and also breaks the live cross-check (archived hash != live hash).
    assert "merkle_root_mismatch" in types
    assert "live_row_tampered" in types


# ---------------------------------------------------------------------------
# 5. archive_status pending counts before/after seal.
# ---------------------------------------------------------------------------
def test_archive_status_pending_counts(tmp_archive):
    # Nothing written yet.
    st0 = audit_archive.archive_status()
    assert st0["rows_pending"] == 0
    assert st0["archived_rows"] == 0
    assert st0["segment_count"] == 0

    _write_rows(tmp_archive["writer"], 4)
    st1 = audit_archive.archive_status()
    assert st1["rows_pending"] == 4
    assert st1["live_rows_total"] == 4
    assert st1["archived_rows"] == 0

    audit_archive.seal_next_segment()
    st2 = audit_archive.archive_status()
    assert st2["rows_pending"] == 0
    assert st2["archived_rows"] == 4
    assert st2["segment_count"] == 1

    # Write 2 more -> pending == 2 again.
    _write_rows(tmp_archive["writer"], 2, start=200)
    st3 = audit_archive.archive_status()
    assert st3["rows_pending"] == 2
    assert st3["archived_rows"] == 4
