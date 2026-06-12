"""Q13 — WORM archiver: seal audit rows into tamper-evident immutable segments.

The live audit log (``backend/gateway/audit.py``) is an append-only,
hash-chained table (SQLite or Postgres — ``AUDIT_BACKEND``). That is solid
against *casual* tampering (the UPDATE/DELETE triggers abort), but Q13
(docs/QUESTIONS.md) additionally requires periodic archival to **WORM**
storage:

    "Append-only ... + WORM: 定期 archive 到 S3 Object Lock / Azure Immutable
     Blob; 保存期 7 年; 可匯出"

Two storage targets are supported (``ARCHIVE_BACKEND``):

  * ``local`` (default) — a local directory whose sealed files are flipped
    read-only (the original POC of Object Lock semantics; zero infra).
  * ``s3``    — a real S3-compatible Object Lock bucket (MinIO in the
    delivery stack — compose service on :19000; AWS S3 in production).
    Segments + manifests are uploaded with a per-object retention
    (``ARCHIVE_S3_RETENTION_MODE`` GOVERNANCE|COMPLIANCE +
    ``ARCHIVE_S3_RETENTION_DAYS``), so the object store itself refuses
    deletion/version-removal until the retain-until date. The bucket MUST be
    created with Object Lock enabled (versioning implied) — one-shot init:
    ``python scripts/init_minio.py``.

Both targets capture the same WORM SEMANTICS, so flipping the knob changes
the storage, never the logic:

  * **Write-once** — rows are sealed into ``segment-<NNNN>.jsonl`` batches.
    Local: files are flipped read-only after fsync. S3: objects carry an
    Object Lock retention; an overwrite can only ADD a version (the sealed
    version stays retrievable) and deleting the sealed version is refused by
    the store. Re-sealing the same range is refused in both modes.
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
``_state.json`` (``{"archived_rows": N, "last_audit_id": "...",
"last_segment_root": "...", "segment_index": K}``) — a file in the archive dir
(local) or a plain versioned object in the bucket (s3; deliberately NOT
object-locked, it must stay rewritable). The audit table is strictly
append-only (insertion order == ``rowid``/``row_seq`` ASC, never reused), so
"the first N rows in insertion order" is a stable, monotonic cursor — row N+1
is always the next one to seal. We deliberately do NOT rely on rowid *values*
(which could in principle be non-contiguous if a future migration ever
VACUUMed); we rely only on the count + ordering, recomputed from the live DB
each run, then sliced with ``OFFSET archived_rows``. The state file is the
durable cursor; if it is lost, :func:`verify_archive` can still re-derive the
truth from the segment files (each manifest records its absolute
``row_offset_start``/``row_count``), so the state file is a fast-path cache,
not the source of truth.

Live-DB access goes through :func:`backend.gateway.audit.read_live_rows`,
which is backend-aware (SQLite read-only URI / Postgres READ ONLY tx) — this
module never opens the audit store directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.gateway import audit

# Coarse process-wide lock. Sealing is an ops/cron operation off the request
# hot path, so serialising the read-DB → write-segment → update-state sequence
# is fine and keeps the archive internally consistent under concurrent calls.
_lock = threading.Lock()

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


def _backend() -> str:
    """``local`` | ``s3`` — resolved lazily so tests can monkeypatch
    ``config.settings.ARCHIVE_BACKEND`` per-test."""
    from backend.shared import config

    return getattr(config.settings, "ARCHIVE_BACKEND", "local")


def _state_path() -> Path:
    return _archive_dir() / _STATE_FILENAME


# ---------------------------------------------------------------------------
# Live audit DB read access (READ-ONLY — we never write the audit store here).
# ---------------------------------------------------------------------------
def _read_live_rows() -> list[dict[str, Any]]:
    """Every audit row in insertion order, via the backend-aware read-only
    entry point in audit.py (SQLite ``mode=ro`` URI / Postgres READ ONLY tx)."""
    return audit.read_live_rows()


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
# S3 / MinIO target (ARCHIVE_BACKEND=s3).
# ---------------------------------------------------------------------------
def _s3_client():
    """Build a boto3 S3 client against the configured endpoint (MinIO/AWS).

    Lazy import: boto3 is only required when ARCHIVE_BACKEND=s3. Settings are
    read per call so tests can monkeypatch bucket/endpoint per-test.
    """
    import boto3
    from botocore.config import Config

    from backend.shared.config import settings

    return boto3.client(
        "s3",
        endpoint_url=settings.ARCHIVE_S3_ENDPOINT,
        aws_access_key_id=settings.ARCHIVE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.ARCHIVE_S3_SECRET_KEY,
        region_name=settings.ARCHIVE_S3_REGION,
        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
    )


def _s3_bucket() -> str:
    from backend.shared.config import settings

    return settings.ARCHIVE_S3_BUCKET


def _s3_object_exists(client, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _s3_get_text(client, bucket: str, key: str) -> str | None:
    """Fetch an object's body as utf-8 text; None when the key is absent."""
    from botocore.exceptions import ClientError

    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _s3_put_locked(client, bucket: str, key: str, content: str) -> None:
    """Upload one sealed artefact WITH Object Lock retention.

    The retain-until date is now + ARCHIVE_S3_RETENTION_DAYS, in the
    configured mode (GOVERNANCE by default — a privileged principal can
    bypass with an explicit governance-bypass header; COMPLIANCE cannot be
    bypassed by anyone until expiry, which is the production posture for the
    7-year Q13 retention). Requires the bucket to have Object Lock enabled
    (scripts/init_minio.py creates it that way).
    """
    from botocore.exceptions import ClientError

    from backend.shared.config import settings

    retain_until = datetime.now(UTC) + timedelta(days=settings.ARCHIVE_S3_RETENTION_DAYS)
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
            ObjectLockMode=settings.ARCHIVE_S3_RETENTION_MODE,
            ObjectLockRetainUntilDate=retain_until,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "NoSuchBucket":
            raise RuntimeError(
                f"WORM bucket {bucket!r} does not exist at the configured "
                f"endpoint. Create it (Object Lock enabled) with: "
                f"python scripts/init_minio.py"
            ) from exc
        if code == "InvalidRequest":
            raise RuntimeError(
                f"put_object with Object Lock retention was refused for "
                f"bucket {bucket!r} — the bucket was probably created WITHOUT "
                f"Object Lock. Recreate it via: python scripts/init_minio.py"
            ) from exc
        raise


