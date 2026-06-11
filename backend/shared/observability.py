"""Observability shared layer (Q19): Sentry + structured logging + correlation IDs.

Two responsibilities, both shared verbatim by the gateway and the ai_engine so a
single request is traceable end to end:

1. **Sentry** — :func:`init_sentry` wires the optional crash reporter. No-op when
   ``SENTRY_DSN`` is unset (local demos / mock mode don't need an account).

2. **Correlation / request IDs + structured logging** — the heart of Q19's
   "trace one request across both services". The flow is:

       client ──X-Request-ID──▶ gateway ──X-Request-ID──▶ ai_engine
                                  │                          │
                                  ▼                          ▼
                            JSON log line               JSON log line
                            {"request_id": "...", ...}   {"request_id": "...", ...}

   The gateway's middleware *accepts* an inbound ``X-Request-ID`` (so an upstream
   reverse proxy / digiRunner can supply the trace id) or *generates* one when
   absent, binds it into a :class:`contextvars.ContextVar`, echoes it on the
   response, and — via :func:`request_id_headers` — propagates it on the
   gateway→ai_engine HTTP call. The ai_engine's middleware reads the inbound
   header back out and binds it into its own context, so both services' JSON log
   lines carry the SAME ``request_id``.

   The contextvar is the binding mechanism: a :class:`logging.Filter`
   (:class:`RequestIdLogFilter`) reads it at emit time and stamps every log
   record, so application code logs normally (``logger.info("...")``) and the
   request id appears automatically — no threading of an id through every call.

Env vars:
    SENTRY_DSN                 enable Sentry (else silent no-op)
    SENTRY_ENVIRONMENT         defaults to "dev"
    SENTRY_TRACES_SAMPLE_RATE  defaults to 0.1
    SENTRY_RELEASE             optional (git sha / build version)
    LOG_FORMAT                 "json" (default) or "text" — text for human dev
    LOG_LEVEL                  defaults to "INFO"
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correlation / request-id context.
# ---------------------------------------------------------------------------
# The canonical inbound/outbound header. Case-insensitive on the wire; we read
# it lower-cased (Starlette normalises) and emit it in canonical form.
REQUEST_ID_HEADER = "X-Request-ID"

# A bounded id length so a hostile upstream can't smuggle a megabyte "id" into
# every log line. 200 chars comfortably fits a UUID, a W3C traceparent, or a
# digiRunner correlation token while bounding the blast radius.
_MAX_REQUEST_ID_LEN = 200

# The single source of truth for "which request am I handling right now". A
# ContextVar is asyncio-task-local AND thread-local: FastAPI runs sync handlers
# in a threadpool and async handlers on the loop, and a ContextVar is correct
# for both (unlike threading.local, which leaks across pooled async tasks).
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "patentmind_request_id", default=None
)


def new_request_id() -> str:
    """Mint a fresh request id (uuid4 hex, no dashes — compact in log lines)."""
    return uuid.uuid4().hex


def _sanitise_request_id(raw: str | None) -> str | None:
    """Clean an inbound request id: trim, cap length, drop control chars.

    Returns ``None`` for empty/whitespace input so the caller can fall back to
    a freshly generated id. We keep only printable, non-whitespace-internal
    characters so a forged ``X-Request-ID`` can't inject a newline (log
    forging) or blow up the JSON encoder.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Strip anything that could break a single-line JSON log record. Keep it
    # liberal (alnum, dash, underscore, dot, colon) — covers UUIDs and W3C
    # traceparents — but reject the rest rather than escape it.
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in "-_.:")
    if not cleaned:
        return None
    return cleaned[:_MAX_REQUEST_ID_LEN]


def bind_request_id(raw: str | None) -> str:
    """Bind ``raw`` (or a fresh id when absent/invalid) as the current request id.

    Returns the bound id so the caller can echo it on the response header.
    """
    rid = _sanitise_request_id(raw) or new_request_id()
    _request_id_var.set(rid)
    return rid


