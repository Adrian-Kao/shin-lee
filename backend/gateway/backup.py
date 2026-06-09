"""Q20 — backup, restore, DR drill, and GDPR right-to-erasure.

docs/QUESTIONS.md Q20 demands a concrete disaster-recovery posture:

  * **RPO < 5 min, RTO < 1 hr** — recovery-point / recovery-time objectives.
  * **Hourly logical backup to offsite** of every stateful store.
  * **Audit hourly sync to immutable** storage (handled by ``audit_archive.py``
    — the WORM segments are themselves swept up by every snapshot here).
  * **QUARTERLY DR DRILL** — actually kill the primary and prove the standby
    comes up. This module's :func:`drill` is the software half of that drill:
    snapshot → restore into a throwaway dir → verify bytes AND verify the
    restored audit hash-chain is still intact. "We have backups" becomes
    "we PROVED we can restore a *valid* audit log."
  * **Retention 7yr**; **GDPR / 個資法 right-to-erasure** — BUT the audit log is
    *masked, not deleted* (Art. 17(3)(b) legal-hold / legal-claim exception).
    The audit rows store only hashes + a ``user_id`` label, never raw PII, so
    retaining them is compliant; the reversible-PII store (the masking mapping
    table) is what actually gets erased.

The stub table in CLAUDE.md reads: "Daily backup未實作 → cron ``pg_dump`` +
``aws s3 cp``; must upgrade to streaming replication before prod." This module
is the local POC of that cron job. It captures the SEMANTICS so production can
swap the storage target (a local ``BACKUP_DIR`` ↔ an S3 bucket / a Postgres
base-backup) without changing the verify/restore/erase logic.

Design choices that map onto production
---------------------------------------
* **SQLite online backup API** (``sqlite3.Connection.backup``) is used for every
  ``.db`` file rather than a raw file copy. A live SQLite DB being written
  concurrently can be *torn* by ``shutil.copy`` (you capture a half-applied
  transaction / a WAL mid-checkpoint). The backup API takes a consistent
  snapshot through the SQLite pager — the moral equivalent of ``pg_dump`` /
  ``pg_basebackup`` for Postgres.
* **manifest.json + sha256** per file is the integrity scheme. :func:`restore`
  re-hashes every restored file and compares against the manifest, so a
  bit-rotted or tampered backup is detected on restore (not silently served).
* **CLI** mirrors ``audit_archive.py`` / ``deadline.py``: a thin library that an
  ops cron calls. Deliberately NO HTTP endpoint (kept off ``main.py``).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Backup-set format version, recorded in every manifest. Bump if the layout or
# the hashing scheme ever changes so an old backup can be recognised + handled.
_BACKUP_SCHEMA_VERSION = "backup-v1"

_MANIFEST_FILENAME = "manifest.json"

# sha256 read chunk size (stream large files rather than slurping into memory).
_HASH_CHUNK = 1 << 20  # 1 MiB


# ---------------------------------------------------------------------------
# Lazy config resolution (honours conftest / test monkeypatching, exactly like
# audit_archive.py — config constants are mutated per-session by the harness).
# ---------------------------------------------------------------------------
def _cfg() -> Any:
    from backend.shared import config

    return config


def _backup_dir() -> Path:
    return Path(_cfg().BACKUP_DIR)


def _audit_db_path() -> Path:
    return Path(_cfg().AUDIT_DB_PATH)


def _mapping_db_path() -> Path:
    return Path(_cfg().MAPPING_DB_PATH)


def _patent_db_path() -> Optional[Path]:
    """PATENT_DB_PATH may not exist in a fresh checkout (RAG is in-memory in the
    POC). Returns the configured path regardless; the snapshot skips it when the
    file is absent."""
    p = getattr(_cfg(), "PATENT_DB_PATH", None)
    return Path(p) if p else None


def _archive_dir() -> Path:
    return Path(_cfg().AUDIT_ARCHIVE_DIR)


# ---------------------------------------------------------------------------
# Hash helpers.
# ---------------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# SQLite online backup (consistent, tear-free snapshot of a LIVE db).
# ---------------------------------------------------------------------------
def _sqlite_online_backup(src: Path, dst: Path) -> None:
    """Copy ``src`` SQLite DB to ``dst`` using the online backup API.

    Unlike ``shutil.copy``, this takes a transactionally-consistent page-level
    snapshot even while another connection is mid-write — the production-correct
    way to back up a live SQLite file. We open the source READ-ONLY (URI ``ro``)
    as defence in depth: a backup must never mutate the thing it is backing up.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{src.as_posix()}?mode=ro"
    src_conn = sqlite3.connect(uri, uri=True)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)  # full-database online backup
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


