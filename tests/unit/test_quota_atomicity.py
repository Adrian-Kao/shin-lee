"""Q18 quota atomicity + ordering + cost-breaker tests (Day 13I).

These tests lock in the production-grade guarantees of the rate-limit layer:

  1. ATOMIC RESERVE — `check_quotas` increments the counter and compares to the
     cap together, so N concurrent requests can NEVER all pass when only some
     fit. A pre-fix read-then-act `check` (which is what the original code did,
     leaving the increment to `record_usage`) would let every concurrent caller
     read the same `used=0` and oversell the quota. The concurrency test below
     fires many threads at a quota that fits only a few and asserts the number
     of successes is bounded exactly by the cap.

  2. RECONCILE — `record_usage(reserved_tokens=...)` adjusts the counter by the
     actual-vs-reserved DELTA so the reservation isn't double counted, and an
     over-estimate releases the unused headroom.

  3. ORDERING (invariant #8) — quota is reserved BEFORE the (simulated) LLM
     call; the cost circuit breaker is read SECOND. We assert the breaker does
     not gate the reservation.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from backend.gateway import rate_limit as rl
from backend.shared.config import settings
from backend.shared.models import User, UserRole


@pytest.fixture(autouse=True)
def _clean():
    """Wipe every rate-limit counter before and after each test."""
    def _wipe():
        for name in (
            "_user_rpm", "_login_ip_rpm", "_user_daily_tokens",
            "_tenant_monthly_tokens", "_daily_cost_usd",
            "_tenant_daily_cost", "_tenant_monthly_cost", "_model_daily_cost",
            "_tenant_model_daily_cost", "_tenant_model_monthly_cost",
        ):
            getattr(rl, name).clear()
    _wipe()
    yield
    _wipe()


def _user(user_id="alice", tenant_id="tenant_a", quota=1_000) -> User:
    return User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name=user_id,
        daily_token_quota=quota,
    )


# ---------------------------------------------------------------------------
# 1. Atomic reserve — single-threaded correctness
# ---------------------------------------------------------------------------
def test_check_quotas_reserves_and_blocks_at_cap():
    u = _user(quota=100)
    # First reservation of 60 fits.
    assert rl.check_quotas(u, 60) == 60
    # Second reservation of 60 would bring total to 120 > 100 → 402.
    with pytest.raises(HTTPException) as ei:
        rl.check_quotas(u, 60)
    assert ei.value.status_code == 402
    # The rejected reservation must NOT have incremented the counter.
    assert rl._user_daily_tokens[(u.user_id, rl._today())] == 60


def test_failed_tenant_reservation_rolls_back_user_counter():
    """If the per-user check passes but the per-tenant cap fails, the user
    counter increment must be rolled back so a retry isn't penalised."""
    monthly_cap = rl._tenant_cap_for("tenant_a")
    u = _user(quota=monthly_cap + 1_000)  # user quota generous; tenant cap binds
    # Reserve right up to (but not over) the tenant cap.
    rl.check_quotas(u, monthly_cap)
    user_before = rl._user_daily_tokens[(u.user_id, rl._today())]
    # Next reservation breaks the tenant cap → 402, user counter unchanged.
    with pytest.raises(HTTPException) as ei:
        rl.check_quotas(u, 1)
    assert ei.value.status_code == 402
    assert rl._user_daily_tokens[(u.user_id, rl._today())] == user_before


# ---------------------------------------------------------------------------
# 2. Reconcile
# ---------------------------------------------------------------------------
def test_record_usage_reconciles_reservation_delta():
    u = _user(quota=1_000)
    reserved = rl.check_quotas(u, 300)  # reserve estimate of 300
    assert rl._user_daily_tokens[(u.user_id, rl._today())] == 300
    # Actual spend was 250 (estimate over-shot by 50). Reconcile.
    rl.record_usage(u, prompt_tokens=200, completion_tokens=50,
                    cost_usd=0.10, reserved_tokens=reserved)
    # Counter now reflects true spend (250), not 300+250.
    assert rl._user_daily_tokens[(u.user_id, rl._today())] == 250


def test_record_usage_without_reservation_is_additive():
    """Legacy callers / direct budget tests pass no reserved_tokens → full add."""
    u = _user()
    rl.record_usage(u, prompt_tokens=100, completion_tokens=50, cost_usd=0.10)
    assert rl._user_daily_tokens[(u.user_id, rl._today())] == 150


# ---------------------------------------------------------------------------
# 3. Concurrency — no oversell under parallel reservations
# ---------------------------------------------------------------------------
def test_concurrent_reservations_never_oversell():
    """Fire many threads at a per-user quota that fits only a fixed number of
    reservations. The count of successful reservations must equal exactly the
    cap // amount — the atomic reserve forbids an (N+1)th from slipping through
    a read-then-act race."""
    amount = 10
    cap = 100  # exactly 10 reservations fit
    u = _user(quota=cap)
    n_threads = 50
    successes: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()  # maximise contention — all threads hit at once
        try:
            rl.check_quotas(u, amount)
            with lock:
                successes.append(1)
        except HTTPException:
            pass

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(successes) == cap // amount, (
        f"expected exactly {cap // amount} reservations to fit, got {sum(successes)} "
        "— atomic reserve oversold the quota under concurrency"
    )
    # And the counter never exceeded the cap.
    assert rl._user_daily_tokens[(u.user_id, rl._today())] <= cap


def test_concurrent_tenant_cap_never_oversold(monkeypatch):
    """Same property at the per-tenant monthly layer: many users in one tenant
    racing a small tenant cap can't collectively exceed it."""
    cap = 100
    monkeypatch.setitem(
        settings.DEMO_TENANTS, "tenant_x", {"monthly_token_cap": cap}
    )
    amount = 10
    n_threads = 40
    successes: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(i: int):
        # distinct user ids so the per-USER quota never binds — only the
        # per-TENANT cap can reject.
        u = _user(user_id=f"u{i}", tenant_id="tenant_x", quota=10_000)
        barrier.wait()
        try:
            rl.check_quotas(u, amount)
            with lock:
                successes.append(1)
        except HTTPException:
            pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(successes) == cap // amount
    assert rl._tenant_monthly_tokens[("tenant_x", rl._this_month())] <= cap


# ---------------------------------------------------------------------------
# 4. Ordering invariant #8 — quota first, cost breaker second
# ---------------------------------------------------------------------------
def test_quota_reservation_independent_of_cost_breaker():
    """The breaker is a *degrade* signal read AFTER the quota reservation; it
    must not itself block the reservation. Trip the breaker, then confirm a
    quota reservation under cap still succeeds."""
    u = _user(quota=1_000)
    # Drive realised cost over the breaker threshold.
    rl.record_usage(u, 0, 0, cost_usd=settings.COST_CIRCUIT_DAILY_USD + 1.0)
    assert rl.cost_circuit_state()["tripped"] is True
    # Quota reservation still works (ordering: quota BEFORE breaker).
    assert rl.check_quotas(u, 100) == 100


def test_cost_circuit_state_shape_unchanged():
    state = rl.cost_circuit_state()
    assert set(state) == {"tripped", "current_usd", "threshold_usd"}
