"""Rate limit + token quota + cost circuit breaker (Q18 全套).

Three layers of protection:
    1. Per-request hard cap (32k tokens single prompt)  — anti-abuse
    2. Per-user daily token quota                       — fair usage
    3. Per-tenant monthly cap                           — contract enforcement
    4. Cost circuit breaker                             — daily $ alert / auto-degrade

Production: replace in-memory state with Redis (atomic INCR + TTL).
"""
from __future__ import annotations

import calendar
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

# Q18 layer 5 (budget dashboard + month-end forecast). The dicts above answer
# "are we over a token/cost limit *right now*"; these answer "where is the
# money going, and where will we land at month-end". Keyed finely so the
# dashboard can show per-tenant / per-model spend and run-rate projection.
#   - _tenant_daily_cost  : (tenant_id, YYYY-MM-DD) -> usd   (today, per tenant)
#   - _tenant_monthly_cost: (tenant_id, YYYY-MM)    -> usd   (MTD, per tenant)
#   - _model_daily_cost   : (model, YYYY-MM-DD)     -> usd   (today, per model)
#   - _tenant_model_daily_cost   : (tenant_id, model, YYYY-MM-DD) -> usd
#   - _tenant_model_monthly_cost : (tenant_id, model, YYYY-MM)    -> usd
# The tenant_model_* dicts are what the dashboard's per-model breakdown reads;
# the coarser _tenant_*/_model_* dicts give cheap totals without re-summing.
_UNKNOWN_MODEL = "_unknown_"  # sentinel when record_usage gets model=None
_tenant_daily_cost: dict[tuple[str, str], float] = defaultdict(float)
_tenant_monthly_cost: dict[tuple[str, str], float] = defaultdict(float)
_model_daily_cost: dict[tuple[str, str], float] = defaultdict(float)
_tenant_model_daily_cost: dict[tuple[str, str, str], float] = defaultdict(float)
_tenant_model_monthly_cost: dict[tuple[str, str, str], float] = defaultdict(float)

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


def record_usage(
    user: User,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    model: str | None = None,
) -> None:
    """Account for usage after the LLM call.  Trip the breaker if needed.

    ``model`` is OPTIONAL and keyword-only-friendly: existing callers
    (``backend/gateway/main.py`` analyze + OCR-upload paths) pass
    ``prompt_tokens`` / ``completion_tokens`` / ``cost_usd`` by keyword and do
    NOT pass ``model``; the ``None`` default keeps them working unchanged.
    When ``model`` is provided (or later wired from ``obs["model_used"]``) the
    spend is additionally attributed to per-tenant and per-model buckets so the
    Q18 budget dashboard can break cost down and forecast month-end.
    """
    total = prompt_tokens + completion_tokens
    day = _today()
    month = _this_month()
    _user_daily_tokens[(user.user_id, day)] += total
    _tenant_monthly_tokens[(user.tenant_id, month)] += total
    _daily_cost_usd[day] += cost_usd

    # Q18 layer 5 — attributable spend (tenant + model).
    model_key = model or _UNKNOWN_MODEL
    _tenant_daily_cost[(user.tenant_id, day)] += cost_usd
    _tenant_monthly_cost[(user.tenant_id, month)] += cost_usd
    _model_daily_cost[(model_key, day)] += cost_usd
    _tenant_model_daily_cost[(user.tenant_id, model_key, day)] += cost_usd
    _tenant_model_monthly_cost[(user.tenant_id, model_key, month)] += cost_usd


def _tenant_monthly_cost_cap(tenant_id: str) -> float | None:
    """Per-tenant month-end USD cap, if the operator configured one.

    DEMO_TENANTS today only ships a token cap (``monthly_token_cap``); a USD
    cap is optional. Returns the ``monthly_cost_cap_usd`` value when present,
    else None (no contractual dollar ceiling — forecast still reported,
    just without a vs-cap percentage).
    """
    cap = settings.DEMO_TENANTS.get(tenant_id, {}).get("monthly_cost_cap_usd")
    return float(cap) if cap is not None else None


