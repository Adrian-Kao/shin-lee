"""Unit tests for the Q20 backup / restore / DR-drill / GDPR-erasure module
(backend/gateway/backup.py).

Every stateful path (AUDIT_DB_PATH / MAPPING_DB_PATH / PATENT_DB_PATH /
AUDIT_ARCHIVE_DIR / BACKUP_DIR) is monkeypatched onto fresh tmp paths, mirroring
how test_audit_archive.py redirects config. Audit rows are seeded via a private
AuditWriter bound to the tmp DB (never the global ``audit.writer`` singleton).
Mapping rows are seeded via a private MaskingStore bound to the tmp mapping DB.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.gateway import audit, audit_archive, backup, masking
from backend.shared import config
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_stores(tmp_path, monkeypatch):
    """Point every stateful store + the backup dir at fresh tmp paths.

    Returns the redirected paths plus a private AuditWriter / MaskingStore bound
    to the tmp DBs.
    """
    audit_db = tmp_path / "audit.db"
    mapping_db = tmp_path / "mapping.db"
    patent_db = tmp_path / "patent.db"
    arc_dir = tmp_path / "audit_archive"
    backup_dir = tmp_path / "backups"

    monkeypatch.setattr(config, "AUDIT_DB_PATH", audit_db)
    monkeypatch.setattr(config, "MAPPING_DB_PATH", mapping_db)
    monkeypatch.setattr(config, "PATENT_DB_PATH", patent_db)
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", arc_dir)
    monkeypatch.setattr(config, "BACKUP_DIR", backup_dir)

    writer = audit.AuditWriter(path=audit_db)
    store = masking.MaskingStore(path=mapping_db)
    return {
        "audit_db": audit_db,
        "mapping_db": mapping_db,
        "patent_db": patent_db,
        "arc_dir": arc_dir,
        "backup_dir": backup_dir,
        "writer": writer,
        "store": store,
    }


def _seed_audit(writer: audit.AuditWriter, n: int, user_id: str = "alice") -> list[str]:
    user = User(
        user_id=user_id,
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name=user_id,
    )
    ids = []
    for i in range(n):
        ids.append(
            writer.write(
                user=user,
                case_id=f"case-{i}",
                endpoint="/v1/analyze",
                request_payload={"q": i},
                response_payload={"a": i},
                masked_rules=["email"],
                model_used="mock",
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
                policy_decisions={"redacted": True},
            )
        )
    return ids


# ---------------------------------------------------------------------------
# 1. snapshot — manifest sha256s match the backed-up files; DB round-trips.
# ---------------------------------------------------------------------------
def test_snapshot_manifest_hashes_match_files(tmp_stores):
    _seed_audit(tmp_stores["writer"], 3)
    tmp_stores["store"].remember("tenant_a", "[EMAIL_AAAA1111]", "a@b.com", "email")

    result = backup.snapshot(now_iso="2026-06-08T10:00:00+00:00")
    assert result["backup_id"] == "20260608T100000"
    assert result["file_count"] >= 2  # at least audit.db + mapping.db

    backup_root = Path(result["backup_path"])
    manifest = json.loads((backup_root / "manifest.json").read_text(encoding="utf-8"))

    backed_rels = {f["path"] for f in manifest["files"]}
    assert "audit.db" in backed_rels
    assert "mapping.db" in backed_rels

    # Every manifest sha256 matches the actual file on disk.
    import hashlib

    for f in manifest["files"]:
        p = backup_root / f["path"]
        assert p.exists()
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == f["sha256"], f"hash mismatch for {f['path']}"
        assert f["size"] == p.stat().st_size

    # The audit.db captured via the sqlite backup API is a valid, queryable DB
    # with the same row count as the source (round-trip through the backup API).
    conn = sqlite3.connect(backup_root / "audit.db")
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        conn.close()
    assert n == 3


def test_snapshot_includes_worm_archive_tree(tmp_stores):
    _seed_audit(tmp_stores["writer"], 2)
    sealed = audit_archive.seal_next_segment(now_iso="2026-06-08T09:00:00+00:00")
    assert sealed["sealed"] is True

    result = backup.snapshot(now_iso="2026-06-08T10:00:00+00:00")
    backed_rels = {f["path"] for f in result["files"]}
    # The sealed segment + its manifest are swept into the backup set.
    assert any(r.startswith("audit_archive/") for r in backed_rels)
    assert any(r.endswith(".jsonl") for r in backed_rels)


# ---------------------------------------------------------------------------
# 2. restore — clean restore verifies OK; a flipped byte → hash mismatch.
# ---------------------------------------------------------------------------
def test_restore_verifies_ok(tmp_stores, tmp_path):
    _seed_audit(tmp_stores["writer"], 3)
    snap = backup.snapshot(now_iso="2026-06-08T10:00:00+00:00")

    target = tmp_path / "restore_target"
    result = backup.restore(snap["backup_id"], target)
    assert result["ok"] is True
    assert result["anomalies"] == []
    assert result["files_verified"] == snap["file_count"]
    assert (target / "audit.db").exists()


def test_restore_detects_corrupted_backup(tmp_stores, tmp_path):
    _seed_audit(tmp_stores["writer"], 3)
    snap = backup.snapshot(now_iso="2026-06-08T10:00:00+00:00")

    # Corrupt a backed-up file in place by flipping a byte (simulate bit-rot /
    # tampered backup), WITHOUT updating the manifest.
    backup_root = Path(snap["backup_path"])
    victim = backup_root / "audit.db"
    data = bytearray(victim.read_bytes())
    data[0] ^= 0xFF
    victim.write_bytes(bytes(data))

    target = tmp_path / "restore_target"
    result = backup.restore(snap["backup_id"], target)
    assert result["ok"] is False
    assert any(
        a["type"] == "sha256_mismatch" and a["path"] == "audit.db" for a in result["anomalies"]
    )


def test_restore_detects_missing_backup_file(tmp_stores, tmp_path):
    _seed_audit(tmp_stores["writer"], 2)
    snap = backup.snapshot(now_iso="2026-06-08T10:00:00+00:00")
    backup_root = Path(snap["backup_path"])
    (backup_root / "audit.db").unlink()

    result = backup.restore(snap["backup_id"], tmp_path / "t")
    assert result["ok"] is False
    assert any(a["type"] == "missing_backup_file" for a in result["anomalies"])


# ---------------------------------------------------------------------------
# 3. drill — healthy set ok=True/chain_intact=True; tampered audit → False.
# ---------------------------------------------------------------------------
def test_drill_healthy(tmp_stores):
    _seed_audit(tmp_stores["writer"], 5)
    report = backup.drill(now_iso="2026-06-08T10:00:00+00:00")
    assert report["ok"] is True
    assert report["chain_intact"] is True
    assert report["files_verified"] > 0
    assert report["rows"] == 5
    assert report["rpo_estimate_seconds"] is not None
    assert report["rpo_estimate_seconds"] >= 0


def test_drill_detects_tampered_audit_chain(tmp_stores):
    """If the LIVE audit DB is tampered (a row's hash forged) before the drill
    snapshot, the restored copy carries the tamper and verify_global_chain
    flags it: chain_intact must be False."""
    _seed_audit(tmp_stores["writer"], 4)

    # Tamper the live audit DB directly via sqlite, bypassing the append-only
    # trigger (DROP the triggers first — simulates a DBA-level compromise).
    conn = sqlite3.connect(tmp_stores["audit_db"])
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
        # Corrupt one row's request_hash so its recomputed row_hash no longer
        # matches the stored row_hash → chain break.
        conn.execute(
            "UPDATE audit SET request_hash = 'TAMPERED' "
            "WHERE rowid = (SELECT MIN(rowid) FROM audit)"
        )
        conn.commit()
    finally:
        conn.close()

    report = backup.drill(now_iso="2026-06-08T10:00:00+00:00")
    assert report["chain_intact"] is False
    assert report["ok"] is False
    assert len(report["chain"]["broken"]) >= 1


# ---------------------------------------------------------------------------
# 4. erase_user — removes tenant's mapping entries, retains audit rows.
# ---------------------------------------------------------------------------
def test_erase_user_removes_mapping_keeps_audit(tmp_stores):
    _seed_audit(tmp_stores["writer"], 3, user_id="alice")
    store = tmp_stores["store"]
    store.remember("tenant_a", "[EMAIL_AAAA1111]", "alice@apex.com", "email")
    store.remember("tenant_a", "[PHONE_BBBB2222]", "0912345678", "phone_tw")
    store.remember("tenant_b", "[EMAIL_CCCC3333]", "bob@beta.com", "email")

    # Erase tenant_a's reversible map (the white-glove offboard path).
    result = backup.erase_user("tenant_a", dry_run=False)
    assert result["erased_mapping_entries"] == 2
    # Audit rows for the same subject are RETAINED (legal-hold exception). The
    # audit rows are labelled by user_id; alice has 3.
    assert result["audit_rows_retained"] == 0  # erase id 'tenant_a' != user 'alice'

    # tenant_a's mapping rows are gone; tenant_b's remain.
    conn = sqlite3.connect(tmp_stores["mapping_db"])
    try:
        a = conn.execute("SELECT COUNT(*) FROM mappings WHERE tenant_id='tenant_a'").fetchone()[0]
        b = conn.execute("SELECT COUNT(*) FROM mappings WHERE tenant_id='tenant_b'").fetchone()[0]
    finally:
        conn.close()
    assert a == 0
    assert b == 1


def test_erase_user_audit_retained_count(tmp_stores):
    """When the erase identifier matches the audit user_id label, the retained
    count is reported (rows kept, not deleted)."""
    _seed_audit(tmp_stores["writer"], 3, user_id="alice")
    result = backup.erase_user("alice", dry_run=False)
    assert result["audit_rows_retained"] == 3
    # Audit rows still physically present (nothing deleted).
    conn = sqlite3.connect(tmp_stores["audit_db"])
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        conn.close()
    assert n == 3


def test_erase_user_dry_run_reports_without_deleting(tmp_stores):
    store = tmp_stores["store"]
    store.remember("tenant_a", "[EMAIL_AAAA1111]", "alice@apex.com", "email")
    store.remember("tenant_a", "[PHONE_BBBB2222]", "0912345678", "phone_tw")

    result = backup.erase_user("tenant_a", dry_run=True)
    assert result["dry_run"] is True
    assert result["erased_mapping_entries"] == 0
    assert result["would_erase_mapping_entries"] == 2

    # Nothing was actually deleted.
    conn = sqlite3.connect(tmp_stores["mapping_db"])
    try:
        n = conn.execute("SELECT COUNT(*) FROM mappings WHERE tenant_id='tenant_a'").fetchone()[0]
    finally:
        conn.close()
    assert n == 2
