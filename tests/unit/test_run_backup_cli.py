"""Q20 P1 — scheduled-backup CLI wrapper (scripts/run_backup.py).

Exercises the wrapper in-process (import + main(argv)) against tmp-redirected
stores, mirroring test_backup_retention.py's fixture. The contract under test
is the CRON contract: exit code 0 only when the recovery point advanced, 1 on
any failure, retention applied after the snapshot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from backend.gateway import audit, masking
from backend.shared import config
from backend.shared.models import User, UserRole

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_backup.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_backup_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def tmp_stores(tmp_path, monkeypatch):
    audit_db = tmp_path / "audit.db"
    mapping_db = tmp_path / "mapping.db"
    backup_dir = tmp_path / "backups"

    monkeypatch.setattr(config, "AUDIT_DB_PATH", audit_db)
    monkeypatch.setattr(config, "MAPPING_DB_PATH", mapping_db)
    monkeypatch.setattr(config, "PATENT_DB_PATH", tmp_path / "patent.db")
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", tmp_path / "audit_archive")
    monkeypatch.setattr(config, "BACKUP_DIR", backup_dir)

    writer = audit.AuditWriter(path=audit_db)
    masking.MaskingStore(path=mapping_db)
    user = User(user_id="alice", tenant_id="tenant_a", role=UserRole.ATTORNEY, display_name="alice")
    writer.write(
        user=user,
        case_id="case-0",
        endpoint="/v1/analyze",
        request_payload={"q": 1},
        response_payload={"a": 1},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
        policy_decisions={"ok": True},
    )
    return {"backup_dir": backup_dir}


def test_snapshot_success_exit_zero_and_json_report(tmp_stores, capsys):
    cli = _load_cli()
    rc = cli.main([])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["file_count"] >= 1
    assert (tmp_stores["backup_dir"] / report["backup_id"] / "manifest.json").exists()


def test_keep_applies_retention_after_snapshot(tmp_stores):
    from backend.gateway import backup

    cli = _load_cli()
    # Pre-seed three older snapshots with deterministic ids.
    for ts in ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"):
        backup.snapshot(now_iso=ts)
    rc = cli.main(["--keep", "2", "--quiet"])
    assert rc == 0
    remaining = backup.list_backups()
    assert len(remaining) == 2  # newest two survive; the fresh one is among them


def test_no_prune_keeps_everything(tmp_stores):
    from backend.gateway import backup

    cli = _load_cli()
    backup.snapshot(now_iso="2026-01-01T00:00:00+00:00")
    rc = cli.main(["--no-prune", "--quiet"])
    assert rc == 0
    assert len(backup.list_backups()) == 2


def test_empty_stores_exit_one(tmp_path, monkeypatch, capsys):
    # No store materialised anywhere → 0 files captured → cron must see exit 1.
    monkeypatch.setattr(config, "AUDIT_DB_PATH", tmp_path / "missing-audit.db")
    monkeypatch.setattr(config, "MAPPING_DB_PATH", tmp_path / "missing-mapping.db")
    monkeypatch.setattr(config, "PATENT_DB_PATH", tmp_path / "missing-patent.db")
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", tmp_path / "missing-archive")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")

    cli = _load_cli()
    rc = cli.main([])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert "0 files" in report["error"]


def test_exception_path_exit_one(tmp_stores, monkeypatch, capsys):
    from backend.gateway import backup

    def _boom(**_kw):
        raise RuntimeError("disk on fire")

    cli = _load_cli()
    monkeypatch.setattr(backup, "snapshot", _boom)
    rc = cli.main([])
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["ok"] is False and "disk on fire" in err["error"]


def test_drill_success_exit_zero(tmp_stores, capsys):
    cli = _load_cli()
    rc = cli.main(["--drill"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["chain_intact"] is True


def test_quiet_prints_one_line(tmp_stores, capsys):
    cli = _load_cli()
    rc = cli.main(["--quiet"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "\n" not in out
    assert out.startswith("snapshot backup_id=")


def test_cli_runs_as_subprocess(tmp_stores):
    """The cron path: the script must be invocable as a child process with
    UTF-8 output regardless of the parent console codepage (cp950)."""
    import subprocess

    env = dict(**__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    # Point the subprocess at the SAME tmp stores via env? Config reads env at
    # import for paths only partially — so just smoke the --help path, which
    # must not import-crash or hit any store.
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "snapshot" in proc.stdout.lower()
