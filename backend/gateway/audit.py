"""Audit log (Q13).

POC implements append-only locally; the trigger blocks UPDATE / DELETE so
the DBA can't tamper inadvertently.  Production must additionally:
    - Write to S3 Object Lock / Azure Immutable Blob hourly.
    - Sign each row chain with HMAC of previous row hash (tamper evidence).
    - Replicate to a 2nd tenant for compliance independence.

Every gateway-handled request produces exactly one audit row.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.shared.config import AUDIT_DB_PATH
from backend.shared.models import User


_DDL = """
CREATE TABLE IF NOT EXISTS audit (
    audit_id           TEXT PRIMARY KEY,
    timestamp_utc      TEXT NOT NULL,
    timestamp_local    TEXT NOT NULL,
    user_id            TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    case_id            TEXT,
    endpoint           TEXT NOT NULL,
    request_hash       TEXT NOT NULL,
    response_hash      TEXT,
    masked_field_rules TEXT NOT NULL,
    model_used         TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    latency_ms         INTEGER,
    policy_decisions   TEXT NOT NULL,
    prev_row_hash      TEXT,
    row_hash           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit(case_id, timestamp_utc DESC);

-- Hard block on tampering.  Trigger errors out.
CREATE TRIGGER IF NOT EXISTS audit_no_update
    BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit table is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
    BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit table is append-only'); END;
"""


class AuditWriter:
    def __init__(self, path: Path = AUDIT_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()

    @staticmethod
    def _hash_payload(obj: Any) -> str:
        if obj is None:
            return ""
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(s.encode()).hexdigest()

    def _last_row_hash(self) -> Optional[str]:
        cur = self._conn.execute("SELECT row_hash FROM audit ORDER BY rowid DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None

    def write(
        self,
        *,
        user: User,
        case_id: Optional[str],
        endpoint: str,
        request_payload: Any,
        response_payload: Any,
        masked_rules: list[str],
        model_used: Optional[str],
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        latency_ms: int,
        policy_decisions: dict[str, bool],
    ) -> str:
        now_utc = datetime.now(timezone.utc)
        # POC: local timezone shown as UTC+8 for Taiwan demo
        local_offset_hours = 8
        now_local = now_utc.astimezone(tz=None).isoformat()

        audit_id = str(uuid.uuid4())
        request_hash = self._hash_payload(request_payload)
        response_hash = self._hash_payload(response_payload)
        prev_hash = self._last_row_hash() or ""

        # Tamper-evident chain: hash includes prev_row_hash
        row_payload = {
            "audit_id": audit_id,
            "ts": now_utc.isoformat(),
            "user": user.user_id,
            "tenant": user.tenant_id,
            "case": case_id,
            "endpoint": endpoint,
            "req": request_hash,
            "resp": response_hash,
            "prev": prev_hash,
        }
        row_hash = self._hash_payload(row_payload)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit (
                    audit_id, timestamp_utc, timestamp_local, user_id, tenant_id, case_id,
                    endpoint, request_hash, response_hash, masked_field_rules,
                    model_used, prompt_tokens, completion_tokens, latency_ms,
                    policy_decisions, prev_row_hash, row_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    now_utc.isoformat(),
                    now_local,
                    user.user_id,
                    user.tenant_id,
                    case_id,
                    endpoint,
                    request_hash,
                    response_hash,
                    json.dumps(masked_rules),
                    model_used,
                    prompt_tokens,
                    completion_tokens,
                    latency_ms,
                    json.dumps(policy_decisions),
                    prev_hash,
                    row_hash,
                ),
            )
            self._conn.commit()
        return audit_id

    def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
        cur = self._conn.execute(
            """
            SELECT audit_id, timestamp_utc, user_id, case_id, endpoint,
                   model_used, prompt_tokens, completion_tokens, latency_ms,
                   masked_field_rules, policy_decisions
            FROM audit
            WHERE tenant_id = ?
            ORDER BY rowid DESC LIMIT ?
            """,
            (tenant_id, limit),
        )
        cols = [c[0] for c in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["masked_field_rules"] = json.loads(d["masked_field_rules"])
            d["policy_decisions"] = json.loads(d["policy_decisions"])
            rows.append(d)
        return rows

    def verify_chain(self, tenant_id: str) -> dict:
        """Walk the chain, recompute hashes, report any tamper detected.

        For production: run nightly + alert on mismatch.
        """
        cur = self._conn.execute(
            """
            SELECT audit_id, timestamp_utc, user_id, tenant_id, case_id,
                   endpoint, request_hash, response_hash, prev_row_hash, row_hash
            FROM audit
            WHERE tenant_id = ?
            ORDER BY rowid ASC
            """,
            (tenant_id,),
        )
        ok = 0
        broken: list[str] = []
        prev = ""
        for row in cur.fetchall():
            (audit_id, ts, uid, tid, cid, ep, rqh, rph, recorded_prev, recorded_row) = row
            if recorded_prev != prev:
                broken.append(audit_id)
            payload = {
                "audit_id": audit_id, "ts": ts, "user": uid, "tenant": tid,
                "case": cid, "endpoint": ep, "req": rqh, "resp": rph, "prev": recorded_prev,
            }
            recomputed = self._hash_payload(payload)
            if recomputed != recorded_row:
                broken.append(audit_id)
            else:
                ok += 1
            prev = recorded_row
        return {"verified": ok, "broken": broken, "tenant": tenant_id}

    def verify_global_chain(self) -> dict:
        """Walk every audit row in global rowid order + run cross-cutting
        checks no per-tenant walk can perform (H-4 fix — CLAUDE.md §7
        pitfall #4).

        Important wrinkle the per-tenant ``verify_chain`` does NOT handle:
        the hash chain is GLOBAL (the writer's ``_last_row_hash`` lookup
        is not tenant-scoped), so ``prev_row_hash`` on a tenant_b row may
        legitimately point to a tenant_a row_hash. Walking only
        ``WHERE tenant_id = 'tenant_b'`` and expecting tenant_b's first
        row to have ``prev=''`` is therefore wrong in the multi-tenant
        case — it flags an intact chain as broken. Global verify walks
        every row in rowid order so the chain is reconstructed faithfully.

        This verifier surfaces THREE classes of anomaly:

        1. **Hash chain integrity (global)** — every row's
           ``row_hash`` is recomputed from its payload + recorded
           ``prev_row_hash``; mismatch flags the row as broken. Adjacent
           rows must form a chain (each row's ``prev_row_hash`` == the
           previous row's ``row_hash``).

        2. **Tenant whitelist** — any row whose ``tenant_id`` is NOT in
           ``settings.DEMO_TENANTS`` is flagged as ``unknown_tenant``.
           Catches typos (``tenat_a``), probes (``tenant_zzz``), and any
           future ghost tenant smuggled in by a compromised DBA.

        3. **prev_row_hash referential integrity** — every non-empty
           ``prev_row_hash`` must reference a ``row_hash`` that exists
           somewhere in the table. Dangling prev = row was tampered with
           after insert OR written by a process bypassing AuditWriter.

        Returns:

            {
              "verified": int,                          # rows that passed
              "broken": list[tuple[tenant_id, audit_id]],
              "by_tenant": {
                  tenant_id: {
                      "verified": int,
                      "broken": list[audit_id],         # audit_ids only,
                                                        # for backward-compat
                                                        # shape with existing
                                                        # per-tenant verify
                      "tenant": tenant_id,
                      "unknown_tenant": bool,           # only when true
                  },
                  ...
              }
            }
        """
        # Load every row in rowid (insertion) order so we reconstruct the
        # GLOBAL chain rather than a per-tenant view. We also need the full
        # set of row_hashes to validate prev_row_hash references in pass
        # two; the same fetchall serves both.
        cur = self._conn.execute(
            "SELECT audit_id, timestamp_utc, user_id, tenant_id, case_id, "
            "       endpoint, request_hash, response_hash, prev_row_hash, row_hash "
            "FROM audit "
            "ORDER BY rowid ASC"
        )
        all_rows = cur.fetchall()
        all_row_hashes: set[str] = {r[9] for r in all_rows}

        # Cross-import settings here (not at module top) so a test that
        # monkeypatches DEMO_TENANTS via settings sees the override.
        from backend.shared.config import settings as _settings
        known_tenants: set[str] = set(_settings.DEMO_TENANTS.keys())

        by_tenant: dict[str, dict] = {}
        broken: list[tuple[str, str]] = []
        verified_total = 0

        # Pass 1 — walk the global chain, recompute hashes, partition
        # per-tenant. ``prev`` tracks the expected prev_row_hash for the
        # NEXT row (starts empty for the first global row).
        prev = ""
        for row in all_rows:
            (audit_id, ts, uid, tid, cid, ep, rqh, rph, recorded_prev, recorded_row) = row
            per = by_tenant.setdefault(
                tid, {"verified": 0, "broken": [], "tenant": tid}
            )

            row_broken = False
            if recorded_prev != prev:
                row_broken = True
            payload = {
                "audit_id": audit_id, "ts": ts, "user": uid, "tenant": tid,
                "case": cid, "endpoint": ep, "req": rqh, "resp": rph,
                "prev": recorded_prev,
            }
            if self._hash_payload(payload) != recorded_row:
                row_broken = True

            if row_broken:
                per["broken"].append(audit_id)
                broken.append((tid, audit_id))
            else:
                per["verified"] += 1
                verified_total += 1

            prev = recorded_row

        # Pass 2 — tenant whitelist. Any tenant_id not in DEMO_TENANTS is
        # flagged; every row from that tenant is added to broken even if
        # its hash chain happens to be internally consistent (we have no
        # policy basis for accepting rows from an unknown tenant).
        for tid, per in by_tenant.items():
            if tid not in known_tenants:
                per["unknown_tenant"] = True
                cur2 = self._conn.execute(
                    "SELECT audit_id FROM audit WHERE tenant_id = ? ORDER BY rowid ASC",
                    (tid,),
                )
                for (audit_id,) in cur2.fetchall():
                    pair = (tid, audit_id)
                    if pair not in broken:
                        broken.append(pair)

        # Pass 3 — prev_row_hash referential integrity. Every non-empty
        # prev_row_hash MUST point to some row's row_hash. Catches the
        # case where a row was written outside the AuditWriter (which is
        # the only thing that calls ``_last_row_hash`` to set prev).
        cur = self._conn.execute(
            "SELECT audit_id, tenant_id, prev_row_hash FROM audit "
            "WHERE prev_row_hash IS NOT NULL AND prev_row_hash != '' "
            "ORDER BY rowid ASC"
        )
        for audit_id, tenant_id, prev_hash in cur.fetchall():
            if prev_hash not in all_row_hashes:
                pair = (tenant_id, audit_id)
                if pair not in broken:
                    broken.append(pair)

        return {
            "verified": verified_total,
            "broken": broken,
            "by_tenant": by_tenant,
        }


writer = AuditWriter()