def project_month_end_cost(tenant_id: str, now: datetime | None = None) -> dict:
    """Q18 layer 5 — linear run-rate projection of month-end spend.

    Given month-to-date (MTD) spend and the elapsed fraction of the current
    month, extrapolate where the tenant lands at month-end:

        projected = mtd / elapsed_fraction
                  = mtd * days_in_month / days_elapsed

    ``now`` is injectable so tests can pin the date; production passes None
    and we read the wall clock (UTC, matching _today/_this_month).

    Edge cases:
      * Day 1 — ``days_elapsed == 1``; projection = ``mtd * days_in_month``
        (no divide-by-zero; treats day-1 spend as the daily run-rate).
      * MTD == 0 — projection is 0.0 (and 0% of any cap).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    mtd = _tenant_monthly_cost[(tenant_id, month)]
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_elapsed = now.day  # 1-based; day 1 -> 1, never 0

    # run-rate: scale MTD by (whole month / elapsed-so-far).
    projected = mtd * days_in_month / days_elapsed

    cap = _tenant_monthly_cost_cap(tenant_id)
    projected_vs_cap_pct = (
        round(projected / cap * 100.0, 2) if cap else None
    )

    return {
        "month": month,
        "month_to_date_usd": round(mtd, 4),
        "projected_month_end_usd": round(projected, 4),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "tenant_monthly_cap_usd": cap,
        "projected_vs_cap_pct": projected_vs_cap_pct,
    }


def tenant_model_breakdown(tenant_id: str, now: datetime | None = None) -> list[dict]:
    """Per-model spend for ``tenant_id`` (today + month-to-date).

    Returns one row per model the tenant has spent on this month, sorted by
    month-to-date spend descending so the dashboard shows the biggest line
    items first.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    # Collect models the tenant touched this month.
    models: set[str] = {
        m for (t, m, mo) in _tenant_model_monthly_cost if t == tenant_id and mo == month
    }
    rows = [
        {
            "model": model,
            "today_usd": round(_tenant_model_daily_cost[(tenant_id, model, day)], 4),
            "month_to_date_usd": round(_tenant_model_monthly_cost[(tenant_id, model, month)], 4),
        }
        for model in models
    ]
    rows.sort(key=lambda r: r["month_to_date_usd"], reverse=True)
    return rows


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
    """For the IT admin dashboard (Q19 cost observability).

    The original keys (user_daily_*, tenant_monthly_*, circuit_breaker) are
    token-quota + breaker state and are consumed by the frontend token bar +
    existing tests — they are kept verbatim. The Q18-layer-5 ``budget`` block
    is ADDED alongside: per-model $ breakdown, month-end forecast, and an
    on-track / will-exceed flag so a client's IT can watch the spend in real
    time.
    """
    forecast = project_month_end_cost(user.tenant_id)
    cap = forecast["tenant_monthly_cap_usd"]
    will_exceed_cap = bool(
        cap is not None and forecast["projected_month_end_usd"] > cap
    )
    return {
        "user_daily_used": _user_daily_tokens[(user.user_id, _today())],
        "user_daily_limit": user.daily_token_quota,
        "tenant_monthly_used": _tenant_monthly_tokens[(user.tenant_id, _this_month())],
        "tenant_monthly_cap": settings.DEMO_TENANTS.get(user.tenant_id, {}).get(
            "monthly_token_cap", settings.TENANT_MONTHLY_TOKENS
        ),
        "circuit_breaker": cost_circuit_state(),
        "budget": {
            "tenant_id": user.tenant_id,
            "per_model": tenant_model_breakdown(user.tenant_id),
            "forecast": forecast,
            # status flag the dashboard can colour: cap configured + projected
            # over it = "will_exceed", cap configured + under = "on_track",
            # no cap configured = "no_cap".
            "status": (
                "no_cap" if cap is None else ("will_exceed" if will_exceed_cap else "on_track")
            ),
            "will_exceed_cap": will_exceed_cap,
        },
    }
