"""H-5: session-token revocation store (logout / leaked-token kill switch).

`verify_token` rejects any jti found here; `revoke_token` (logout) adds the
jti with a TTL equal to the token's remaining lifetime, so entries expire on
their own and the store never grows unbounded.

Backends (env ``REVOCATION_BACKEND``):
  - ``memory`` (default): per-process dict. Correct for a single-replica POC,
    but lost on restart and not shared across replicas.
  - ``redis``: durable + fleet-wide; each jti is a key with native EX expiry.

The selection mirrors the cache backend pattern (``backend/gateway/cache.py``).
"""
from __future__ import annotations

import time

from backend.shared.config import settings

_PREFIX = "revoked_jti:"


class InMemoryRevocationStore:
    def __init__(self) -> None:
        self._d: dict[str, float] = {}

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        self._d[jti] = time.time() + max(1, int(ttl_seconds))

    def is_revoked(self, jti: str) -> bool:
        exp = self._d.get(jti)
        if exp is None:
            return False
        if exp < time.time():
            # Lazy prune: an expired revocation is indistinguishable from a
            # naturally-expired token (which verify_token already rejects).
            self._d.pop(jti, None)
            return False
        return True

    def clear(self) -> None:
        self._d.clear()


class RedisRevocationStore:
    def __init__(self, url: str) -> None:
        import redis  # lazy import — only when REVOCATION_BACKEND=redis

        # Short timeouts so a Redis outage degrades fast rather than hanging the
        # auth path. Connection is lazy (first command).
        self._r = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        self._r.setex(_PREFIX + jti, max(1, int(ttl_seconds)), "1")

    def is_revoked(self, jti: str) -> bool:
        return bool(self._r.exists(_PREFIX + jti))

    def clear(self) -> None:
        # Test-only convenience; never called on the hot path.
        for key in self._r.scan_iter(_PREFIX + "*"):
            self._r.delete(key)


def _build_store():
    if settings.REVOCATION_BACKEND == "redis":
        return RedisRevocationStore(settings.REDIS_URL)
    return InMemoryRevocationStore()


_store = _build_store()


def revoke(jti: str, ttl_seconds: int) -> None:
    _store.revoke(jti, ttl_seconds)


def is_revoked(jti: str) -> bool:
    return _store.is_revoked(jti)


def clear() -> None:
    """Reset the store (used by the test harness between tests)."""
    _store.clear()