def current_request_id() -> str | None:
    """The request id bound to the current context, or ``None`` outside a request."""
    return _request_id_var.get()


def reset_request_id() -> None:
    """Clear the bound request id (defence against leakage between contexts)."""
    _request_id_var.set(None)


def request_id_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers to propagate the current request id on an outbound call.

    Merges onto ``extra`` (e.g. the gateway's ``X-Internal-Token`` headers) so a
    caller can do ``client.post(url, headers=request_id_headers(_internal_headers()))``
    and get both the auth token AND the correlation id forwarded. When no request
    id is bound (call made outside a request context), one is minted so the
    downstream service still gets *a* trace id rather than none.
    """
    headers: dict[str, str] = dict(extra or {})
    rid = current_request_id() or new_request_id()
    headers[REQUEST_ID_HEADER] = rid
    return headers


# ---------------------------------------------------------------------------
# Structured logging.
# ---------------------------------------------------------------------------
class RequestIdLogFilter(logging.Filter):
    """Stamp every log record with the current request id.

    Attached to the root handler so application code (``logger.info(...)``) gets
    the id for free. Records emitted outside a request context get
    ``request_id="-"`` (a stable sentinel that's easy to grep out).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


# Standard LogRecord attributes we must NOT re-serialise as "extra" fields (they
# are either already captured by the formatter or are internal machinery).
_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "request_id",
        "taskName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object.

    Always includes ``ts``, ``level``, ``logger``, ``message``, ``service`` and
    ``request_id``. Any ``logger.info("...", extra={...})`` keys are folded in as
    top-level fields (so structured context survives), and an exception, if
    present, is rendered into ``exc``.
    """

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        # Fold structured `extra=` fields in as top-level keys.
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)  # ensure serialisable; skip otherwise
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service: str) -> None:
    """Install structured (JSON) logging + the request-id filter for ``service``.

    Idempotent: re-calling it replaces the root handler rather than stacking a
    second one (so importing both apps in one pytest session doesn't double-log).
    Honours ``LOG_FORMAT`` (``json`` default, ``text`` for human-readable dev)
    and ``LOG_LEVEL`` (``INFO`` default).

    The request-id filter is attached to the handler so EVERY record — including
    uvicorn / starlette access logs that propagate to root — carries the id.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv("LOG_FORMAT", "json").strip().lower()

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdLogFilter())
    if fmt == "text":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    else:
        handler.setFormatter(JsonLogFormatter(service))

    root = logging.getLogger()
    # Remove any handler WE previously installed (tagged) so re-init is clean,
    # but leave handlers installed by the test harness / pytest capture alone.
    for existing in list(root.handlers):
        if getattr(existing, "_patentmind_obs", False):
            root.removeHandler(existing)
    handler._patentmind_obs = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)


def init_sentry(service_name: str) -> bool:
    """Init Sentry for `service_name` if SENTRY_DSN is set. Returns True if active."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning(
            "SENTRY_DSN set but sentry-sdk not installed. Run: pip install sentry-sdk[fastapi]"
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "dev"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        release=os.getenv("SENTRY_RELEASE") or None,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        # Don't send PII — OA content goes through redaction; the rest is benign.
        send_default_pii=False,
        # Tag every event with the service so we can split alerts.
        before_send=lambda event, hint: _tag_service(event, service_name),
    )
    logger.info(
        "Sentry initialised for service=%s environment=%s",
        service_name,
        os.getenv("SENTRY_ENVIRONMENT", "dev"),
    )
    return True


def _tag_service(event: dict, service_name: str) -> dict:
    tags = event.setdefault("tags", {})
    tags["service"] = service_name
    return event


def sentry_enabled() -> bool:
    """Cheap check for /health endpoints to report status."""
    return bool(os.getenv("SENTRY_DSN", "").strip())
