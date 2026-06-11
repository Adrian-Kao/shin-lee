"""Unit tests for Q20 backup retention pruning (backend/gateway/backup.py).

Mirrors test_backup.py's fixture: every stateful store + the backup dir is
redirected onto fresh tmp paths so pruning operates on an isolated tree. Backup
ids are injected via ``now_iso`` so ordering is deterministic (no Date.now
nondeterminism).
"""

from __future__ import annotations

import pytest

from backend.gateway import audit, backup, masking
from backend.shared import config
from backend.shared.models import User, UserRole


@pytest.fixture()
def tmp_stores(tmp_path, monkeypatch):
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
    masking.MaskingStore(path=mapping_db)  # materialise the mapping db
    return {"writer": writer, "backup_dir": backup_dir}


def _seed(writer: audit.AuditWriter, n: int = 2) -> None:
    user = User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="alice",
    )
    for i in range(n):
        writer.write(
            user=user,
            case_id=f"case-{i}",
            endpoint="/v1/analyze",
            request_payload={"q": i},
            response_payload={"a": i},
            masked_rules=[],
            model_used="mock",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
            policy_decisions={"ok": True},
        )


# Six deterministic, chronologically-ordered snapshot timestamps.
_TS = [
    "2026-06-08T01:00:00+00:00",
    "2026-06-08T02:00:00+00:00",
    "2026-06-08T03:00:00+00:00",
    "2026-06-08T04:00:00+00:00",
    "2026-06-08T05:00:00+00:00",
    "2026-06-08T06:00:00+00:00",
]
_IDS = [
    "20260608T010000",
    "20260608T020000",
    "20260608T030000",
    "20260608T040000",
    "20260608T050000",
    "20260608T060000",
]


def _make_n_backups(tmp_stores, n: int) -> list[str]:
    _seed(tmp_stores["writer"])
    ids = []
    for i in range(n):
        snap = backup.snapshot(now_iso=_TS[i])
        ids.append(snap["backup_id"])
    return ids


# ---------------------------------------------------------------------------
# list_backups.
# ---------------------------------------------------------------------------
def test_list_backups_chronological(tmp_stores):
    _make_n_backups(tmp_stores, 3)
    assert backup.list_backups() == _IDS[:3]


def test_list_backups_empty_when_no_dir(tmp_stores):
    # No snapshot taken yet → empty list, no crash.
    assert backup.list_backups() == []


def test_list_backups_ignores_non_backup_dirs(tmp_stores):
    _make_n_backups(tmp_stores, 1)
    # A stray dir with no manifest must not be counted as a backup set.
    (tmp_stores["backup_dir"] / "garbage").mkdir()
    assert backup.list_backups() == [_IDS[0]]


# ---------------------------------------------------------------------------
# prune.
# ---------------------------------------------------------------------------
def test_prune_keeps_n_most_recent(tmp_stores):
    _make_n_backups(tmp_stores, 5)
    result = backup.prune(keep=2)
    assert result["kept"] == 2
    assert result["pruned"] == 3
    # The two newest survive.
    assert result["remaining_ids"] == _IDS[3:5]
    assert sorted(result["pruned_ids"]) == sorted(_IDS[0:3])
    # Physically gone.
    for bid in _IDS[0:3]:
        assert not (tmp_stores["backup_dir"] / bid).exists()
    for bid in _IDS[3:5]:
        assert (tmp_stores["backup_dir"] / bid).exists()


def test_prune_noop_when_fewer_than_keep(tmp_stores):
    _make_n_backups(tmp_stores, 2)
    result = backup.prune(keep=5)
    assert result["pruned"] == 0
    assert result["kept"] == 2
    assert backup.list_backups() == _IDS[:2]


def test_prune_keep_zero_deletes_all(tmp_stores):
    _make_n_backups(tmp_stores, 3)
    result = backup.prune(keep=0)
    assert result["pruned"] == 3
    assert result["kept"] == 0
    assert backup.list_backups() == []


def test_prune_rejects_negative(tmp_stores):
    with pytest.raises(ValueError):
        backup.prune(keep=-1)


def test_prune_keep_one(tmp_stores):
    _make_n_backups(tmp_stores, 4)
    result = backup.prune(keep=1)
    assert result["remaining_ids"] == [_IDS[3]]


# ---------------------------------------------------------------------------
# snapshot(prune_keep=...) — snapshot-then-sweep, the fresh set always survives.
# ---------------------------------------------------------------------------
def test_snapshot_with_prune_keep_sweeps_old_keeps_new(tmp_stores):
    _seed(tmp_stores["writer"])
    # Three older snapshots, no auto-prune.
    for ts in _TS[:3]:
        backup.snapshot(now_iso=ts)
    assert len(backup.list_backups()) == 3

    # 4th snapshot with prune_keep=2 → keep the 2 newest (incl. this one).
    snap = backup.snapshot(now_iso=_TS[3], prune_keep=2)
    assert "prune" in snap
    assert snap["prune"]["kept"] == 2
    remaining = backup.list_backups()
    assert remaining == _IDS[2:4]  # the 3rd + the just-written 4th
    # The just-written snapshot is among the survivors (didn't self-delete).
    assert snap["backup_id"] in remaining


def test_snapshot_without_prune_keep_does_not_prune(tmp_stores):
    _seed(tmp_stores["writer"])
    for ts in _TS[:3]:
        snap = backup.snapshot(now_iso=ts)
        assert "prune" not in snap  # opt-in only
    assert len(backup.list_backups()) == 3


def test_snapshot_prune_keep_round_trips_restore(tmp_stores, tmp_path):
    """After a snapshot-then-sweep, the surviving newest set still restores +
    verifies — pruning never corrupts the kept sets."""
    _seed(tmp_stores["writer"], n=3)
    for ts in _TS[:2]:
        backup.snapshot(now_iso=ts)
    snap = backup.snapshot(now_iso=_TS[2], prune_keep=1)
    assert backup.list_backups() == [snap["backup_id"]]

    result = backup.restore(snap["backup_id"], tmp_path / "restored")
    assert result["ok"] is True
    assert (tmp_path / "restored" / "audit.db").exists()
