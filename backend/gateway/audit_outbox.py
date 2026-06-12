"""Durable write-ahead outbox for audit rows (Q13 — invariant #4 backstop).

Invariant #4 (CLAUDE.md §4) says *every* gateway request writes exactly one
audit row — even errors. The gateway enforces the "always attempt a write"
half with a try/finally in each handler. But the primary audit store (SQLite
file or Postgres — ``AUDIT_BACKEND``) can still fail a write at runtime: disk
full, file locked by a concurrent backup, a dropped Postgres connection, or
the append-only trigger refusing the INSERT. When that happens,
``_safe_audit_write`` (main.py) must NOT re-raise —
re-raising would mask the genuine response/error the caller is about to see.
Pre-outbox the swallowed failure meant the audit row was lost *forever*, which
silently breaks invariant #4: the contract claims "exactly one row even on
errors" but a write failure leaves zero rows. For a legal-compliance audit log
that is a contract-termination-level defect.

This module closes that hole with an outbox / write-ahead pattern:

  * On primary-write failure the caller hands the *full* audit payload to
    :func:`enqueue` here, which appends one JSON line to a flat file
    (``AUDIT_OUTBOX_PATH``) and ``fsync``s it. Appending to a schema-less,
    trigger-less, lock-free flat file is far more robust than the SQLite write
    that just failed — it is the most durable thing we can still do when the
    primary store is unhappy.
  * :func:`replay_outbox` re-attempts each queued row against the real audit
    writer once the DB recovers, then rewrites the file with only the rows
    that still failed (or truncates it when all succeeded).
  * :func:`outbox_depth` reports the pending backlog as an ops/health signal.

The enqueued record stores the *primitive* identity fields (user_id,
tenant_id, role, display_name) rather than the live :class:`User` Pydantic
object, so the record is JSON-serialisable and survives a process restart.
``replay_outbox`` reconstructs a :class:`User` from those fields before calling
``audit.writer.write``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from backend.gateway import audit
from backend.shared.models import User, UserRole

logger = logging.getLogger(__name__)

# A single process-wide lock serialises concurrent appends AND the
# read-modify-rewrite that replay performs. The audit write path is already
# off the hot path (only taken when the primary write failed), so coarse
# locking here is fine and keeps the file consistent under concurrency.
_lock = threading.Lock()


def _outbox_path() -> Path:
    """Resolve the outbox path lazily.

    Read through ``backend.shared.config`` each call (rather than binding the
    constant at import time) so a test that monkeypatches
    ``config.AUDIT_OUTBOX_PATH`` to a tmp file is honoured — mirroring how
    conftest redirects ``AUDIT_DB_PATH``.
    """
    from backend.shared import config

    return Path(config.AUDIT_OUTBOX_PATH)


def _user_to_fields(user: User) -> dict[str, Any]:
    """Flatten the live User model into JSON-safe identity fields.

    We deliberately store only what ``audit.writer.write`` needs to
    reconstruct the row's identity. ``role`` is serialised as its enum value
    (a plain string) so the JSONL line carries no Python objects.
    """
    return {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "role": user.role.value,
        "display_name": user.display_name,
        "daily_token_quota": user.daily_token_quota,
    }


def _fields_to_user(fields: dict[str, Any]) -> User:
    """Rebuild a User from the flattened identity fields stored at enqueue."""
    return User(
        user_id=fields["user_id"],
        tenant_id=fields["tenant_id"],
        role=UserRole(fields["role"]),
        display_name=fields.get("display_name", fields["user_id"]),
        daily_token_quota=fields.get("daily_token_quota", 100_000),
    )


def enqueue(**kwargs: Any) -> None:
    """Append one failed audit-row payload to the durable outbox.

    ``kwargs`` is exactly what ``audit.writer.write`` would have received:
    ``user`` (a :class:`User`), ``case_id``, ``endpoint``, ``request_payload``,
    ``response_payload``, ``masked_rules``, ``model_used``, ``prompt_tokens``,
    ``completion_tokens``, ``latency_ms``, ``policy_decisions``.

    The ``user`` object is flattened into JSON-safe identity fields before
    serialisation. We reuse ``default=str`` (as audit.py's ``_hash_payload``
    does) so any stray non-JSON-native value (e.g. a datetime in a payload)
    degrades to its string form rather than raising — durability beats
    fidelity here; the worst case is a slightly stringified field, never a
    lost row.

    This function never raises to the caller: if even the flat-file append
    fails (the truly catastrophic case — disk genuinely full), we log at
    error level and return, because the caller is mid-response and must not be
    masked. That residual gap is logged loudly for ops to alert on.
    """
    try:
        kwargs = dict(kwargs)
        user = kwargs.pop("user", None)
        record: dict[str, Any] = {"kwargs": kwargs}
        if isinstance(user, User):
            record["user"] = _user_to_fields(user)
        elif user is not None:
            # Defensive: a non-User was passed (shouldn't happen). Store what
            # we can so the row isn't silently dropped.
            record["user"] = {
                "user_id": getattr(user, "user_id", None),
                "tenant_id": getattr(user, "tenant_id", None),
                "role": getattr(getattr(user, "role", None), "value", None),
                "display_name": getattr(user, "display_name", None),
            }

        line = json.dumps(record, ensure_ascii=False, default=str)

        path = _outbox_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
    except Exception:  # noqa: BLE001 — last-resort durability layer
        logger.exception(
            "audit outbox enqueue FAILED for endpoint=%s — audit row is now "
            "lost; primary audit store AND outbox are both unwritable",
            kwargs.get("endpoint") if isinstance(kwargs, dict) else None,
        )


def outbox_depth() -> int:
    """Return the number of pending (un-replayed) rows in the outbox.

    Tolerant of a missing/empty file (returns 0). Blank lines are ignored so
    the count matches what ``replay_outbox`` will actually attempt.
    """
    path = _outbox_path()
    try:
        with _lock:
            if not path.exists():
                return 0
            with open(path, encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
    except OSError:
        logger.exception("audit outbox depth check failed for %s", path)
        return 0


def replay_outbox() -> dict[str, int]:
    """Drain the outbox back into the real audit DB.

    Reads every queued row, re-attempts it via ``audit.writer.write``, and
    rewrites the file with only the rows that still failed (truncating it when
    all succeeded). Tolerant of a missing/empty file. Returns a summary:

        {"replayed": <rows written to the audit DB this call>,
         "remaining": <rows still queued after this call>}

    Idempotency note: each replay creates a *new* audit row (the writer mints
    a fresh ``audit_id`` and chains it). So re-running replay on the SAME file
    would double-write. We guard against that by removing each row from the
    file the moment its write succeeds — a successfully-replayed row is never
    seen by a subsequent replay. A row that fails again stays in the file for
    the next attempt. The whole read-modify-rewrite is done under the lock so
    a concurrent ``enqueue`` can't lose an append.
    """
    path = _outbox_path()
    with _lock:
        if not path.exists():
            return {"replayed": 0, "remaining": 0}

        with open(path, encoding="utf-8") as fh:
            raw_lines = fh.readlines()

        replayed = 0
        still_failed: list[str] = []
        for raw in raw_lines:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                # A corrupt line can never be replayed into a typed audit row;
                # keep it so an operator can inspect it rather than silently
                # dropping evidence.
                logger.error("audit outbox: undecodable line retained: %r", stripped)
                still_failed.append(stripped)
                continue

            kwargs = dict(record.get("kwargs", {}))
            user_fields = record.get("user")
            try:
                if user_fields is not None:
                    kwargs["user"] = _fields_to_user(user_fields)
                audit.writer.write(**kwargs)
                replayed += 1
            except Exception:  # noqa: BLE001 — DB may still be unhappy
                logger.exception(
                    "audit outbox replay failed for endpoint=%s — kept for retry",
                    kwargs.get("endpoint"),
                )
                still_failed.append(stripped)

        # Rewrite the file with only the rows that still failed. Write to a
        # temp file + atomic replace so a crash mid-rewrite can't truncate the
        # outbox and lose the un-replayed remainder.
        if still_failed:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for stripped in still_failed:
                    fh.write(stripped + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        else:
            # Everything drained — remove the file entirely so outbox_depth
            # short-circuits on the missing-file path.
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        return {"replayed": replayed, "remaining": len(still_failed)}
