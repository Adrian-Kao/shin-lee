"""WORM archive hardening battery (Q13 — audit_archive.py).

``test_audit_archive.py`` covers the happy path + a couple of tamper cases.
This file is the *deep* WORM battery the Day-13G hardening track requires:

  * **Object-Lock simulation** — sealed segment + manifest files are flipped
    read-only; assert the OS actually refuses a write (the WORM property).
  * **Re-seal refusal** — if a segment file for the next index already exists
    (a partial seal that crashed, or a malicious pre-creation), ``seal_next_
    segment`` must refuse rather than overwrite (``segment_already_exists``).
  * **Segment chain across rollover** — multiple sealed segments must form a
    verifiable prev_root chain; ``verify_archive`` spans them and reports ok.
  * **Chain-break detection** — forge a manifest's prev_root / Merkle root /
    offset and assert verify_archive pinpoints ``segment_chain_break`` /
    ``merkle_root_mismatch`` / ``segment_offset_gap``.
  * **Missing-segment-file detection** — delete a sealed .jsonl and assert
    ``missing_segment_file``.

All tests redirect the live audit DB + archive dir to tmp paths via
monkeypatching ``backend.shared.config`` (mirroring conftest), with a private
AuditWriter bound to the tmp DB so the session singleton is untouched.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from backend.gateway import audit, audit_archive
from backend.shared import config
from backend.shared.models import User, UserRole


@pytest.fixture()
def tmp_archive(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    arc_dir = tmp_path / "audit_archive"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db_path)
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", arc_dir)
    writer = audit.AuditWriter(path=db_path)
    return {"db_path": db_path, "arc_dir": arc_dir, "writer": writer}


def _write_rows(writer: audit.AuditWriter, n: int, start: int = 0) -> list[str]:
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


def _rw(p: Path) -> None:
    """Re-grant write so the test can mutate a sealed file (simulating an
    attacker who cleared the read-only attribute)."""
    os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)


# ===========================================================================
# 1. Object Lock simulation — sealed files are read-only.
# ===========================================================================
def test_sealed_segment_files_are_read_only(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()

    seg = tmp_archive["arc_dir"] / "segment-0001.jsonl"
    man = tmp_archive["arc_dir"] / "segment-0001.manifest.json"
    assert seg.exists() and man.exists()

    # The write bit must be cleared on both (Object Lock sim). On Windows
    # chmod sets FILE_ATTRIBUTE_READONLY; stat.S_IWRITE is honoured.
    seg_mode = stat.S_IMODE(os.stat(seg).st_mode)
    man_mode = stat.S_IMODE(os.stat(man).st_mode)
    assert not (seg_mode & stat.S_IWUSR), f"segment writable: {oct(seg_mode)}"
    assert not (man_mode & stat.S_IWUSR), f"manifest writable: {oct(man_mode)}"

    # And the OS actually refuses an append while read-only.
    with pytest.raises((PermissionError, OSError)):
        with open(seg, "a", encoding="utf-8") as fh:
            fh.write("tamper\n")


# ===========================================================================
# 2. Re-seal refusal — pre-existing next-index segment is not overwritten.
# ===========================================================================
def test_seal_refuses_when_next_segment_already_exists(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()  # segment-0001 sealed

    # Write more rows so there ARE pending rows (else it'd no-op for a
    # different reason). The next seal would be segment-0002.
    _write_rows(tmp_archive["writer"], 2, start=100)

    # Pre-create the segment-0002 file as if a partial seal crashed.
    arc = tmp_archive["arc_dir"]
    (arc / "segment-0002.jsonl").write_text("garbage\n", encoding="utf-8")

    result = audit_archive.seal_next_segment()
    assert result["sealed"] is False
    assert result["reason"] == "segment_already_exists", result
    # The pending rows are still pending (nothing was archived into 0002).
    assert audit_archive.archive_status()["rows_pending"] == 2


# ===========================================================================
# 3. Continuity across rollover — many segments verify as one chain.
# ===========================================================================
def test_archive_continuity_across_three_rollovers(tmp_archive):
    roots = []
    for batch in range(3):
        _write_rows(tmp_archive["writer"], 2, start=batch * 10)
        r = audit_archive.seal_next_segment()
        assert r["sealed"] is True
        assert r["segment_index"] == batch + 1
        roots.append(r["merkle_root"])

    # Each segment's manifest prev_root chains to the previous root.
    arc = tmp_archive["arc_dir"]
    man2 = json.loads((arc / "segment-0002.manifest.json").read_text("utf-8"))
    man3 = json.loads((arc / "segment-0003.manifest.json").read_text("utf-8"))
    assert man2["prev_root"] == roots[0]
    assert man3["prev_root"] == roots[1]
    # Offsets are contiguous: 0,2,4.
    assert man2["row_offset_start"] == 2
    assert man3["row_offset_start"] == 4

    result = audit_archive.verify_archive()
    assert result["ok"] is True, result["anomalies"]
    assert result["segments"] == 3
    assert result["rows_archived"] == 6


# ===========================================================================
# 4. Chain-break detection — forge a prev_root in a middle manifest.
# ===========================================================================
def test_verify_detects_segment_chain_break(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()
    _write_rows(tmp_archive["writer"], 2, start=10)
    audit_archive.seal_next_segment()

    man2_path = tmp_archive["arc_dir"] / "segment-0002.manifest.json"
    _rw(man2_path)
    man2 = json.loads(man2_path.read_text("utf-8"))
    man2["prev_root"] = "forged_prev_root"
    man2_path.write_text(json.dumps(man2, sort_keys=True), encoding="utf-8")

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    types = {a["type"] for a in result["anomalies"]}
    # Changing prev_root breaks the chain link AND the recomputed Merkle root
    # (prev_root is folded into the root), so both fire.
    assert "segment_chain_break" in types, result["anomalies"]
    assert "merkle_root_mismatch" in types, result["anomalies"]


# ===========================================================================
# 5. Offset-gap detection — forge a manifest's row_offset_start.
# ===========================================================================
def test_verify_detects_offset_gap(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()
    _write_rows(tmp_archive["writer"], 2, start=10)
    audit_archive.seal_next_segment()

    man2_path = tmp_archive["arc_dir"] / "segment-0002.manifest.json"
    _rw(man2_path)
    man2 = json.loads(man2_path.read_text("utf-8"))
    man2["row_offset_start"] = 99  # should be 2
    man2_path.write_text(json.dumps(man2, sort_keys=True), encoding="utf-8")

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    gaps = [a for a in result["anomalies"] if a["type"] == "segment_offset_gap"]
    assert gaps, result["anomalies"]
    assert gaps[0]["expected_offset"] == 2
    assert gaps[0]["recorded_offset"] == 99


# ===========================================================================
# 6. Forged Merkle root in manifest is detected.
# ===========================================================================
def test_verify_detects_forged_merkle_root(tmp_archive):
    _write_rows(tmp_archive["writer"], 3)
    audit_archive.seal_next_segment()

    man_path = tmp_archive["arc_dir"] / "segment-0001.manifest.json"
    _rw(man_path)
    man = json.loads(man_path.read_text("utf-8"))
    man["merkle_root"] = "deadbeef" * 8
    man_path.write_text(json.dumps(man, sort_keys=True), encoding="utf-8")

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    types = {a["type"] for a in result["anomalies"]}
    assert "merkle_root_mismatch" in types, result["anomalies"]


# ===========================================================================
# 7. Missing-segment-file detection — delete a sealed .jsonl.
# ===========================================================================
def test_verify_detects_missing_segment_file(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()
    _write_rows(tmp_archive["writer"], 2, start=10)
    audit_archive.seal_next_segment()

    seg1 = tmp_archive["arc_dir"] / "segment-0001.jsonl"
    _rw(seg1)
    seg1.unlink()

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    missing = [a for a in result["anomalies"] if a["type"] == "missing_segment_file"]
    assert missing, result["anomalies"]
    assert missing[0]["segment_index"] == 1


# ===========================================================================
# 8. row_count mismatch — append a row to a sealed segment after clearing RO.
# ===========================================================================
def test_verify_detects_row_count_mismatch(tmp_archive):
    _write_rows(tmp_archive["writer"], 2)
    audit_archive.seal_next_segment()

    seg = tmp_archive["arc_dir"] / "segment-0001.jsonl"
    _rw(seg)
    rows = audit_archive._read_segment_rows(seg)
    # Duplicate the last row → manifest.row_count (2) != actual (3).
    rows.append(dict(rows[-1]))
    seg.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
        encoding="utf-8",
    )

    result = audit_archive.verify_archive()
    assert result["ok"] is False
    types = {a["type"] for a in result["anomalies"]}
    assert "row_count_mismatch" in types, result["anomalies"]


# ===========================================================================
# 9. Empty live DB — seal is a no-op, verify is trivially ok.
# ===========================================================================
def test_seal_noop_on_empty_db_and_verify_ok(tmp_archive):
    r = audit_archive.seal_next_segment()
    assert r["sealed"] is False
    assert r["reason"] == "no_pending_rows"
    result = audit_archive.verify_archive()
    assert result["ok"] is True
    assert result["segments"] == 0
    assert result["rows_archived"] == 0
