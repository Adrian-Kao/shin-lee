"""RedisCacheBackend per-tenant FIFO cap + tenant-kwarg parity tests (Day 13I).

No live Redis required — the client is mocked and the Lua `_SET_WITH_CAP_LUA`
logic is re-implemented in a tiny fake so we can prove:

  * `set(..., tenant=...)` routes through the atomic EVAL (cap path), not the
    plain SETEX/SET path — closing the parity gap where the redis backend had
    NO per-tenant cap while the in-memory backend did (M-8).
  * the fake EVAL evicts the oldest key once a tenant exceeds the cap (FIFO),
    matching the in-memory backend's behaviour.
  * `set(..., tenant=None)` (embeddings) stays on the uncapped plain path.
"""

from __future__ import annotations

from unittest import mock

import pytest

from backend.gateway.redis_cache import RedisCacheBackend
from backend.shared.config import settings


class _FakeRedisStore:
    """A fake redis whose `eval` faithfully runs the SET-with-cap semantics
    (SETEX/SET + per-tenant FIFO order list + eviction)."""

    def __init__(self):
        self.kv: dict[str, bytes] = {}
        self.lists: dict[str, list[str]] = {}

    def eval(self, script, numkeys, *args):
        value_key, order_key, payload, ttl, cap = args
        ttl = int(ttl)
        cap = int(cap)
        self.kv[value_key] = payload
        order = self.lists.setdefault(order_key, [])
        # LREM then LPUSH (newest at front).
        if value_key in order:
            order.remove(value_key)
        order.insert(0, value_key)
        # Evict oldest (tail) while over cap.
        while len(order) > cap:
            victim = order.pop()  # RPOP
            self.kv.pop(victim, None)
        return 1

    def setex(self, key, ttl, payload):
        self.kv[key] = payload

    def set(self, key, payload):
        self.kv[key] = payload


@pytest.fixture()
def backend(monkeypatch):
    with mock.patch("backend.gateway.redis_cache.redis") as redis_mod:
        fake = _FakeRedisStore()
        redis_mod.Redis.from_url.return_value = fake
        be = RedisCacheBackend("redis://localhost:6379/0")
        yield be, fake


def test_tenant_set_uses_eval_cap_path(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 100)
    be.set("resp:k1", {"v": 1}, ttl_sec=60, tenant="tenant_a")
    # Routed through eval → value stored + order list created.
    assert "resp:k1" in fake.kv
    assert fake.lists["cacheorder:tenant_a"] == ["resp:k1"]


def test_tenant_cap_evicts_oldest_fifo(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 3)
    for i in range(5):
        be.set(f"resp:k{i}", {"i": i}, ttl_sec=60, tenant="tenant_a")
    order = fake.lists["cacheorder:tenant_a"]
    # Only the newest 3 keys survive; oldest 2 evicted from kv too.
    assert len(order) == 3
    assert set(order) == {"resp:k2", "resp:k3", "resp:k4"}
    assert "resp:k0" not in fake.kv
    assert "resp:k1" not in fake.kv


def test_no_tenant_uses_plain_path(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 3)
    be.set("emb:abc", [0.1, 0.2], ttl_sec=0, tenant=None)
    # Plain SET path — value present, NO order list created.
    assert "emb:abc" in fake.kv
    assert "cacheorder:" not in "".join(fake.lists.keys())


def test_per_tenant_caps_isolated(backend, monkeypatch):
    """tenant_a flooding past cap must not evict tenant_b's keys (separate
    order lists)."""
    be, fake = backend
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 2)
    be.set("resp:b1", {"v": "b"}, ttl_sec=60, tenant="tenant_b")
    for i in range(5):
        be.set(f"resp:a{i}", {"i": i}, ttl_sec=60, tenant="tenant_a")
    # tenant_b's single key survives tenant_a's flood.
    assert "resp:b1" in fake.kv
    assert fake.lists["cacheorder:tenant_b"] == ["resp:b1"]
    assert len(fake.lists["cacheorder:tenant_a"]) == 2
