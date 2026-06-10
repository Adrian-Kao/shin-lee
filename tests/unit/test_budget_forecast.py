"""Q18 layer 5 — budget dashboard + month-end forecast (rate_limit.py).

Layers 1-4 (per-user/tenant token quotas + cost circuit breaker) are covered
elsewhere. This module covers the missing piece: per-tenant / per-model spend
attribution, the linear run-rate month-end projection, and surfacing both in
``get_quota_snapshot`` without breaking its existing (frontend-consumed) keys.

The autouse ``_reset_module_state`` fixture in tests/conftest.py clears the
budget dicts between tests, but these unit tests poke module state directly
(bypassing the gateway), so each test that depends on a clean slate also calls
``_clear_budget_state()`` in arrange to be self-contained / order-independent.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.gateway import rate_limit as rl
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user(user_id: str = "alice", tenant_id: str = "tenant_a") -> User:
    return User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name=user_id,
    )


def _clear_budget_state() -> None:
    for name in (
        "_user_daily_tokens",
        "_tenant_monthly_tokens",
        "_daily_cost_usd",
        "_tenant_daily_cost",
        "_tenant_monthly_cost",
        "_model_daily_cost",
        "_tenant_model_daily_cost",
        "_tenant_model_monthly_cost",
    ):
        getattr(rl, name).clear()


@pytest.fixture(autouse=True)
def _clean():
    _clear_budget_state()
    yield
    _clear_budget_state()


# ---------------------------------------------------------------------------
# 1. Per-model + per-tenant spend attribution
# ---------------------------------------------------------------------------
def test_record_usage_attributes_cost_to_tenant_and_model():
    day = rl._today()
    month = rl._this_month()
    rl.record_usage(_user(), prompt_tokens=100, completion_tokens=50,
                    cost_usd=1.50, model="claude-sonnet-4-6")

    assert rl._tenant_daily_cost[("tenant_a", day)] == pytest.approx(1.50)
    assert rl._tenant_monthly_cost[("tenant_a", month)] == pytest.approx(1.50)
    assert rl._model_daily_cost[("claude-sonnet-4-6", day)] == pytest.approx(1.50)
    assert rl._tenant_model_daily_cost[("tenant_a", "claude-sonnet-4-6", day)] == pytest.approx(1.50)
    assert rl._tenant_model_monthly_cost[("tenant_a", "claude-sonnet-4-6", month)] == pytest.approx(1.50)


def test_two_models_on_one_tenant_sum_correctly():
    month = rl._this_month()
    u = _user(tenant_id="tenant_a")
    rl.record_usage(u, 100, 50, 2.00, model="claude-sonnet-4-6")
    rl.record_usage(u, 200, 80, 0.50, model="claude-haiku-4-5-20251001")

    # tenant-level total is the sum across models
    assert rl._tenant_monthly_cost[("tenant_a", month)] == pytest.approx(2.50)
    # per-model buckets stay separate
    assert rl._tenant_model_monthly_cost[("tenant_a", "claude-sonnet-4-6", month)] == pytest.approx(2.00)
    assert rl._tenant_model_monthly_cost[("tenant_a", "claude-haiku-4-5-20251001", month)] == pytest.approx(0.50)

    breakdown = rl.tenant_model_breakdown("tenant_a")
    assert len(breakdown) == 2
    # sorted by MTD spend descending -> sonnet first
    assert breakdown[0]["model"] == "claude-sonnet-4-6"
    assert breakdown[0]["month_to_date_usd"] == pytest.approx(2.00)
    assert breakdown[1]["model"] == "claude-haiku-4-5-20251001"


def test_two_tenants_stay_separate():
    month = rl._this_month()
    rl.record_usage(_user(tenant_id="tenant_a"), 100, 50, 3.00, model="claude-sonnet-4-6")
    rl.record_usage(_user(tenant_id="tenant_b"), 100, 50, 7.00, model="claude-sonnet-4-6")

    assert rl._tenant_monthly_cost[("tenant_a", month)] == pytest.approx(3.00)
    assert rl._tenant_monthly_cost[("tenant_b", month)] == pytest.approx(7.00)
    # tenant_b's spend must not leak into tenant_a's breakdown
    a_models = rl.tenant_model_breakdown("tenant_a")
    assert a_models[0]["month_to_date_usd"] == pytest.approx(3.00)


def test_model_none_falls_back_to_sentinel_bucket():
    """Backward-compat path: callers that don't pass model still attribute spend."""
    day = rl._today()
    rl.record_usage(_user(), 100, 50, 1.00)  # no model kwarg
    assert rl._tenant_model_daily_cost[("tenant_a", rl._UNKNOWN_MODEL, day)] == pytest.approx(1.00)
    # and the coarse tenant bucket still gets it
    assert rl._tenant_daily_cost[("tenant_a", day)] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# 2. Month-end forecast (run-rate)
