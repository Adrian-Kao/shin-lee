#!/usr/bin/env bash
# Q20 — cron wrapper for scripts/run_backup.py (Linux/macOS deployments).
#
# Install (as the service user):
#   crontab -e
# and add ONE of:
#
#   # hourly logical snapshot, keep the newest 168 sets (one week of hourlies)
#   0 * * * *  /usr/bin/env bash /opt/patentmind/scripts/backup_cron.sh >> /var/log/patentmind-backup.log 2>&1
#
#   # quarterly DR drill (1st day of Jan/Apr/Jul/Oct, 03:15) — proves the
#   # backup actually restores AND the restored audit hash-chain verifies
#   15 3 1 1,4,7,10 *  /usr/bin/env bash /opt/patentmind/scripts/backup_cron.sh --drill >> /var/log/patentmind-backup.log 2>&1
#
# Windows equivalent (Task Scheduler, run once from an elevated prompt):
#   schtasks /Create /TN PatentMindBackup /SC HOURLY ^
#     /TR "py -3 D:\patentmind-poc\scripts\run_backup.py --quiet" /F
#
# Exit code passes through from run_backup.py: 0 = recovery point advanced,
# 1 = FAILED — alert on it (cron MAILTO, or healthchecks.io-style ping).
#
# ⚠ PRODUCTION WARNING: a periodic snapshot bounds data loss to the cron
# interval — it can NOT meet the Q20 RPO < 5 min target. Before production,
# upgrade to streaming replication (Postgres WAL shipping / litestream while
# the stores are still SQLite). This cron is the POC/pilot stopgap.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# Load the service .env if present (BACKUP_DIR, BACKUP_RETENTION_KEEP, paths).
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN=python

exec "$PYTHON_BIN" "$SCRIPT_DIR/run_backup.py" --quiet "$@"
