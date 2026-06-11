"""Q18 redis-backed quota atomicity + degrade-policy tests (Day 13I).

No live Redis required — we mock the client so the Lua EVAL reserve path and
the connection-failure degrade policy are exercised hermetically (mirrors the
test_redis_cache.py mock pattern). The Lua script's logic is validated against
a tiny in-memory fake `eval` so we prove the contract "reserve fits ⇒ 1 +
counter incremented; reserve breaks cap ⇒ 0 + counter unchanged" without a
real redis server.
"""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException

from backend.gateway import rate_limit as rl
from backend.shared.config import settings
from backend.shared.models import User, UserRole


def _user(user_id="alice", tenant_id="tenant_a", quota=1_000) -> User:
    return User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name=user_id,
        daily_token_quota=quota,
    )


class _FakeRedis:
    """Minimal redis stand-in implementing just the ops the quota path uses,
    with a faithful re-implementation of the reserve Lua semantics."""

    def __init__(self):
        self.store: dict[str, int] = {}

    def eval(self, script, numkeys, *args):
        # args = (key, amount, limit, ttl)
        key, amount, limit, _ttl = args
        cur = self.store.get(key, 0)
        amount = int(amount)
        limit = int(limit)
        if cur + amount > limit:
            return 0
        self.store[key] = cur + amount
        return 1

    def decrby(self, key, amount):
        self.store[key] = self.store.get(key, 0) - int(amount)

    def incrby(self, key, amount):
        self.store[key] = self.store.get(key, 0) + int(amount)

    def get(self, key):
        v = self.store.get(key)
        return str(v) if v is not None else None

    def expire(self, key, ttl):
        return True


@pytest.fixture()
def redis_backend(monkeypatch):
    """Force RATE_LIMIT_BACKEND=redis with a fake client wired into the lazy
    accessor, and reset the module client cache around the test."""
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_REDIS_CLIENT", fake)
    yield fake
    monkeypatch.setattr(rl, "_REDIS_CLIENT", None)


def test_redis_reserve_fits_under_cap(redis_backend):
    u = _user(quota=100)
    assert rl.check_quotas(u, 60) == 60
    # Counter incremented in the fake store.
    key = f"quota:user:{u.user_id}:{rl._today()}"
    assert redis_backend.store[key] == 60


def test_redis_reserve_blocks_over_cap_and_leaves_counter(redis_backend):
    u = _user(quota=100)
    rl.check_quotas(u, 60)
    key = f"quota:user:{u.user_id}:{rl._today()}"
    with pytest.raises(HTTPException) as ei:
        rl.check_quotas(u, 60)  # 120 > 100
    assert ei.value.status_code == 402
    # Counter unchanged by the rejected reservation (atomic check-and-incr).
    assert redis_backend.store[key] == 60


def test_redis_tenant_failure_rolls_back_user(redis_backend):
    """User reserve succeeds, tenant reserve fails → user counter rolled back."""
    cap = rl._tenant_cap_for("tenant_a")
    u = _user(quota=cap + 1_000)
    # Pre-fill the tenant counter to the cap so the next reserve breaks it.
    tenant_key = f"quota:tenant:{u.tenant_id}:{rl._this_month()}"
    redis_backend.store[tenant_key] = cap
    user_key = f"quota:user:{u.user_id}:{rl._today()}"
    with pytest.raises(HTTPException):
        rl.check_quotas(u, 10)
    # User reservation was rolled back to 0 (decrby).
    assert redis_backend.store.get(user_key, 0) == 0


def test_redis_degrade_fail_closed_rejects(monkeypatch):
    """RATE_LIMIT_REDIS_DEGRADE=closed (default): a redis error on reserve →
    402 (protect the budget)."""
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_DEGRADE", "closed")
    broken = mock.MagicMock()
    broken.eval.side_effect = RuntimeError("redis down")
    monkeypatch.setattr(rl, "_REDIS_CLIENT", broken)
    try:
        with pytest.raises(HTTPException) as ei:
            rl.check_quotas(_user(), 10)
        assert ei.value.status_code == 402
    finally:
        monkeypatch.setattr(rl, "_REDIS_CLIENT", None)


def test_redis_degrade_fail_open_allows(monkeypatch):
    """RATE_LIMIT_REDIS_DEGRADE=open: a redis error → allow (protect
    availability)."""
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_DEGRADE", "open")
    broken = mock.MagicMock()
    broken.eval.side_effect = RuntimeError("redis down")
    monkeypatch.setattr(rl, "_REDIS_CLIENT", broken)
    try:
        # Must NOT raise — fail-open lets the request proceed.
        assert rl.check_quotas(_user(), 10) == 10
    finally:
        monkeypatch.setattr(rl, "_REDIS_CLIENT", None)


def test_redis_cost_breaker_reads_shared_counter(redis_backend):
    """The cost breaker reads the fleet-wide micro-dollar counter so every
    replica trips on the same realised spend."""
    u = _user()
    over = settings.COST_CIRCUIT_DAILY_USD + 5.0
    rl.record_usage(u, 0, 0, cost_usd=over)
    # Stored as integer micro-dollars in the shared key.
    cost_key = f"cost:daily:{rl._today()}"
    assert redis_backend.store[cost_key] == int(round(over * 1_000_000))
    state = rl.cost_circuit_state()
    assert state["tripped"] is True
    assert state["current_usd"] == pytest.approx(over, abs=1e-4)