# ---------------------------------------------------------------------------
# Snapshot.
# ---------------------------------------------------------------------------
def _timestamp_id(now_iso: Optional[str]) -> tuple[str, str]:
    """Return ``(backup_id, created_at_iso)``.

    The backup_id is a filesystem-safe, lexically-sortable form of the
    timestamp (so ``sorted(BACKUP_DIR.iterdir())`` is chronological). ``now_iso``
    is injectable so tests can pin a deterministic id.
    """
    if now_iso is None:
        dt = datetime.now(timezone.utc)
        created_at = dt.isoformat()
    else:
        created_at = now_iso
        # Best-effort parse for normalisation; fall back to the raw string.
        try:
            dt = datetime.fromisoformat(now_iso)
        except ValueError:
            dt = datetime.now(timezone.utc)
    # 2026-06-08T12:34:56.789+00:00 -> 20260608T123456 (drop sub-seconds/tz)
    backup_id = dt.strftime("%Y%m%dT%H%M%S")
    return backup_id, created_at


def snapshot(now_iso: Optional[str] = None, prune_keep: Optional[int] = None) -> dict:
    """Back up every stateful store into a timestamped backup set.

    Stores captured:
      * ``AUDIT_DB_PATH``       (SQLite — online backup)
      * ``MAPPING_DB_PATH``     (SQLite — online backup)
      * ``PATENT_DB_PATH``      (SQLite — online backup; skipped if absent)
      * ``AUDIT_ARCHIVE_DIR``   (WORM segment tree — copied file-by-file; these
                                 are already-sealed immutable files, so a plain
                                 copy is consistent)

    Writes ``<BACKUP_DIR>/<backup_id>/manifest.json`` recording, per file:
    relative path, size, sha256 — plus ``backup_id``, ``created_at``, and the
    schema/version note. Returns the manifest dict (with an absolute
    ``backup_path``).

    When ``prune_keep`` is not None, retention pruning runs AFTER the new
    snapshot is durably written (so the fresh set always survives its own
    prune): all but the ``prune_keep`` most-recent sets are deleted and the
    result is surfaced under ``out["prune"]``. This mirrors the production cron
    "snapshot then sweep" cadence — keep it None to snapshot without pruning.
    """
    backup_id, created_at = _timestamp_id(now_iso)
    dest_root = _backup_dir() / backup_id
    dest_root.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []

    def _record(rel: str, abs_path: Path) -> None:
        files.append(
            {
                "path": rel,
                "size": abs_path.stat().st_size,
                "sha256": _sha256_file(abs_path),
            }
        )

    # --- SQLite stores via the online backup API ---
    db_targets = [
        ("audit.db", _audit_db_path()),
        ("mapping.db", _mapping_db_path()),
    ]
    patent = _patent_db_path()
    if patent is not None:
        db_targets.append(("patent.db", patent))

    for rel, src in db_targets:
        if src is None or not src.exists():
            continue  # store not materialised yet (fresh checkout / in-memory)
        dst = dest_root / rel
        _sqlite_online_backup(src, dst)
        _record(rel, dst)

    # --- WORM audit-archive tree (already-immutable sealed segments) ---
    arc = _archive_dir()
    if arc.exists():
        arc_dest_base = dest_root / "audit_archive"
        for src_file in sorted(arc.rglob("*")):
            if not src_file.is_file():
                continue
            rel_inside = src_file.relative_to(arc)
            dst_file = arc_dest_base / rel_inside
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            _record(f"audit_archive/{rel_inside.as_posix()}", dst_file)

    manifest = {
        "backup_id": backup_id,
        "created_at": created_at,
        "schema_version": _BACKUP_SCHEMA_VERSION,
        "note": (
            "Logical backup of all stateful stores. SQLite files captured via "
            "the online backup API for a tear-free snapshot; audit_archive WORM "
            "segments copied verbatim. RPO target < 5min (production: run hourly "
            "+ stream WAL); RTO target < 1hr."
        ),
        "files": files,
    }
    manifest_path = dest_root / _MANIFEST_FILENAME
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())

    out = dict(manifest)
    out["backup_path"] = str(dest_root)
    out["file_count"] = len(files)

    # Retention: snapshot-then-sweep. Runs only when the caller opted in; the
    # just-written set is the newest, so it always survives its own prune
    # (keep >= 1). keep == 0 would delete everything including this snapshot —
    # we treat that as a no-op here to avoid a surprising self-delete; an
    # operator who really wants to clear all backups calls prune(0) directly.
    if prune_keep is not None and prune_keep >= 1:
        out["prune"] = prune(prune_keep)
    return out


