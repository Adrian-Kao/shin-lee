"""Unit tests for ``backend.gateway.redis_cache.RedisCacheBackend``.

These tests do NOT require a running Redis server — the underlying client is
mocked via ``unittest.mock``. A future integration test (with the CI Redis
service) can exercise the real wire path; this suite locks in the contract
(JSON serialisation, miss → None, connection failure → graceful, stats
counters).
"""
from __future__ import annotations

from unittest import mock

import pytest

from backend.gateway.redis_cache import RedisCacheBackend


@pytest.fixture()
def patched_backend():
    """Yield a RedisCacheBackend whose underlying redis.Redis is a MagicMock.

    We patch ``redis.Redis.from_url`` so ``__init__`` doesn't try to open a
    real socket; the returned mock client is exposed via ``backend._client``
    so each test can configure ``get`` / ``setex`` / ``set`` / ``dbsize``
    return values or side effects.
    """
    with mock.patch("backend.gateway.redis_cache.redis") as redis_mod:
        # Preserve the real exception classes so ``except`` clauses in the
        # backend match what callers raise. Otherwise patching ``redis``
        # wholesale would also blank out the imported exception aliases the
        # module captured at import time — but the module imported those
        # symbols by name before this patch, so they're already bound and
        # safe. We still keep the real exception classes here in case test
        # code wants to reference them.
        import redis as real_redis

        redis_mod.exceptions.ConnectionError = real_redis.exceptions.ConnectionError
        client = mock.MagicMock()
        redis_mod.Redis.from_url.return_value = client
        backend = RedisCacheBackend("redis://localhost:6379/0")
        # Sanity: lazy-connect contract — we never actually connected.
        redis_mod.Redis.from_url.assert_called_once_with(
            "redis://localhost:6379/0", decode_responses=False
        )
        yield backend


def test_get_miss_returns_none(patched_backend):
    """GET returns None from Redis → backend returns None and bumps misses."""
    patched_backend._client.get.return_value = None

    result = patched_backend.get("resp:abc")

    assert result is None
    stats = patched_backend.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0
    assert stats["failures"] == 0


def test_set_then_get_roundtrip(patched_backend):
    """SET serialises to JSON, GET deserialises back to the same dict."""
    payload = {"foo": "bar", "count": 3, "nested": {"k": [1, 2, 3]}}

    patched_backend.set("resp:abc", payload, ttl_sec=60)

    # Verify SETEX was called with the JSON-encoded value and the right TTL.
    patched_backend._client.setex.assert_called_once()
    args, _ = patched_backend._client.setex.call_args
    assert args[0] == "resp:abc"
    assert args[1] == 60
    raw = args[2]
    assert isinstance(raw, bytes)
    import json as _json

    assert _json.loads(raw) == payload

    # Round-trip: rig the mock client to return what we'd have stored.
    patched_backend._client.get.return_value = raw
    got = patched_backend.get("resp:abc")
    assert got == payload

    stats = patched_backend.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 0


def test_set_with_zero_ttl_uses_plain_set(patched_backend):
    """ttl_sec=0 → permanent → uses ``SET`` (no expiry), not SETEX."""
    patched_backend.set("emb:hash", [0.1, 0.2, 0.3], ttl_sec=0)

    patched_backend._client.set.assert_called_once()
    patched_backend._client.setex.assert_not_called()


def test_connection_failure_returns_none_not_crash(patched_backend):
    """ConnectionError on GET/SET is swallowed; failure counter increments."""
    import redis as real_redis

    patched_backend._client.get.side_effect = real_redis.exceptions.ConnectionError(
        "Redis is down"
    )
    patched_backend._client.setex.side_effect = real_redis.exceptions.ConnectionError(
        "Redis is down"
    )

    # GET path: must return None, not raise.
    assert patched_backend.get("resp:abc") is None

    # SET path: must not raise either.
    patched_backend.set("resp:abc", {"x": 1}, ttl_sec=60)

    stats = patched_backend.stats()
    assert stats["failures"] >= 2
    # Failed GETs should not be counted as misses (they're a third state).
    assert stats["misses"] == 0
    assert stats["hits"] == 0


def test_stats_includes_hits_misses(patched_backend):
    """stats() returns the documented shape after a mix of hits and misses."""
    import json as _json

    # Two hits, one miss.
    patched_backend._client.get.side_effect = [
        _json.dumps({"a": 1}).encode("utf-8"),
        None,
        _json.dumps({"b": 2}).encode("utf-8"),
    ]
    patched_backend._client.dbsize.return_value = 42

    patched_backend.get("k1")
    patched_backend.get("k2")
    patched_backend.get("k3")

    stats = patched_backend.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["failures"] == 0
    assert stats["size"] == 42
    assert stats["backend"] == "redis"


def test_stats_size_degrades_when_dbsize_fails(patched_backend):
    """DBSIZE errors must not break stats() — best-effort size reported as 0."""
    patched_backend._client.dbsize.side_effect = RuntimeError("dbsize forbidden")

    stats = patched_backend.stats()
    assert stats["size"] == 0
    # All counters present even on the degraded path.
    assert "hits" in stats
    assert "misses" in stats
    assert "failures" in stats
