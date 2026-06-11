"""Q13 — WORM archiver: seal audit rows into tamper-evident immutable segments.

The live audit log (``backend/gateway/audit.py``) is an append-only,
hash-chained SQLite table. That is solid against *casual* tampering (the
UPDATE/DELETE triggers abort), but Q13 (docs/QUESTIONS.md) additionally
requires periodic archival to **WORM** storage:

    "Append-only ... + WORM: 定期 archive 到 S3 Object Lock / Azure Immutable
     Blob; 保存期 7 年; 可匯出"

This module is a *local POC* of that hourly S3 Object Lock archiver. It
captures the WORM SEMANTICS so production can swap the storage target (a
directory ↔ an Object-Lock bucket) without changing the logic:

  * **Write-once** — rows are sealed into ``segment-<NNNN>.jsonl`` batches.
    Once a segment is written its files are flipped read-only (``chmod``),
    simulating Object Lock retention. Re-sealing the same range is refused.
  * **Sealed manifest** — each segment gets a ``segment-<NNNN>.manifest.json``
    recording the audit_id range, row count, sealed_at, a Merkle root over the
    segment's rows, and the *previous* segment's root. The manifests therefore
    form their own hash chain mirroring the row-level chain in the audit DB.
  * **Independently verifiable** — :func:`verify_archive` recomputes every
    segment's Merkle root from its rows, checks the segment chain, AND
    cross-checks each archived row against the live audit DB. A row whose live
    ``row_hash`` no longer matches what we sealed = post-archive tampering of
    the live DB, which the WORM copy now detects.

High-water mark
---------------
We track *how many* audit rows have been archived, as an integer persisted in
``<archive_dir>/_state.json`` (``{"archived_rows": N, "last_audit_id": "...",
"last_segment_root": "...", "segment_index": K}``). The audit table is strictly
append-only (insertion order == ``rowid`` ASC, never reused), so "the first N
rows in rowid order" is a stable, monotonic cursor — row N+1 is always the next
one to seal. We deliberately do NOT rely on ``rowid`` *values* (which could in
principle be non-contiguous if a future migration ever VACUUMed); we rely only
on the count + ordering, recomputed from the live DB each run, then sliced with
``OFFSET archived_rows``. The state file is the durable cursor; if it is lost,
:func:`verify_archive` can still re-derive the truth from the segment files
(each manifest records its absolute ``row_offset_start``/``row_count``), so the
state file is a fast-path cache, not the source of truth.

Production note: in S3, ``_state.json`` would itself be a versioned object (or
the high-water mark would be the max ``last_audit_id`` across listed manifest
objects). The directory layout here maps 1:1 onto an S3 prefix.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Coarse process-wide lock. Sealing is an ops/cron operation off the request
# hot path, so serialising the read-DB → write-segment → update-state sequence
# is fine and keeps the archive internally consistent under concurrent calls.
_lock = threading.Lock()

# Columns pulled from the live audit row, in the exact shape that feeds the
# audit writer's row_hash (see AuditWriter.write / verify_global_chain). We
# store these verbatim in the segment so verify_archive can (a) recompute the
# row_hash offline and (b) cross-check it against the live DB.
_AUDIT_SELECT = (
    "SELECT audit_id, timestamp_utc, user_id, tenant_id, case_id, "
    "       endpoint, request_hash, response_hash, prev_row_hash, row_hash "
    "FROM audit ORDER BY rowid ASC"
)

_STATE_FILENAME = "_state.json"


# ---------------------------------------------------------------------------
# Path / config resolution (lazy — honours conftest monkeypatching).
# ---------------------------------------------------------------------------
def _archive_dir() -> Path:
    """Resolve the archive directory lazily through config so a test that
    monkeypatches ``config.AUDIT_ARCHIVE_DIR`` is honoured (mirrors how
    audit_outbox resolves AUDIT_OUTBOX_PATH)."""
    from backend.shared import config

    return Path(config.AUDIT_ARCHIVE_DIR)


def _audit_db_path() -> Path:
    """Resolve the live audit DB path lazily through config (conftest
    redirects ``config.AUDIT_DB_PATH`` to a tmp file)."""
    from backend.shared import config

    return Path(config.AUDIT_DB_PATH)


def _state_path() -> Path:
    return _archive_dir() / _STATE_FILENAME


# ---------------------------------------------------------------------------
# Live audit DB read access (READ-ONLY — we never write the audit DB here).
# ---------------------------------------------------------------------------
def _read_live_rows() -> list[dict[str, Any]]:
    """Read every audit row in insertion (rowid ASC) order as plain dicts.

    Opens a fresh, short-lived connection (the live AuditWriter owns its own
    long-lived connection; we deliberately do NOT touch it). We open in URI
    read-only mode so this module can never mutate the audit log — defence in
    depth on top of the append-only triggers.
    """
    path = _audit_db_path()
    if not path.exists():
        return []
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(_AUDIT_SELECT)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        conn.close()


def _live_row_hash_index() -> dict[str, str]:
    """Map audit_id -> current live row_hash, for the cross-check pass."""
    return {r["audit_id"]: r["row_hash"] for r in _read_live_rows()}


# ---------------------------------------------------------------------------
# Merkle / chain primitives.
# ---------------------------------------------------------------------------
def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _row_leaf(row: dict[str, Any]) -> str:
    """Leaf hash for a single archived row.

    We hash the row's recorded ``row_hash`` (which itself already commits to
    the row's content + its place in the live chain). Binding the Merkle leaf
    to the live row_hash means any later mutation of the live row content
    changes its row_hash, which changes the leaf, which changes the segment
    root — so the cross-check and the recomputed-root check are mutually
    reinforcing.
    """
    return _sha256_hex("leaf:" + (row["row_hash"] or ""))


def _merkle_root(rows: list[dict[str, Any]], prev_root: str) -> str:
    """Compute a chained Merkle root over ``rows`` seeded with ``prev_root``.

    A binary Merkle tree over the per-row leaf hashes; odd nodes are promoted
    (duplicated) at each level. The previous segment's root is folded in as the
    seed so each segment root commits to the entire archive history before it
    (segment-level hash chain mirroring the row-level chain). An empty segment
    is never sealed, so ``rows`` is always non-empty here.
    """
    leaves = [_row_leaf(r) for r in rows]
    # Fold the previous root in as a synthetic left-most leaf so the root
    # chains to history. (prev_root is "" for the first segment.)
    level = [_sha256_hex("seed:" + prev_root)] + leaves
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left  # promote odd
            nxt.append(_sha256_hex(left + right))
        level = nxt
    return level[0]


# ---------------------------------------------------------------------------
# State (high-water mark) persistence.
# ---------------------------------------------------------------------------
def _read_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {
            "archived_rows": 0,
            "segment_index": 0,
            "last_audit_id": None,
            "last_segment_root": "",
        }
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_state(state: dict[str, Any]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # The state file is rewritten each seal, so (unlike segments) it is NOT
    # made read-only. Write atomically via a temp file + replace so a crash
    # mid-write can't leave a truncated high-water mark.
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Immutability simulation (Object Lock).
# ---------------------------------------------------------------------------
def _make_read_only(p: Path) -> None:
    """Flip a file to read-only to simulate S3 Object Lock retention.

    On POSIX this clears the write bits; on Windows it sets FILE_ATTRIBUTE_
    READONLY (os.chmod honours stat.S_IWRITE there). Production swaps this for
    an Object Lock retention period on the uploaded object.
    """
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except (OSError, NotImplementedError):
        # Best-effort: some filesystems (e.g. certain mounts) reject chmod.
        # The refuse-to-overwrite guard below is the real enforcement; chmod
        # is the belt to that braces.
        pass


def _seg_basename(index: int) -> str:
    return f"segment-{index:04d}"


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------
def seal_next_segment(now_iso: str | None = None) -> dict:
    """Seal all not-yet-archived audit rows into one new immutable segment.

    Returns a dict describing what happened. When there are no pending rows
    this is a no-op (``{"sealed": False, "reason": "no_pending_rows", ...}``)
    so the cron job is naturally idempotent — re-running with no new rows does
    NOT create an empty/duplicate segment.

    ``now_iso`` lets the caller inject the seal timestamp (for deterministic
    tests / replaying); defaults to ``datetime.now(timezone.utc)``.
    """
    if now_iso is None:
        now_iso = datetime.now(UTC).isoformat()

    with _lock:
        adir = _archive_dir()
        adir.mkdir(parents=True, exist_ok=True)

        state = _read_state()
        archived = int(state.get("archived_rows", 0))
        seg_index = int(state.get("segment_index", 0))
        prev_root = state.get("last_segment_root", "") or ""

        live_rows = _read_live_rows()
        total = len(live_rows)

        if archived >= total:
            return {
                "sealed": False,
                "reason": "no_pending_rows",
                "segment_index": seg_index,
                "archived_rows": archived,
                "rows_pending": 0,
            }

        pending = live_rows[archived:]  # slice past the high-water mark
        new_index = seg_index + 1
        basename = _seg_basename(new_index)
        seg_path = adir / f"{basename}.jsonl"
        manifest_path = adir / f"{basename}.manifest.json"

        # Idempotency / WORM guard: refuse to overwrite an existing sealed
        # segment. If either file already exists the range was already sealed
        # (or a partial seal crashed) — do not double-archive.
        if seg_path.exists() or manifest_path.exists():
            return {
                "sealed": False,
                "reason": "segment_already_exists",
                "segment_index": new_index,
                "path": str(seg_path),
            }

        # Compute the segment Merkle root (chained off the previous root).
        seg_root = _merkle_root(pending, prev_root)

        # --- write the segment file (append-only JSONL) ---
        # Build content first, write once, fsync, then flip read-only.
        with seg_path.open("w", encoding="utf-8") as fh:
            for i, row in enumerate(pending):
                record = {
                    "row_offset": archived + i,  # absolute index in the log
                    "audit_id": row["audit_id"],
                    "timestamp_utc": row["timestamp_utc"],
                    "user_id": row["user_id"],
                    "tenant_id": row["tenant_id"],
                    "case_id": row["case_id"],
                    "endpoint": row["endpoint"],
                    "request_hash": row["request_hash"],
                    "response_hash": row["response_hash"],
                    "prev_row_hash": row["prev_row_hash"],
                    "row_hash": row["row_hash"],
                }
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())

        manifest = {
            "segment_index": new_index,
            "row_offset_start": archived,
            "row_offset_end": archived + len(pending) - 1,
            "row_count": len(pending),
            "audit_id_first": pending[0]["audit_id"],
            "audit_id_last": pending[-1]["audit_id"],
            "sealed_at": now_iso,
            "merkle_root": seg_root,
            "prev_root": prev_root,
            "segment_file": seg_path.name,
            "algo": "sha256-chained-merkle-v1",
        }
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())

        # Flip both files read-only AFTER content is durable (Object Lock sim).
        _make_read_only(seg_path)
        _make_read_only(manifest_path)

        # Advance the high-water mark durably.
        _write_state(
            {
                "archived_rows": archived + len(pending),
                "segment_index": new_index,
                "last_audit_id": pending[-1]["audit_id"],
                "last_segment_root": seg_root,
            }
        )

        return {
            "sealed": True,
            "segment_index": new_index,
            "row_count": len(pending),
            "row_offset_start": archived,
            "row_offset_end": archived + len(pending) - 1,
            "merkle_root": seg_root,
            "prev_root": prev_root,
            "segment_file": str(seg_path),
            "manifest_file": str(manifest_path),
            "sealed_at": now_iso,
        }


def _load_segments() -> list[tuple[dict, Path, Path]]:
    """Discover sealed segments, sorted by segment_index.

    Returns ``[(manifest_dict, manifest_path, segment_path), ...]``.
    """
    adir = _archive_dir()
    if not adir.exists():
        return []
    out: list[tuple[dict, Path, Path]] = []
    for manifest_path in sorted(adir.glob("segment-*.manifest.json")):
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        seg_path = adir / manifest.get("segment_file", "")
        out.append((manifest, manifest_path, seg_path))
    out.sort(key=lambda t: t[0].get("segment_index", 0))
    return out


def _read_segment_rows(seg_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with seg_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def verify_archive() -> dict:
    """Independently verify the WORM archive.

    Three checks, all offline-recomputed (we trust nothing recorded blindly):

    1. **Merkle root** — recompute each segment's root from its own rows and
       its recorded ``prev_root``; flag a mismatch (segment file was mutated
       or a root was forged).
    2. **Segment chain** — each manifest's ``prev_root`` must equal the
       previous segment's recomputed root, and offsets must be contiguous
       (no gap / overlap between segments). The first segment must have
       ``prev_root == ""``.
    3. **Live cross-check** — every archived row's ``row_hash`` must still
       match the live audit DB's current row_hash for that audit_id. A
       mismatch = the live DB was tampered with *after* archival; a missing
       live row = the live row was deleted (the append-only trigger should
       prevent this, but the WORM copy catches it if the trigger is bypassed).

    Returns ``{segments, rows_archived, ok, anomalies:[...]}``.
    """
    segments = _load_segments()
    anomalies: list[dict[str, Any]] = []
    rows_archived = 0

    live_index = _live_row_hash_index()

    expected_prev_root = ""
    expected_offset = 0
    for manifest, _manifest_path, seg_path in segments:
        seg_index = manifest.get("segment_index")

        if not seg_path.exists():
            anomalies.append(
                {"type": "missing_segment_file", "segment_index": seg_index, "path": str(seg_path)}
            )
            # Can't verify rows of a missing file; keep chain expectation as-is
            # so subsequent segments still get checked against the prior root.
            continue

        seg_rows = _read_segment_rows(seg_path)
        rows_archived += len(seg_rows)

        # --- (2) chain: prev_root linkage ---
        recorded_prev = manifest.get("prev_root", "")
        if recorded_prev != expected_prev_root:
            anomalies.append(
                {
                    "type": "segment_chain_break",
                    "segment_index": seg_index,
                    "expected_prev_root": expected_prev_root,
                    "recorded_prev_root": recorded_prev,
                }
            )

        # --- (2) chain: offset contiguity ---
        recorded_start = manifest.get("row_offset_start")
        if recorded_start != expected_offset:
            anomalies.append(
                {
                    "type": "segment_offset_gap",
                    "segment_index": seg_index,
                    "expected_offset": expected_offset,
                    "recorded_offset": recorded_start,
                }
            )

        # --- row_count consistency ---
        if manifest.get("row_count") != len(seg_rows):
            anomalies.append(
                {
                    "type": "row_count_mismatch",
                    "segment_index": seg_index,
                    "manifest_row_count": manifest.get("row_count"),
                    "actual_rows": len(seg_rows),
                }
            )

        # --- (1) recompute Merkle root from the segment's own rows ---
        recomputed_root = _merkle_root(seg_rows, recorded_prev)
        recorded_root = manifest.get("merkle_root")
        if recomputed_root != recorded_root:
            anomalies.append(
                {
                    "type": "merkle_root_mismatch",
                    "segment_index": seg_index,
                    "recorded_root": recorded_root,
                    "recomputed_root": recomputed_root,
                }
            )

        # --- (3) cross-check each row against the live DB ---
        for row in seg_rows:
            aid = row.get("audit_id")
            live_hash = live_index.get(aid)
            if live_hash is None:
                anomalies.append(
                    {"type": "live_row_missing", "segment_index": seg_index, "audit_id": aid}
                )
            elif live_hash != row.get("row_hash"):
                anomalies.append(
                    {
                        "type": "live_row_tampered",
                        "segment_index": seg_index,
                        "audit_id": aid,
                        "archived_row_hash": row.get("row_hash"),
                        "live_row_hash": live_hash,
                    }
                )

        # advance chain expectations using the RECOMPUTED root (so a forged
        # manifest root can't quietly re-anchor the rest of the chain)
        expected_prev_root = recomputed_root
        expected_offset = (recorded_start if recorded_start is not None else expected_offset) + len(
            seg_rows
        )

    return {
        "segments": len(segments),
        "rows_archived": rows_archived,
        "ok": len(anomalies) == 0,
        "anomalies": anomalies,
    }


def archive_status() -> dict:
    """Ops signal: high-water mark, segment count, rows pending in live DB."""
    state = _read_state()
    archived = int(state.get("archived_rows", 0))
    total = len(_read_live_rows())
    segments = _load_segments()
    return {
        "archived_rows": archived,
        "last_audit_id": state.get("last_audit_id"),
        "last_segment_root": state.get("last_segment_root", ""),
        "segment_count": len(segments),
        "live_rows_total": total,
        "rows_pending": max(0, total - archived),
        "archive_dir": str(_archive_dir()),
    }


# ---------------------------------------------------------------------------
# CLI (mirrors deadline.py / element_table.py style).
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "seal":
        result = seal_next_segment()
    elif cmd == "verify":
        result = verify_archive()
    elif cmd == "status":
        result = archive_status()
    else:
        print(
            f"unknown command {cmd!r}. usage: "
            f"python -m backend.gateway.audit_archive seal|verify|status",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
