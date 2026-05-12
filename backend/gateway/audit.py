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


writer = AuditWriter()