# ---------------------------------------------------------------------------
def test_projection_linear_run_rate():
    # $30 month-to-date on day 10 of a 30-day month (June 2026 has 30 days)
    # -> run-rate projects $90 at month-end.
    month = "2026-06"
    rl._tenant_monthly_cost[("tenant_a", month)] = 30.0
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)

    out = rl.project_month_end_cost("tenant_a", now=now)
    assert out["month_to_date_usd"] == pytest.approx(30.0)
    assert out["days_elapsed"] == 10
    assert out["days_in_month"] == 30
    assert out["projected_month_end_usd"] == pytest.approx(90.0)


def test_projection_day_one_no_divide_by_zero():
    month = "2026-06"
    rl._tenant_monthly_cost[("tenant_a", month)] = 5.0
    now = datetime(2026, 6, 1, 0, 30, tzinfo=timezone.utc)

    out = rl.project_month_end_cost("tenant_a", now=now)
    assert out["days_elapsed"] == 1
    # day-1 projection = mtd * days_in_month
    assert out["projected_month_end_usd"] == pytest.approx(5.0 * 30)


def test_projection_zero_spend():
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    out = rl.project_month_end_cost("tenant_a", now=now)
    assert out["month_to_date_usd"] == pytest.approx(0.0)
    assert out["projected_month_end_usd"] == pytest.approx(0.0)


def test_projected_vs_cap_pct(monkeypatch):
    # Configure a USD month cap on tenant_a and check the percentage.
    from backend.shared.config import settings
    tenants = {
        "tenant_a": {"name": "Apex", "monthly_token_cap": 50_000_000,
                     "monthly_cost_cap_usd": 100.0},
    }
    monkeypatch.setattr(settings, "DEMO_TENANTS", tenants)

    month = "2026-06"
    rl._tenant_monthly_cost[("tenant_a", month)] = 30.0
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)  # projects $90

    out = rl.project_month_end_cost("tenant_a", now=now)
    assert out["tenant_monthly_cap_usd"] == pytest.approx(100.0)
    # 90 / 100 = 90%
    assert out["projected_vs_cap_pct"] == pytest.approx(90.0)


def test_no_cap_configured_yields_none_pct():
    # tenant_a default config ships no monthly_cost_cap_usd.
    month = "2026-06"
    rl._tenant_monthly_cost[("tenant_a", month)] = 30.0
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    out = rl.project_month_end_cost("tenant_a", now=now)
    assert out["tenant_monthly_cap_usd"] is None
    assert out["projected_vs_cap_pct"] is None


# ---------------------------------------------------------------------------
# 3. get_quota_snapshot — new budget block + backward compat
# ---------------------------------------------------------------------------
_LEGACY_SNAPSHOT_KEYS = {
    "user_daily_used",
    "user_daily_limit",
    "tenant_monthly_used",
    "tenant_monthly_cap",
    "circuit_breaker",
}


def test_snapshot_keeps_all_legacy_keys():
    snap = rl.get_quota_snapshot(_user())
    # every old key still present (frontend + existing tests read these)
    assert _LEGACY_SNAPSHOT_KEYS.issubset(snap.keys())
    # circuit_breaker shape unchanged
    assert set(snap["circuit_breaker"]) == {"tripped", "current_usd", "threshold_usd"}


def test_snapshot_includes_budget_block():
    u = _user()
    rl.record_usage(u, 100, 50, 2.00, model="claude-sonnet-4-6")

    snap = rl.get_quota_snapshot(u)
    assert "budget" in snap
    budget = snap["budget"]
    assert budget["tenant_id"] == "tenant_a"
    assert isinstance(budget["per_model"], list)
    assert budget["per_model"][0]["model"] == "claude-sonnet-4-6"
    assert budget["per_model"][0]["month_to_date_usd"] == pytest.approx(2.00)
    assert "forecast" in budget
    assert set(budget["forecast"]) >= {
        "month_to_date_usd", "projected_month_end_usd",
        "days_elapsed", "days_in_month",
        "tenant_monthly_cap_usd", "projected_vs_cap_pct",
    }
    # no USD cap configured by default -> status "no_cap"
    assert budget["status"] == "no_cap"
    assert budget["will_exceed_cap"] is False


def test_snapshot_status_will_exceed(monkeypatch):
    from backend.shared.config import settings
    monkeypatch.setattr(
        settings,
        "DEMO_TENANTS",
        {"tenant_a": {"name": "Apex", "monthly_token_cap": 50_000_000,
                      "monthly_cost_cap_usd": 10.0}},
    )
    u = _user()
    # Big spend early in the month so the run-rate projection blows past $10.
    rl.record_usage(u, 100, 50, 9.0, model="claude-opus-4-7")

    snap = rl.get_quota_snapshot(u)
    budget = snap["budget"]
    # projection scales 9.0 up across the month -> well over cap unless it's
    # literally the last day; assert the flag is consistent with the forecast.
    fc = budget["forecast"]
    expected_exceed = fc["projected_month_end_usd"] > fc["tenant_monthly_cap_usd"]
    assert budget["will_exceed_cap"] is expected_exceed
    assert budget["status"] == ("will_exceed" if expected_exceed else "on_track")