# ---------------------------------------------------------------------------
# Retention pruning (keep the N most-recent backup sets).
# ---------------------------------------------------------------------------
def _is_backup_set(path: Path) -> bool:
    """A directory is a backup set iff it holds a manifest.json."""
    return path.is_dir() and (path / _MANIFEST_FILENAME).exists()


def list_backups() -> list[str]:
    """Return all backup ids present under ``BACKUP_DIR``, oldest → newest.

    The backup_id is the lexically-sortable ``YYYYmmddTHHMMSS`` timestamp, so a
    plain ``sorted()`` is chronological. Only directories that actually contain a
    manifest are counted — a half-written / interrupted snapshot dir is ignored.
    """
    root = _backup_dir()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if _is_backup_set(p))


def prune(keep: int) -> dict:
    """Delete all but the ``keep`` most-recent backup sets (retention policy).

    Production Q20 retention is 7 years of hourly logical backups offsite; this
    is the local POC of the prune half of that cron: keep the N newest sets,
    delete the rest. The newest are determined by the lexically-sortable
    backup_id (timestamp), so this is robust without reading every manifest.

    ``keep`` must be >= 0. ``keep=0`` deletes every backup (used by an operator
    explicitly clearing a backup target; the CLI requires it to be passed
    deliberately). Returns ``{kept, pruned, pruned_ids, remaining_ids}``.

    A delete failure on one set (e.g. a file locked on Windows) is recorded but
    does NOT abort the prune of the others — retention is best-effort sweeping,
    not a transaction.
    """
    if keep < 0:
        raise ValueError("keep must be >= 0")
    all_ids = list_backups()  # oldest → newest
    if keep == 0:
        to_delete = list(all_ids)
        survivors = []
    else:
        to_delete = all_ids[:-keep] if len(all_ids) > keep else []
        survivors = all_ids[-keep:] if keep else []

    pruned_ids: list[str] = []
    errors: list[dict[str, str]] = []
    root = _backup_dir()
    for bid in to_delete:
        target = root / bid
        try:
            shutil.rmtree(target)
            pruned_ids.append(bid)
        except OSError as exc:  # pragma: no cover — platform-specific lock case
            errors.append({"backup_id": bid, "error": str(exc)})

    return {
        "kept": len(survivors),
        "pruned": len(pruned_ids),
        "pruned_ids": pruned_ids,
        "remaining_ids": list_backups(),
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Restore (with integrity verification).
# ---------------------------------------------------------------------------
def _load_manifest(backup_id: str) -> tuple[dict, Path]:
    backup_root = _backup_dir() / backup_id
    manifest_path = backup_root / _MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"backup {backup_id!r} not found (no manifest at {manifest_path})"
        )
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    return manifest, backup_root


