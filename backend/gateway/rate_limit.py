"""Rate limit + token quota + cost circuit breaker (Q18 全套).

Three layers of protection:
    1. Per-request hard cap (32k tokens single prompt)  — anti-abuse
    2. Per-user daily token quota                       — fair usage
    3. Per-tenant monthly cap                           — contract enforcement
    4. Cost circuit breaker                             — daily $ alert / auto-degrade

Production: replace in-memory state with Redis (atomic INCR + TTL).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status

from backend.shared.config import settings
from backend.shared.models import User


logger = logging.getLogger(__name__)


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

# Day 8 post-review (Important #1 from Chunk A/B review): per-IP RPM bucket
# for /v1/auth/login. Login is pre-auth so we can't key on user_id; key on
# client IP instead. Stricter than DEFAULT_RPM (10/min vs 30/min) because the
# attack model is "spray demo-{user_id} guesses until one lands".
_login_ip_rpm: dict[str, _TokenBucket] = {}


# ---------------------------------------------------------------------------
# Pricing — Anthropic public list price as of 2026-05.  USD per **1M** tokens.
# Keys are the canonical model IDs we ship in shared/config.py defaults plus
# anything else we might let an operator set via LLM_MODEL_* env vars.
# Update with care: this dict is the single source of truth for cost_meta.
# ---------------------------------------------------------------------------
_MODEL_PRICING_USD_PER_M: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_creation": 1.25,
        "cache_read": 0.10,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
        "cache_creation": 18.75,
        "cache_read": 1.50,
    },
}

# Fallback used when (a) LLM_MODE=mock so model strings are "claude-sonnet-mock"
# style synthetic IDs, or (b) LLM_MODE=local (Ollama, on-prem, marginal cost ≈ 0).
# Values picked to roughly match the OLD `(p*3 + c*15)/1M` rule of thumb so
# pre-Anthropic dashboards don't suddenly jump to $0.
_FALLBACK_PRICING: dict[str, float] = {
    "input": 3.00,
    "output": 15.00,
    "cache_creation": 0.0,
    "cache_read": 0.0,
}


def _pricing_for(model: str) -> tuple[dict[str, float], str]:
    """Pick the pricing row for ``model`` and return its provenance label.

    Provenance values:

    * ``"mock"``     — model string is a mock identifier (``*-mock`` or
      starts with ``mock``). Cost numbers are synthetic and MUST NOT be
      trusted by billing dashboards.
    * ``"exact"``    — model matched an entry in
      ``_MODEL_PRICING_USD_PER_M`` directly or via prefix sweep. Numbers
      are the published Anthropic list price as of the dict's last update;
      cost can be reported in the audit row at face value.
    * ``"fallback"`` — neither mock nor known. The conservative
      sonnet-equivalent fallback fires; this typically means a typo in
      ``LLM_MODEL_REASONING`` (e.g. ``claude-sonet-4-6``) or a deployed
      model whose pricing we haven't entered yet. A WARNING is logged so
      the operator notices BEFORE the audit row reports a fictitious cost.

    The fallback case is the audit finding M-3: previously this silently
    returned the fallback dict and any downstream caller had no way to
    flag the cost as estimated. Returning provenance alongside the prices
    lets ``estimate_cost`` propagate it into ``cost_meta`` so the audit row
    + billing dashboard can show "this number is approximate".
    """
    if model.endswith("-mock") or model.startswith("mock"):
        return _FALLBACK_PRICING, "mock"
    if model in _MODEL_PRICING_USD_PER_M:
        return _MODEL_PRICING_USD_PER_M[model], "exact"
    for known, prices in _MODEL_PRICING_USD_PER_M.items():
        if model.startswith(known):
            return prices, "exact"
    # M-3 fix: log the fallback so a typo'd LLM_MODEL_* env var (which
    # silently zeros cache pricing) shows up in the operator's log scrape
    # rather than masquerading as $0.00.
    logger.warning(
        "rate_limit._pricing_for: unknown model %r — using conservative "
        "sonnet-equivalent fallback. Add this model to "
        "_MODEL_PRICING_USD_PER_M or fix the LLM_MODEL_* env var. "
        "cost_provenance will be marked 'fallback' downstream.",
        model,
    )
    return _FALLBACK_PRICING, "fallback"


def cost_provenance_for(model: str) -> str:
    """Public accessor: provenance label without recomputing prices.

    Used by callers that already estimated cost and now want to tag the
    audit row / cost_meta with how trustworthy the number is.
    """
    return _pricing_for(model)[1]


def estimate_cost(model: str, usage: dict[str, int]) -> float:
    """Compute USD cost for an Anthropic-style usage record.

    `usage` keys we look at (all optional, default 0):
      - input_tokens               (NB: in Anthropic semantics this *excludes*
                                    cache_read / cache_creation — see SDK docs)
      - output_tokens
      - cache_creation_input_tokens
      - cache_read_input_tokens

    For legacy callers we also accept `prompt_tokens` as an alias for input.
    """
    prices, _provenance = _pricing_for(model)
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)

    cost = (
        input_tokens * prices.get("input", 0.0)
        + output_tokens * prices.get("output", 0.0)
        + cache_creation * prices.get("cache_creation", 0.0)
        + cache_read * prices.get("cache_read", 0.0)
    ) / 1_000_000.0
    return cost


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


def check_login_rpm(client_ip: str) -> None:
    """Pre-auth RPM check for /v1/auth/login (keyed on client IP, not user_id).

    Day 8 post-review fix: previously the login endpoint had no rate limit
    at all, so an attacker reaching the gateway could brute-force any user's
    demo password (sha256 hash; rainbow-tablable for short passwords). This
    bounds the brute-force rate to LOGIN_RPM per minute per IP. Default 10
    is stricter than DEFAULT_RPM=30 because login is the front door and the
    threat model is harsher.

    `client_ip` should come from `request.client.host`. If the request
    routed through a trusted reverse proxy (digiRunner), upstream IP is
    fine — we still get distinct buckets per real client because digiRunner
    spreads connections across worker pool.
    """
    if not client_ip:
        # Defensive fallback — if we can't identify the caller, share a
        # single bucket so a misconfigured peer can't bypass the limit by
        # leaving client_ip empty.
        client_ip = "_unknown_"
    bucket = _login_ip_rpm.get(client_ip)
    if bucket is None:
        bucket = _TokenBucket(
            capacity=settings.LOGIN_RPM,
            refill_per_sec=settings.LOGIN_RPM / 60.0,
        )
        _login_ip_rpm[client_ip] = bucket
    if not bucket.consume():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many login attempts ({settings.LOGIN_RPM}/min/IP). retry in ~1s.",
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
