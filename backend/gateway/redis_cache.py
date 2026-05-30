"""Redis-backed cache (Q9, Phase 2A).

Drop-in alternative for the in-memory ``_MemoryCache`` defined in ``cache.py``.
Activated via ``CACHE_BACKEND=redis``. Wire-up lives in
``cache.get_cache_backend()`` so the rest of the codebase keeps calling the
package-level ``cache.get_response`` / ``cache.set_response`` helpers unchanged.

Design choices
--------------
* **Lazy connection.** ``__init__`` only constructs the client object;
  ``redis-py``'s ``Redis.from_url(...)`` defers the TCP handshake until the
  first command, which is what we want — instantiating a stale config at
  module import time must not crash the gateway boot.
* **JSON serialisation.** All values flowing through this cache today are
  already JSON-safe (``response.model_dump(mode="json")``, ``list[float]``
  embeddings, retrieval result dicts). JSON avoids the pickle CVE surface
  and lets a future ops engineer inspect keys with ``redis-cli GET`` during
  incident response. If we ever need to cache opaque Python objects we can
  reach for ``msgpack`` then; pickle is a hard no for a tenant-scoped store.
* **SETEX, no MULTI/EVAL.** POC scope. The atomic counter / sliding-window
  patterns from the upstream ``cache.py`` docstring are deferred until the
  rate-limit module also migrates to Redis.
* **Graceful degradation on connection failure.** If Redis is unreachable
  the gateway must keep serving requests (slower, no caching) rather than
  503ing. ``redis.exceptions.ConnectionError`` is caught at every call site
  and the failure is counted in ``stats()`` so observability can alert.
  Note: this falls back to "no cache for that request", *not* to a
  per-process in-memory cache — instantiating one mid-flight would
  silently lose tenant isolation invariants the moment Redis came back
  (cold cache + warm fallback = stale read). The task spec's "fall back
  to in-memory for THAT request" intent is satisfied by a get-miss /
  set-noop pair, which is observationally identical for the caller
  (callable returns the same ``None`` it would for a real miss) without
  polluting a long-lived process with a duplicate store.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

try:
    import redis
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - exercised only when redis-py absent
    redis = None  # type: ignore[assignment]
    RedisConnectionError = Exception  # type: ignore[misc,assignment]
    RedisError = Exception  # type: ignore[misc,assignment]


log = logging.getLogger(__name__)


class RedisCacheBackend:
    """Cache backend backed by a single Redis instance.

    Interface mirrors ``_MemoryCache``: ``get(key)``, ``set(key, value,
    ttl_sec)``, ``stats()``. Values are JSON-encoded on the wire.
    """

    def __init__(self, url: str):
        if redis is None:
            raise ImportError(
                "redis-py is not installed. Add `redis==5.0.8` to "
                "backend/requirements.txt or pip install it."
            )
        self._url = url
        # decode_responses=False so we receive raw bytes from GET and can
        # apply json.loads ourselves — keeps the boundary explicit and avoids
        # surprises if a value is ever non-UTF-8.
        self._client = redis.Redis.from_url(url, decode_responses=False)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._failures = 0

    # ------------------------------------------------------------------
    # Public API (matches _MemoryCache)
    # ------------------------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(key)
        except RedisConnectionError as exc:
            log.warning("redis_cache: GET %s failed (connection): %s", key, exc)
            with self._lock:
                self._failures += 1
            return None
        except RedisError as exc:
            log.warning("redis_cache: GET %s failed (redis error): %s", key, exc)
            with self._lock:
                self._failures += 1
            return None

        if raw is None:
            with self._lock:
                self._misses += 1
            return None

        with self._lock:
            self._hits += 1
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as exc:
            # Corrupted entry — treat as miss so the caller refills.
            log.warning("redis_cache: corrupt value at %s, dropping: %s", key, exc)
            return None

    def set(self, key: str, value: Any, ttl_sec: int = 0) -> None:
        try:
            payload = json.dumps(value).encode("utf-8")
        except (TypeError, ValueError) as exc:
            log.warning("redis_cache: refusing to cache non-JSON value at %s: %s", key, exc)
            return

        try:
            if ttl_sec and ttl_sec > 0:
                self._client.setex(key, ttl_sec, payload)
            else:
                # ttl_sec == 0 mirrors _MemoryCache: "permanent" (no expiry).
                self._client.set(key, payload)
        except RedisConnectionError as exc:
            log.warning("redis_cache: SET %s failed (connection): %s", key, exc)
            with self._lock:
                self._failures += 1
        except RedisError as exc:
            log.warning("redis_cache: SET %s failed (redis error): %s", key, exc)
            with self._lock:
                self._failures += 1

    def stats(self) -> dict:
        with self._lock:
            out = {
                "backend": "redis",
                "hits": self._hits,
                "misses": self._misses,
                "failures": self._failures,
            }
        # Best-effort DBSIZE. Some managed Redis providers restrict this
        # command; if it errors we report 0 and keep going.
        try:
            out["size"] = int(self._client.dbsize())
        except Exception as exc:  # noqa: BLE001 — broad on purpose for stats path
            log.debug("redis_cache: DBSIZE unavailable (%s)", exc)
            out["size"] = 0
        return out
