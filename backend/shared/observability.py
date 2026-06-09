"""Sentry init for both gateway and ai_engine.

Call init_sentry(service_name) at the top of each FastAPI app's main.py
BEFORE FastAPI() instantiation. No-op when SENTRY_DSN env var is unset
(local demos / mock mode don't need an account).

Env vars:
    SENTRY_DSN              required to enable (else silent no-op)
    SENTRY_ENVIRONMENT      defaults to "dev"
    SENTRY_TRACES_SAMPLE_RATE  defaults to 0.1
    SENTRY_RELEASE          optional (git sha / build version)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


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