def _s3_put_plain(client, bucket: str, key: str, content: str) -> None:
    """Upload a NON-locked object (the rewritable _state.json cursor)."""
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )


# ---------------------------------------------------------------------------
# State (high-water mark) persistence.
# ---------------------------------------------------------------------------
_DEFAULT_STATE: dict[str, Any] = {
    "archived_rows": 0,
    "segment_index": 0,
    "last_audit_id": None,
    "last_segment_root": "",
}


def _read_state() -> dict[str, Any]:
    if _backend() == "s3":
        text = _s3_get_text(_s3_client(), _s3_bucket(), _STATE_FILENAME)
        if text is None:
            return dict(_DEFAULT_STATE)
        return json.loads(text)
    p = _state_path()
    if not p.exists():
        return dict(_DEFAULT_STATE)
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_state(state: dict[str, Any]) -> None:
    if _backend() == "s3":
        # S3 PUT is atomic per object; the bucket is versioned (Object Lock
        # implies versioning) so every previous cursor value stays recoverable.
        _s3_put_plain(
            _s3_client(),
            _s3_bucket(),
            _STATE_FILENAME,
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        )
        return
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
# Immutability simulation (local Object Lock).
# ---------------------------------------------------------------------------
def _make_read_only(p: Path) -> None:
    """Flip a file to read-only to simulate S3 Object Lock retention.

    On POSIX this clears the write bits; on Windows it sets FILE_ATTRIBUTE_
    READONLY (os.chmod honours stat.S_IWRITE there). Production swaps this for
    an Object Lock retention period on the uploaded object (= ARCHIVE_BACKEND=s3).
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
        backend = _backend()

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
        seg_name = f"{basename}.jsonl"
        manifest_name = f"{basename}.manifest.json"

        # Idempotency / WORM guard: refuse to overwrite an existing sealed
        # segment. If either artefact already exists the range was already
        # sealed (or a partial seal crashed) — do not double-archive.
        if backend == "s3":
            client = _s3_client()
            bucket = _s3_bucket()
            if _s3_object_exists(client, bucket, seg_name) or _s3_object_exists(
                client, bucket, manifest_name
            ):
                return {
                    "sealed": False,
                    "reason": "segment_already_exists",
                    "segment_index": new_index,
                    "path": f"s3://{bucket}/{seg_name}",
                }
        else:
            adir = _archive_dir()
            adir.mkdir(parents=True, exist_ok=True)
            seg_path = adir / seg_name
            manifest_path = adir / manifest_name
            if seg_path.exists() or manifest_path.exists():
                return {
                    "sealed": False,
                    "reason": "segment_already_exists",
                    "segment_index": new_index,
                    "path": str(seg_path),
                }

        # Compute the segment Merkle root (chained off the previous root).
        seg_root = _merkle_root(pending, prev_root)

        # --- build the segment content (append-only JSONL) ---
        seg_lines: list[str] = []
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
            seg_lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        seg_content = "\n".join(seg_lines) + "\n"

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
            "segment_file": seg_name,
            "algo": "sha256-chained-merkle-v1",
        }
        manifest_content = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)

        if backend == "s3":
            # Object Lock retention IS the immutability: the store refuses to
            # delete the sealed version until retain-until. Segment first,
            # manifest second — a crash in between leaves a discoverable,
            # re-sealable gap (the existence guard above refuses index reuse,
            # so an operator resolves it explicitly rather than silently).
            _s3_put_locked(client, bucket, seg_name, seg_content)
            _s3_put_locked(client, bucket, manifest_name, manifest_content)
            seg_location = f"s3://{bucket}/{seg_name}"
            manifest_location = f"s3://{bucket}/{manifest_name}"
        else:
            # Build content first, write once, fsync, then flip read-only.
            with seg_path.open("w", encoding="utf-8") as fh:
                fh.write(seg_content)
                fh.flush()
                os.fsync(fh.fileno())
            with manifest_path.open("w", encoding="utf-8") as fh:
                fh.write(manifest_content)
                fh.flush()
                os.fsync(fh.fileno())
            # Flip both read-only AFTER content is durable (Object Lock sim).
            _make_read_only(seg_path)
            _make_read_only(manifest_path)
            seg_location = str(seg_path)
            manifest_location = str(manifest_path)

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
            "segment_file": seg_location,
            "manifest_file": manifest_location,
            "sealed_at": now_iso,
        }


def _load_segments() -> list[tuple[dict, Any, Any]]:
    """Discover sealed segments, sorted by segment_index.

    Returns ``[(manifest_dict, manifest_ref, segment_ref), ...]`` where the
    refs are :class:`Path` objects (local) or object keys (s3).
    """
    if _backend() == "s3":
        client = _s3_client()
        bucket = _s3_bucket()
        out_s3: list[tuple[dict, Any, Any]] = []
        paginator = client.get_paginator("list_objects_v2")
        try:
            pages = paginator.paginate(Bucket=bucket, Prefix="segment-")
            keys = [
                obj["Key"]
                for page in pages
                for obj in page.get("Contents", [])
                if obj["Key"].endswith(".manifest.json")
            ]
        except client.exceptions.NoSuchBucket:
            return []
        for key in sorted(keys):
            text = _s3_get_text(client, bucket, key)
            if text is None:
                continue
            manifest = json.loads(text)
            out_s3.append((manifest, key, manifest.get("segment_file", "")))
        out_s3.sort(key=lambda t: t[0].get("segment_index", 0))
        return out_s3

    adir = _archive_dir()
    if not adir.exists():
        return []
    out: list[tuple[dict, Any, Any]] = []
    for manifest_path in sorted(adir.glob("segment-*.manifest.json")):
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        seg_path = adir / manifest.get("segment_file", "")
        out.append((manifest, manifest_path, seg_path))
    out.sort(key=lambda t: t[0].get("segment_index", 0))
    return out


def _parse_segment_lines(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _read_segment_rows(seg_path: Path) -> list[dict[str, Any]]:
    with seg_path.open("r", encoding="utf-8") as fh:
        return _parse_segment_lines(fh.read())


def _segment_rows_or_none(seg_ref: Any) -> list[dict[str, Any]] | None:
    """Fetch a sealed segment's rows; ``None`` when the artefact is missing."""
    if _backend() == "s3":
        text = _s3_get_text(_s3_client(), _s3_bucket(), str(seg_ref))
        if text is None:
            return None
        return _parse_segment_lines(text)
    seg_path = Path(seg_ref)
    if not seg_path.exists():
        return None
    return _read_segment_rows(seg_path)


