#!/usr/bin/env python3
"""Q20 — scheduled-backup CLI: snapshot every stateful store + retention sweep.

This is the executable a scheduler invokes; ``backend/gateway/backup.py`` is
the body (snapshot / prune / DR drill). Wire-ups:

  Linux cron        — see ``scripts/backup_cron.sh`` (hourly, RPO < 5 min needs
                      streaming replication; this gives RPO = the cron period).
  Windows Task Scheduler —
      schtasks /Create /TN PatentMindBackup /SC HOURLY ^
        /TR "py -3 D:\\patentmind-poc\\scripts\\run_backup.py" /F

Usage:
    python scripts/run_backup.py                 # snapshot + keep BACKUP_RETENTION_KEEP newest
    python scripts/run_backup.py --keep 24       # override retention for this run
    python scripts/run_backup.py --no-prune      # snapshot only, never delete old sets
    python scripts/run_backup.py --drill         # quarterly DR drill instead of a snapshot
    python scripts/run_backup.py --quiet         # one summary line instead of full JSON

Exit codes (cron/Task-Scheduler friendly):
    0  snapshot written (and, with --drill, the drill verified ok)
    1  snapshot/drill FAILED — page the operator; the recovery point did not advance

⚠ PRODUCTION WARNING (CLAUDE.md §3b / docs/OPERATIONS_AND_ONBOARDING.md §11):
this logical-snapshot cron meets the POC bar only. **Before production you MUST
upgrade to streaming replication** (Postgres WAL shipping / litestream for the
SQLite era) — a periodic snapshot can never meet the Q20 RPO < 5 min target,
it only bounds data loss to the cron interval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/run_backup.py` from any CWD: put the repo root (this
# file's parent's parent) on sys.path before importing backend modules.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    # Windows consoles are often cp950/cp1252; force utf-8 so JSON with 中文
    # notes prints cleanly (mirrors backup.py's own CLI).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="run_backup.py",
        description="Snapshot all stateful stores and apply the retention policy (Q20).",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        metavar="N",
        help="retention: keep the N newest backup sets after a successful "
        "snapshot (default: BACKUP_RETENTION_KEEP from config, currently the "
        "hourly-for-a-week 168).",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="snapshot only; skip the retention sweep entirely.",
    )
    parser.add_argument(
        "--drill",
        action="store_true",
        help="run the DR drill (snapshot → restore → verify bytes + audit "
        "chain) instead of a plain snapshot. Exit 1 unless the drill is ok.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print a one-line summary instead of the full JSON report.",
    )
    args = parser.parse_args(argv)

    from backend.gateway import backup
    from backend.shared.config import settings

    try:
        if args.drill:
            report = backup.drill()
            ok = bool(report.get("ok"))
        else:
            keep = None if args.no_prune else (args.keep or settings.BACKUP_RETENTION_KEEP)
            report = backup.snapshot(prune_keep=keep)
            # A snapshot that captured zero files means no store was found at
            # the configured paths — almost certainly a misconfigured cron
            # (wrong CWD / env). Fail loudly rather than report success.
            ok = report.get("file_count", 0) > 0
            if not ok:
                report["error"] = (
                    "snapshot captured 0 files — no stateful store found at the "
                    "configured AUDIT_DB_PATH / MAPPING_DB_PATH / AUDIT_ARCHIVE_DIR. "
                    "Check the service has run at least once and the cron's env/CWD."
                )
    except Exception as exc:  # noqa: BLE001 — cron must get exit 1, not a traceback-only crash
        print(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    if args.quiet:
        if args.drill:
            print(
                f"drill backup_id={report.get('backup_id')} ok={ok} "
                f"chain_intact={report.get('chain_intact')} "
                f"files={report.get('files_verified')}/{report.get('files_total')}"
            )
        else:
            prune = report.get("prune") or {}
            print(
                f"snapshot backup_id={report.get('backup_id')} ok={ok} "
                f"files={report.get('file_count')} "
                f"pruned={prune.get('pruned', 0)} kept={prune.get('kept', '-')}"
            )
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
