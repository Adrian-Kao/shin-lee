# Disaster Recovery Runbook (Q20) — backup, restore, drill, retention

> Decision (docs/DECISIONS.md Q20): **每日備份** for the POC; "正式上線前 Q20
> 必須升到 B" — production **must** upgrade to streaming replication before
> go-live. This runbook is the operational half of `backend/gateway/backup.py`.

**Objectives**

| Objective | Target |
|---|---|
| RPO (recovery point) | **< 5 min** (production: hourly logical backup + streamed WAL) |
| RTO (recovery time)  | **< 1 hr** |
| Retention            | **7 years** offsite (POC: keep-N local pruning) |

---

## 0. What is backed up

`backend/gateway/backup.py` snapshots every **stateful** store into a
timestamped backup set under `BACKUP_DIR`:

| Store | Path (config) | Method |
|---|---|---|
| Audit log | `AUDIT_DB_PATH` | SQLite **online backup API** (tear-free, consistent) |
| Redaction mapping (reversible PII) | `MAPPING_DB_PATH` | SQLite online backup |
| Patent index (if materialised) | `PATENT_DB_PATH` | SQLite online backup (skipped if absent) |
| WORM audit archive | `AUDIT_ARCHIVE_DIR` | file-by-file copy of sealed segments |

Each set writes a `manifest.json` recording per-file `path` / `size` / `sha256`
plus `backup_id`, `created_at`, `schema_version`. The sha256 is the integrity
anchor: restore re-hashes every file and refuses a corrupted/tampered set.

> The AI Engine holds **no business state** (invariant #2) — only RAG vectors,
> which in the POC are in-memory and re-seeded on boot. Nothing on the AI Engine
> needs backing up.

---

## 1. Take a backup

```bash
# Single snapshot (no pruning).
python -m backend.gateway.backup snapshot

# Snapshot then sweep — keep only the N most-recent sets (retention).
python -m backend.gateway.backup snapshot --keep 168    # ~1 week of hourly

# List existing backup sets (oldest → newest).
python -m backend.gateway.backup list
```

Production cron (POC stand-in for streaming replication):

```cron
# Hourly logical backup + retention sweep. Production additionally ships
# BACKUP_DIR offsite (aws s3 cp / rsync to a separate failure domain) and
# streams the Postgres WAL for sub-5-min RPO.
0 * * * *  cd /opt/patentmind && python -m backend.gateway.backup snapshot --keep 168 && aws s3 sync data/backups s3://patentmind-dr/backups/
```

`BACKUP_RETENTION_KEEP` (config / env, default 168) is the default keep count.

---

## 2. Retention pruning

```bash
python -m backend.gateway.backup prune 168   # keep 168 newest, delete the rest
```

* Keeps the `N` lexically-newest sets (backup_id is a sortable timestamp).
* `prune 0` deletes **all** sets (explicit operator action only — a bare
  `snapshot` never prunes, and `snapshot --keep 0` is a deliberate no-op so a
  snapshot can never self-delete).
* A delete failure on one set (e.g. a Windows file lock) is recorded under
  `errors[]` and does **not** abort the others — pruning is best-effort sweeping.

---

## 3. Restore (integrity-verified)

```bash
python -m backend.gateway.backup restore <backup_id> /path/to/restore_target
```

Every file is copied into the target, **re-hashed**, and compared to the
manifest. The result reports `ok` (True only when every file present + hash
matched) and any `anomalies` (`sha256_mismatch` = bit-rot/tamper,
`missing_backup_file`). **Never** promote a restore with `ok=false` to primary.

Cut-over (POC: stop service, swap files, restart):

```bash
systemctl stop patentmind-gateway
python -m backend.gateway.backup restore 20260610T090000 /opt/patentmind/data
systemctl start patentmind-gateway
# Verify the restored audit chain is intact (see §4) before accepting traffic.
```

---

## 4. DR drill (quarterly — DO THIS)

```bash
python -m backend.gateway.backup drill
```

The drill is the headline feature: **snapshot → restore into a throwaway dir →
verify**. It proves two independent things:

1. **Byte integrity** — every restored file's sha256 matches the manifest.
2. **Audit-chain integrity after restore** — the restored `audit.db` is walked
   with `verify_global_chain`; `chain_intact` is True only when **zero** rows
   are broken. This turns "we have backups" into "we PROVED we can restore a
   *valid*, tamper-evident audit log."

Report fields: `ok` (bytes verified AND chain intact), `chain_intact`, `rows`,
`files_verified` / `files_total`, `rpo_estimate_seconds` (age of the snapshot =
realised recovery point; target < 300s).

**A green drill is the quarterly compliance evidence.** Archive the JSON output
with the date. A red drill (`ok=false`) is a P1 — investigate the `chain` /
`anomalies` block immediately.

---

## 5. GDPR / 個資法 right-to-erasure

```bash
python -m backend.gateway.backup erase <tenant_id> --dry-run   # preview
python -m backend.gateway.backup erase <tenant_id>             # commit
```

* **Erased:** the subject's reversible PII in the masking mapping table
  (`MAPPING_DB_PATH`). Deleting those rows makes the placeholders permanently
  un-reversible — the PII is gone.
* **Retained:** audit rows are **not** deleted (GDPR Art. 17(3) legal-hold /
  legal-claim exception). They store only hashes + a `user_id` label — no raw
  PII — so retention is compliant. (The audit table is also append-only at the
  DB level: erasure *must* live in the mutable mapping store by design.)
* Always `--dry-run` first; the receipt reports `would_erase_mapping_entries`
  and `audit_rows_retained`.

---

## 6. ⚠ Production hardening — MUST do before go-live

This module captures the **semantics** of DR so production can swap the storage
target without changing the verify/restore/drill logic. Before prod:

1. **Upgrade to streaming replication** (Postgres physical/logical replication
   or WAL streaming) — the hourly logical backup alone cannot hit RPO < 5 min.
   This is the explicit Q20 "升到 B" requirement and the CLAUDE.md §3 caveat.
2. **Offsite, separate failure domain** — ship `BACKUP_DIR` to S3 (with Object
   Lock for the WORM audit archive) or an equivalent in a different region.
3. **Restore drill in the prod-like environment**, not just unit tests — prove
   RTO < 1 hr against real data volumes, and rehearse the cut-over.
4. **Encrypt backups at rest** — the mapping DB carries reversible PII; the
   master key (`MAPPING_ENCRYPTION_KEY`) must live in a secret manager, never in
   `BACKUP_DIR`.
5. **Alert on drill failure + backup age** — wire `drill` into the cron and
   page on `ok=false` or a snapshot older than the RPO target.