def restore(backup_id: str, target_dir: str | Path) -> dict:
    """Restore a snapshot into ``target_dir``, verifying every file's sha256.

    Each file recorded in the manifest is copied into ``target_dir`` (preserving
    the relative layout), then re-hashed and compared to the manifest sha256.
    Any missing file or hash mismatch is reported as an anomaly (bit-rot /
    tamper detection) — we never silently restore a corrupted backup.

    Returns ``{backup_id, target_dir, files_verified, ok, anomalies:[...]}``.
    ``ok`` is True only when every file was present and hash-matched.
    """
    manifest, backup_root = _load_manifest(backup_id)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    anomalies: list[dict[str, Any]] = []
    files_verified = 0

    for entry in manifest.get("files", []):
        rel = entry["path"]
        expected = entry["sha256"]
        src = backup_root / rel
        if not src.exists():
            anomalies.append(
                {"type": "missing_backup_file", "path": rel, "source": str(src)}
            )
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        actual = _sha256_file(dst)
        if actual != expected:
            anomalies.append(
                {
                    "type": "sha256_mismatch",
                    "path": rel,
                    "expected": expected,
                    "actual": actual,
                }
            )
        else:
            files_verified += 1

    return {
        "backup_id": backup_id,
        "target_dir": str(target),
        "files_verified": files_verified,
        "ok": len(anomalies) == 0,
        "anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# DR drill — the headline feature.
# ---------------------------------------------------------------------------
def _restored_audit_db(target: Path) -> Optional[Path]:
    p = target / "audit.db"
    return p if p.exists() else None


def drill(now_iso: Optional[str] = None) -> dict:
    """Quarterly DR drill: snapshot live stores → restore → verify.

    Two independent proofs:

    1. **Byte integrity** — every restored file's sha256 matches the manifest
       (delegates to :func:`restore`).
    2. **Audit chain integrity AFTER restore** — the restored ``audit.db`` is
       opened with a fresh :class:`audit.AuditWriter` and run through
       ``verify_global_chain``. ``chain_intact`` is True only when that walk
       finds ZERO broken rows. This proves the backup is not merely the right
       bytes but a VALID, tamper-evident audit log that survives a restore.

    Returns a structured drill report::

        {
          "backup_id", "created_at",
          "files_verified", "files_total",
          "chain_intact", "chain": {...verify_global_chain output...},
          "rows", "rpo_estimate_seconds",
          "ok"  # True iff bytes verified AND chain intact
        }

    ``rpo_estimate_seconds`` is the age of the snapshot at drill time — the
    realised recovery-point for THIS drill (production target: < 300s).
    """
    from backend.gateway import audit

    snap = snapshot(now_iso=now_iso)
    backup_id = snap["backup_id"]
    files_total = snap["file_count"]

    tmp_root = Path(tempfile.mkdtemp(prefix=f"drill-{backup_id}-"))
    chain_intact = False
    chain_report: dict[str, Any] = {}
    rows = 0
    try:
        restore_result = restore(backup_id, tmp_root)
        files_verified = restore_result["files_verified"]
        bytes_ok = restore_result["ok"]

        restored_audit = _restored_audit_db(tmp_root)
        if restored_audit is not None:
            # Fresh writer bound to the RESTORED db file (never the live
            # singleton) so the chain walk reads the recovered copy.
            verifier = audit.AuditWriter(path=restored_audit)
            try:
                chain_report = verifier.verify_global_chain()
            finally:
                verifier._conn.close()
            broken = chain_report.get("broken", [])
            rows = int(chain_report.get("verified", 0))
            chain_intact = (len(broken) == 0) and rows >= 0
            # If there are zero rows the chain is vacuously intact; still mark
            # True so an empty-but-valid audit log doesn't fail the drill.
        else:
            # No audit DB restored at all → there's nothing to prove; treat as
            # not-intact so the drill flags the missing audit store loudly.
            chain_intact = False
            chain_report = {"reason": "no_audit_db_in_backup"}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # RPO estimate: how stale is this recovery point right now?
    rpo_seconds: Optional[float] = None
    try:
        created = datetime.fromisoformat(snap["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        rpo_seconds = max(
            0.0, (datetime.now(timezone.utc) - created).total_seconds()
        )
    except (ValueError, KeyError):
        rpo_seconds = None

    return {
        "backup_id": backup_id,
        "created_at": snap.get("created_at"),
        "files_verified": files_verified,
        "files_total": files_total,
        "chain_intact": chain_intact,
        "chain": chain_report,
        "rows": rows,
        "rpo_estimate_seconds": rpo_seconds,
        "ok": bool(bytes_ok and chain_intact),
    }


# ---------------------------------------------------------------------------
# GDPR / 個資法 right-to-erasure (with the audit legal-hold exception).
# ---------------------------------------------------------------------------
def _count_audit_rows_for_user(user_id: str) -> int:
    """Count audit rows labelled with ``user_id`` (read-only).

    These rows are RETAINED under the legal-hold exception; we count them only
    to document, in the erasure receipt, how many were kept. They hold hashes +
    a user_id label, never raw PII, so retaining them is compliant.
    """
    path = _audit_db_path()
    if not path.exists():
        return 0
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM audit WHERE user_id = ?", (user_id,)
        )
        return int(cur.fetchone()[0])
    except sqlite3.OperationalError:
        # audit table not created yet
        return 0
    finally:
        conn.close()


def _mapping_entries_for_user(user_id: str) -> list[tuple[str, str]]:
    """Rows in the masking mapping table attributable to ``user_id``.

    The mapping table is keyed by ``(tenant_id, placeholder)`` and does NOT
    carry a ``user_id`` column — the reversible map is tenant-scoped, not
    user-scoped (Q10). For the POC we treat the supplied identifier as either a
    ``tenant_id`` (erase that tenant's whole reversible map — the white-glove
    "offboard this client" path) OR, when it matches no tenant, a no-op that
    still reports cleanly. We return ``(tenant_id, placeholder)`` pairs that
    would be erased so a ``dry_run`` can show exactly what is at stake.
    """
    path = _mapping_db_path()
    if not path.exists():
        return []
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(
            "SELECT tenant_id, placeholder FROM mappings WHERE tenant_id = ?",
            (user_id,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def erase_user(user_id: str, *, dry_run: bool = False) -> dict:
    """GDPR / 個資法 right-to-erasure with the audit legal-hold exception.

    What is ERASED: the user's/tenant's reversible PII in the **masking mapping
    table** (``MAPPING_DB_PATH``). That table is the only mutable store holding
    the reversible map back to real identifiers; deleting those rows makes the
    placeholders permanently un-reversible — the PII is gone.

    What is RETAINED: **audit rows are NOT deleted**. They are kept under the
    legal-hold exception (GDPR Art. 17(3) / 個資法 legal-claim retention). This is
    compliant precisely because audit rows store only hashes + a ``user_id``
    label, never raw PII — there is no personal data IN the audit row to erase.
    (The audit table is also append-only at the DB level: an UPDATE/DELETE
    trigger would abort the write anyway. Erasure must therefore live in the
    mutable store, which is by design.)

    ``dry_run=True`` reports what *would* be removed without deleting anything —
    the safe default for an operator to review before committing an
    irreversible erase.

    Returns ``{user_id, dry_run, erased_mapping_entries, audit_rows_retained,
    note}``.
    """
    targeted = _mapping_entries_for_user(user_id)
    audit_retained = _count_audit_rows_for_user(user_id)

    erased = 0
    if not dry_run and targeted:
        path = _mapping_db_path()
        # Open read-write only to DELETE from the mutable mapping table. We do
        # NOT touch the audit DB here (it is append-only by trigger and retained
        # by policy).
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute(
                "DELETE FROM mappings WHERE tenant_id = ?", (user_id,)
            )
            conn.commit()
            erased = cur.rowcount if cur.rowcount is not None else len(targeted)
        finally:
            conn.close()
    elif dry_run:
        erased = 0  # nothing deleted; `targeted` reports what would be

    note = (
        "Erased reversible-PII mapping entries for the subject from the masking "
        "store. Audit rows are RETAINED under the legal-hold exception "
        "(GDPR Art.17(3) / 個資法 legal-claim retention): they contain only "
        "hashes + a user_id label, no raw PII, so retention is compliant. "
        "The mapping identifier is treated as a tenant_id (the reversible map "
        "is tenant-scoped per Q10)."
    )
    if dry_run:
        note = "DRY RUN — nothing deleted. " + note

    return {
        "user_id": user_id,
        "dry_run": dry_run,
        "erased_mapping_entries": erased,
        "would_erase_mapping_entries": len(targeted),
        "audit_rows_retained": audit_retained,
        "note": note,
    }


# ---------------------------------------------------------------------------
# CLI (mirrors audit_archive.py / deadline.py).
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    # Windows console is often cp950/cp1252; force utf-8 so 中文 notes + json
    # print cleanly (mirrors deadline.py / audit_archive CLI style).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    cmd = argv[1] if len(argv) > 1 else "drill"
    if cmd == "snapshot":
        # Optional retention: `snapshot --keep N` snapshots then sweeps.
        keep: Optional[int] = None
        if "--keep" in argv:
            i = argv.index("--keep")
            if i + 1 < len(argv):
                keep = int(argv[i + 1])
        result = snapshot(prune_keep=keep)
    elif cmd == "prune":
        if len(argv) < 3:
            print(
                "usage: python -m backend.gateway.backup prune <keep_n>",
                file=sys.stderr,
            )
            return 2
        result = prune(int(argv[2]))
    elif cmd == "list":
        result = {"backups": list_backups()}
    elif cmd == "restore":
        if len(argv) < 4:
            print(
                "usage: python -m backend.gateway.backup restore <backup_id> <target_dir>",
                file=sys.stderr,
            )
            return 2
        result = restore(argv[2], argv[3])
    elif cmd == "drill":
        result = drill()
    elif cmd == "erase":
        if len(argv) < 3:
            print(
                "usage: python -m backend.gateway.backup erase <user_id> [--dry-run]",
                file=sys.stderr,
            )
            return 2
        dry = "--dry-run" in argv[3:]
        result = erase_user(argv[2], dry_run=dry)
    else:
        print(
            f"unknown command {cmd!r}. usage: python -m backend.gateway.backup "
            f"snapshot [--keep N]|list|prune <keep_n>|restore <id> <dir>|"
            f"drill|erase <user_id> [--dry-run]",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
