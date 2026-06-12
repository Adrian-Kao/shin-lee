"""Q13 — WORM archive on a real S3 Object Lock target (``ARCHIVE_BACKEND=s3``).

Runs against the compose MinIO (S3 API on :19000 — ``docker compose up -d
minio``). Mirrors the Qdrant/Postgres gating pattern: every test skips cleanly
when MinIO (or boto3) is absent, so CI without containers stays green.

Each test creates its OWN bucket with Object Lock enabled (versioning
implied), uses GOVERNANCE mode with a 1-day retention so teardown can clean up
via the governance bypass (COMPLIANCE objects would be undeletable until
expiry — the production posture, but hostile to a dev MinIO).

What must hold:

  * sealing uploads segment + manifest objects carrying Object Lock retention;
  * ``verify_archive`` pulls everything back from the bucket and re-verifies
    the Merkle/segment chain + the live-DB cross-check;
  * WORM semantics — deleting a sealed object VERSION without the governance
    bypass is refused by the store, and an overwrite only ADDS a version (the
    sealed bytes stay retrievable) while verify flags the tampered latest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.gateway import audit, audit_archive
from backend.shared import config
from backend.shared.config import settings
from backend.shared.models import User, UserRole

boto3 = pytest.importorskip("boto3")

from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.ARCHIVE_S3_ENDPOINT,
        aws_access_key_id=settings.ARCHIVE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.ARCHIVE_S3_SECRET_KEY,
        region_name=settings.ARCHIVE_S3_REGION,
        config=Config(connect_timeout=2, read_timeout=10, retries={"max_attempts": 1}),
    )


def _minio_or_skip():
    client = _client()
    try:
        client.list_buckets()
    except Exception as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"MinIO not reachable at {settings.ARCHIVE_S3_ENDPOINT}: {exc}")
    return client


def _nuke_bucket(client, bucket: str) -> None:
    """Best-effort teardown: remove every version (governance bypass) + bucket."""
    try:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
                client.delete_object(
                    Bucket=bucket,
                    Key=v["Key"],
                    VersionId=v["VersionId"],
                    BypassGovernanceRetention=True,
                )
        client.delete_bucket(Bucket=bucket)
    except Exception:  # pragma: no cover - teardown must never fail the test
        pass


@pytest.fixture()
def s3_archive(tmp_path, monkeypatch):
    """Fresh tmp audit DB (sqlite) + fresh Object-Lock bucket, archiver in s3 mode."""
    client = _minio_or_skip()

    bucket = f"pm-worm-test-{uuid.uuid4().hex[:10]}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)

    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db_path)
    monkeypatch.setattr(config.settings, "AUDIT_BACKEND", "sqlite")
    monkeypatch.setattr(config.settings, "ARCHIVE_BACKEND", "s3")
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_BUCKET", bucket)
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_RETENTION_MODE", "GOVERNANCE")
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_RETENTION_DAYS", 1)

    writer = audit.AuditWriter(path=db_path)
    yield {"writer": writer, "client": client, "bucket": bucket}
    writer.close()
    _nuke_bucket(client, bucket)


def _write_rows(writer, n: int, start: int = 0) -> list[str]:
    user = User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice",
    )
    ids = []
    for i in range(start, start + n):
        ids.append(
            writer.write(
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
        )
    return ids


# ---------------------------------------------------------------------------
# 1. Seal → objects exist in the bucket WITH Object Lock retention.
# ---------------------------------------------------------------------------
def test_seal_uploads_locked_objects(s3_archive):
    _write_rows(s3_archive["writer"], 3)
    result = audit_archive.seal_next_segment(now_iso="2026-06-12T00:00:00+00:00")
    assert result["sealed"] is True
    assert result["segment_file"] == f"s3://{s3_archive['bucket']}/segment-0001.jsonl"

    head = s3_archive["client"].head_object(
        Bucket=s3_archive["bucket"], Key="segment-0001.jsonl"
    )
    assert head["ObjectLockMode"] == "GOVERNANCE"
    retain = head["ObjectLockRetainUntilDate"]
    assert retain > datetime.now(UTC)

    man_head = s3_archive["client"].head_object(
        Bucket=s3_archive["bucket"], Key="segment-0001.manifest.json"
    )
    assert man_head["ObjectLockMode"] == "GOVERNANCE"

    st = audit_archive.archive_status()
    assert st["archived_rows"] == 3
    assert st["rows_pending"] == 0
    assert st["segment_count"] == 1
    assert st["archive_dir"] == f"s3://{s3_archive['bucket']}"


# ---------------------------------------------------------------------------
# 2. verify_archive round-trips from the bucket; multi-segment chain holds.
# ---------------------------------------------------------------------------
def test_verify_ok_across_two_segments(s3_archive):
    _write_rows(s3_archive["writer"], 3)
    r1 = audit_archive.seal_next_segment()
    _write_rows(s3_archive["writer"], 2, start=50)
    r2 = audit_archive.seal_next_segment()
    assert r2["prev_root"] == r1["merkle_root"]
    assert r2["row_offset_start"] == 3

    rep = audit_archive.verify_archive()
    assert rep["ok"] is True, rep["anomalies"]
    assert rep["segments"] == 2
    assert rep["rows_archived"] == 5


# ---------------------------------------------------------------------------
# 3. Idempotency + refuse-to-overwrite guard.
# ---------------------------------------------------------------------------
def test_reseal_noop_and_existing_key_refused(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    assert audit_archive.seal_next_segment()["sealed"] is True
    second = audit_archive.seal_next_segment()
    assert second["sealed"] is False
    assert second["reason"] == "no_pending_rows"

    # Pre-create the NEXT segment key (a crashed partial seal / malicious
    # pre-creation) — seal must refuse, not overwrite.
    _write_rows(s3_archive["writer"], 2, start=100)
    s3_archive["client"].put_object(
        Bucket=s3_archive["bucket"], Key="segment-0002.jsonl", Body=b"garbage\n"
    )
    refused = audit_archive.seal_next_segment()
    assert refused["sealed"] is False
    assert refused["reason"] == "segment_already_exists"


# ---------------------------------------------------------------------------
# 4. WORM semantics — the store itself refuses deleting a sealed version.
# ---------------------------------------------------------------------------
def test_sealed_version_delete_is_refused_without_bypass(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    audit_archive.seal_next_segment()

    client, bucket = s3_archive["client"], s3_archive["bucket"]
    head = client.head_object(Bucket=bucket, Key="segment-0001.jsonl")
    version_id = head["VersionId"]

    with pytest.raises(ClientError) as exc:
        client.delete_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert exc.value.response["Error"]["Code"] in ("AccessDenied", "InvalidRequest")

    # The sealed bytes are still there.
    obj = client.get_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert b"row_hash" in obj["Body"].read()


# ---------------------------------------------------------------------------
# 5. Overwrite only ADDS a version; verify flags the tampered latest and the
#    original sealed version remains retrievable as evidence.
# ---------------------------------------------------------------------------
def test_overwrite_leaves_version_and_verify_detects(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    client, bucket = s3_archive["client"], s3_archive["bucket"]
    original = client.get_object(Bucket=bucket, Key="segment-0001.jsonl")
    original_version = original["VersionId"]
    original_body = original["Body"].read()

    # Attacker overwrites the sealed segment with forged rows.
    tampered = original_body.replace(b'"row_hash": "', b'"row_hash": "00', 1)
    client.put_object(Bucket=bucket, Key="segment-0001.jsonl", Body=tampered)

    # verify reads the latest version → Merkle root mismatch fires.
    rep = audit_archive.verify_archive()
    assert rep["ok"] is False
    types = {a["type"] for a in rep["anomalies"]}
    assert "merkle_root_mismatch" in types, rep["anomalies"]

    # ...and the SEALED version is still intact (versioning is the evidence trail).
    versions = client.list_object_versions(Bucket=bucket, Prefix="segment-0001.jsonl")
    assert len(versions.get("Versions", [])) == 2
    sealed = client.get_object(
        Bucket=bucket, Key="segment-0001.jsonl", VersionId=original_version
    )
    assert sealed["Body"].read() == original_body


# ---------------------------------------------------------------------------
# 6. Live-DB tamper after archival is still detected in s3 mode.
# ---------------------------------------------------------------------------
def test_live_tamper_detected_in_s3_mode(s3_archive):
    import sqlite3

    ids = _write_rows(s3_archive["writer"], 3)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    conn = sqlite3.connect(config.AUDIT_DB_PATH)
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute(
        "UPDATE audit SET row_hash = ? WHERE audit_id = ?",
        ("deadbeef" * 8, ids[1]),
    )
    conn.commit()
    conn.close()

    rep = audit_archive.verify_archive()
    assert rep["ok"] is False
    tampered = [a for a in rep["anomalies"] if a["type"] == "live_row_tampered"]
    assert any(a["audit_id"] == ids[1] for a in tampered)
