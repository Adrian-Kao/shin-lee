"""Rate limit + token quota + cost circuit breaker (Q18 全套).

Three layers of protection:
    1. Per-request hard cap (32k tokens single prompt)  — anti-abuse
    2. Per-user daily token quota                       — fair usage
    3. Per-tenant monthly cap                           — contract enforcement
    4. Cost circuit breaker                             — daily $ alert / auto-degrade

Production: replace in-memory state with Redis (atomic INCR + TTL).
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status

from backend.shared.config import settings
from backend.shared.models import User


# Token bucket for RPM (requests per minute)
class _TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill = refill_per_sec
        self.last = time.monotonic()

    def consume(self, n: int = 1) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill)
        self.last = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


_user_rpm: dict[str, _TokenBucket] = {}
_user_daily_tokens: dict[tuple[str, str], int] = defaultdict(int)  # (user_id, YYYY-MM-DD) -> tokens
_tenant_monthly_tokens: dict[tuple[str, str], int] = defaultdict(int)  # (tenant_id, YYYY-MM) -> tokens
_daily_cost_usd: dict[str, float] = defaultdict(float)  # YYYY-MM-DD -> usd


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def check_rpm(user: User) -> None:
    """Layer 1: per-user RPM."""
    bucket = _user_rpm.get(user.user_id)
    if bucket is None:
        bucket = _TokenBucket(
            capacity=settings.DEFAULT_RPM,
            refill_per_sec=settings.DEFAULT_RPM / 60.0,
        )
        _user_rpm[user.user_id] = bucket
    if not bucket.consume():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"rate limit exceeded ({settings.DEFAULT_RPM} RPM). retry in ~1s.",
        )


def check_request_size(prompt_tokens_estimate: int) -> None:
    """Layer 2: single request hard cap."""
    if prompt_tokens_estimate > settings.REQUEST_HARD_LIMIT_TOKENS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"prompt too large: {prompt_tokens_estimate} > {settings.REQUEST_HARD_LIMIT_TOKENS}. "
            "split into smaller chunks or reduce context.",
        )


def check_quotas(user: User, tokens_about_to_use: int) -> None:
    """Layer 3 + 4: daily user quota + monthly tenant cap."""
    user_used = _user_daily_tokens[(user.user_id, _today())]
    if user_used + tokens_about_to_use > user.daily_token_quota:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"daily token quota exceeded: used={user_used}, "
            f"requested={tokens_about_to_use}, limit={user.daily_token_quota}",
        )

    tenant_used = _tenant_monthly_tokens[(user.tenant_id, _this_month())]
    tenant_cap = settings.DEMO_TENANTS.get(user.tenant_id, {}).get(
        "monthly_token_cap", settings.TENANT_MONTHLY_TOKENS
    )
    if tenant_used + tokens_about_to_use > tenant_cap:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"tenant monthly cap exceeded: used={tenant_used}, "
            f"requested={tokens_about_to_use}, cap={tenant_cap}. "
            "contact billing to upgrade.",
        )


def record_usage(user: User, prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    """Account for usage after the LLM call.  Trip the breaker if needed."""
    total = prompt_tokens + completion_tokens
    _user_daily_tokens[(user.user_id, _today())] += total
    _tenant_monthly_tokens[(user.tenant_id, _this_month())] += total
    _daily_cost_usd[_today()] += cost_usd


def cost_circuit_state() -> dict:
    """Layer 5: cost circuit breaker.

    POC: returns {tripped, current_usd, threshold_usd}.
    When tripped, llm_router auto-degrades reasoning model → cheap model.
    """
    today_cost = _daily_cost_usd[_today()]
    return {
        "tripped": today_cost >= settings.COST_CIRCUIT_DAILY_USD,
        "current_usd": round(today_cost, 4),
        "threshold_usd": settings.COST_CIRCUIT_DAILY_USD,
    }


def get_quota_snapshot(user: User) -> dict:
    """For the IT admin dashboard (Q19 cost observability)."""
    return {
        "user_daily_used": _user_daily_tokens[(user.user_id, _today())],
        "user_daily_limit": user.daily_token_quota,
        "tenant_monthly_used": _tenant_monthly_tokens[(user.tenant_id, _this_month())],
        "tenant_monthly_cap": settings.DEMO_TENANTS.get(user.tenant_id, {}).get(
            "monthly_token_cap", settings.TENANT_MONTHLY_TOKENS
        ),
        "circuit_breaker": cost_circuit_state(),
    }