def verify_archive() -> dict:
    """Independently verify the WORM archive.

    Three checks, all offline-recomputed (we trust nothing recorded blindly):

    1. **Merkle root** — recompute each segment's root from its own rows and
       its recorded ``prev_root``; flag a mismatch (segment file was mutated
       or a root was forged). In s3 mode the rows come back from the bucket,
       so this also catches a tampered *latest version* of a sealed object
       (Object Lock keeps the original version retrievable as evidence).
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
    for manifest, _manifest_ref, seg_ref in segments:
        seg_index = manifest.get("segment_index")

        seg_rows = _segment_rows_or_none(seg_ref)
        if seg_rows is None:
            anomalies.append(
                {"type": "missing_segment_file", "segment_index": seg_index, "path": str(seg_ref)}
            )
            # Can't verify rows of a missing file; keep chain expectation as-is
            # so subsequent segments still get checked against the prior root.
            continue

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
    if _backend() == "s3":
        location = f"s3://{_s3_bucket()}"
    else:
        location = str(_archive_dir())
    return {
        "archived_rows": archived,
        "last_audit_id": state.get("last_audit_id"),
        "last_segment_root": state.get("last_segment_root", ""),
        "segment_count": len(segments),
        "live_rows_total": total,
        "rows_pending": max(0, total - archived),
        "archive_dir": location,
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
