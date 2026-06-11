"""Cache layer (Q9).

Key invariants:
    - LLM response cache MUST namespace by tenant + user + case to avoid leaking
      one client's answer to another.
    - Embeddings can be cached permanently (patents don't change post-publication).
    - Retrieval results cache 24h (new prior art publishes daily).

POC: in-memory dict with TTL.  Production: Redis with EVAL atomic ops.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from backend.shared.config import settings

logger = logging.getLogger(__name__)


# Key prefixes whose tenant_id can be extracted from the key for the per-tenant
# size cap (M-8). The format is set by the helpers below — keep in sync.
#   resp:<hash24>   — built from [tenant, user, case, prompt_hash]
#   ret:<hash24>    — built from [tenant, query_hash]
# Embedding keys (emb:<sha256(tenant|text)>) ARE tenant-namespaced in the KEY
# (H-3: rag.embed salts mock vectors per tenant, so a non-namespaced key would
# leak tenant_a's vector to tenant_b). They still live in the shared, uncapped
# SIZE bucket — they're permanent and deterministic, so no tenant should be
# charged for them and they never need eviction. Namespacing the key while
# keeping the shared bucket gives both: cross-tenant reads miss, but the
# accounting stays simple.
_TENANT_SCOPED_PREFIXES = ("resp:", "ret:")
_SHARED_BUCKET = "__shared__"


@dataclass
class _Entry:
    value: Any
    expires_at: float  # 0 means permanent
    # M-8: which tenant (or _SHARED_BUCKET) this entry counts toward. Stored
    # on the entry so eviction doesn't have to re-derive it from the key.
    tenant: str = _SHARED_BUCKET


class _MemoryCache:
    """In-memory cache with per-tenant size cap (M-8 fix).

    Pre-fix: a single ``dict[str, _Entry]`` grew unbounded per tenant. One
    noisy tenant could fill RAM with a million response entries, evicting
    nobody else's keys but also OOM-killing the worker.

    Post-fix: each tenant has its own LRU ``OrderedDict`` of keys-in-order
    capped at ``settings.MAX_CACHE_ENTRIES_PER_TENANT`` (default 1000).
    The shared bucket (embeddings) is uncapped because it's a permanent
    deterministic mapping that the whole system benefits from caching.

    Key invariants vs the original contract:

    * ``get(key)`` / ``set(key, value, ttl)`` signatures unchanged.
    * ``stats()`` still returns ``{"size": <total>}`` for backwards
      compatibility (the existing health endpoint reads ``size``); a
      ``per_tenant`` breakdown is added alongside.
    * Eviction is FIFO insertion order via ``OrderedDict.popitem(last=False)``,
      not true LRU. POC trade-off — keeps the implementation a few lines
      and matches Redis's allkeys-lru behaviour close enough that the
      operator's mental model is consistent across backends.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Main key→entry mapping (preserves the existing ``_data`` interface
        # that tests / health checks read).
        self._data: dict[str, _Entry] = {}
        # Per-tenant insertion-ordered key set. ``OrderedDict[str, None]``
        # gives O(1) FIFO eviction without storing duplicate values.
        self._per_tenant_order: dict[str, OrderedDict[str, None]] = {}

    def _bucket_for(self, key: str) -> str:
        """Derive which tenant bucket ``key`` belongs to.

        Response and retrieval keys are prefixed and the tenant is the first
        component of the hash input. We can't recover the tenant from the
        hashed key itself, so callers that need per-tenant accounting must
        pass the tenant explicitly via ``set``. This helper handles the
        fallback for keys set without an explicit tenant (embeddings).
        """
        for prefix in _TENANT_SCOPED_PREFIXES:
            if key.startswith(prefix):
                # Caller didn't pass a tenant hint AND it's a tenant-scoped
                # prefix — we have to lump it into shared, which means the
                # cap doesn't apply. The set_response / set_retrieval
                # helpers below always pass an explicit tenant, so this
                # branch only fires for hand-rolled callers that bypassed
                # them (none exist today).
                return _SHARED_BUCKET
        return _SHARED_BUCKET

    def get(self, key: str) -> Any | None:
        with self._lock:
            e = self._data.get(key)
            if e is None:
                return None
            if e.expires_at and time.time() > e.expires_at:
                self._delete_locked(key)
                return None
            return e.value

    def set(self, key: str, value: Any, ttl_sec: int = 0, tenant: str | None = None):
        """Insert (or overwrite) a cache entry.

        ``tenant`` is optional for backwards compatibility — when omitted
        the entry lands in the shared (uncapped) bucket. The public helpers
        ``set_response`` / ``set_retrieval`` pass it explicitly so the
        per-tenant cap fires correctly.
        """
        with self._lock:
            expires_at = time.time() + ttl_sec if ttl_sec > 0 else 0
            bucket = tenant or self._bucket_for(key)
            # If the key already exists in a different bucket, remove it
            # from the old bucket's order first so we don't double-count.
            existing = self._data.get(key)
            if existing is not None and existing.tenant != bucket:
                old_order = self._per_tenant_order.get(existing.tenant)
                if old_order is not None:
                    old_order.pop(key, None)
            self._data[key] = _Entry(value=value, expires_at=expires_at, tenant=bucket)
            order = self._per_tenant_order.setdefault(bucket, OrderedDict())
            # Move to end if existed; insert at end otherwise. Pure FIFO would
            # use straight insert; we use move_to_end on overwrite so a hot
            # key being re-set doesn't get prematurely evicted.
            if key in order:
                order.move_to_end(key)
            else:
                order[key] = None
            # M-8: enforce cap. Shared bucket is uncapped (embeddings live
            # forever by design — set_embedding passes ttl_sec=0).
            cap = settings.MAX_CACHE_ENTRIES_PER_TENANT
            if bucket != _SHARED_BUCKET and cap > 0:
                while len(order) > cap:
                    oldest_key, _ = order.popitem(last=False)
                    # popitem on the OrderedDict only removes from the order
                    # index; remove from _data too. Use pop with default
                    # because the entry COULD have been deleted concurrently
                    # via TTL expiry between the two lookups (we hold the
                    # lock so this is paranoid but cheap).
                    evicted = self._data.pop(oldest_key, None)
                    if evicted is not None:
                        logger.debug(
                            "cache: evicted oldest entry for tenant=%s (cap=%d) key=%s",
                            bucket,
                            cap,
                            oldest_key,
                        )

    def _delete_locked(self, key: str) -> None:
        """Remove a key from both _data and its tenant's order index.

        Caller must hold ``self._lock``. Used by the TTL-expiry path in
        ``get`` so the order index doesn't accumulate stale entries.
        """
        entry = self._data.pop(key, None)
        if entry is None:
            return
        order = self._per_tenant_order.get(entry.tenant)
        if order is not None:
            order.pop(key, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                # M-8: per-tenant counts so the operator can see who's
                # close to the cap. Shared bucket is reported under its
                # synthetic key so the dashboard can render it labelled
                # "shared (embeddings)".
                "per_tenant": {
                    tenant: len(order) for tenant, order in self._per_tenant_order.items()
                },
                "max_per_tenant": settings.MAX_CACHE_ENTRIES_PER_TENANT,
            }


def get_cache_backend():
    """Return the cache backend chosen by CACHE_BACKEND env var.

    Phase 2A: ``redis`` selects ``RedisCacheBackend`` (lazy-connect, JSON
    serialised, gracefully degrades on connection failure). Default
    ``memory`` keeps the in-process ``_MemoryCache`` used by tests and
    the POC happy path.
    """
    if settings.CACHE_BACKEND == "redis":
        # Local import so ``redis-py`` is only a runtime dep when actually
        # selected — keeps the in-memory path importable even if the
        # ``redis`` package is missing (e.g. minimal POC deploys).
        from backend.gateway.redis_cache import RedisCacheBackend

        return RedisCacheBackend(settings.REDIS_URL)
    return _MemoryCache()


_cache = get_cache_backend()


def _hash_key(parts: list[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# --- Public API ---


def response_cache_key(tenant_id: str, user_id: str, case_id: str, prompt_hash: str) -> str:
    return "resp:" + _hash_key([tenant_id, user_id, case_id, prompt_hash])


def get_response(tenant_id: str, user_id: str, case_id: str, prompt_hash: str) -> Any | None:
    return _cache.get(response_cache_key(tenant_id, user_id, case_id, prompt_hash))


def set_response(tenant_id: str, user_id: str, case_id: str, prompt_hash: str, value: Any):
    # M-8: pass tenant explicitly so the per-tenant cap counts this entry.
    # The cache backend signature is permissive — RedisCacheBackend ignores
    # the kwarg via **kwargs / lack thereof. We guard with a hasattr check
    # so the redis path doesn't break when this kwarg is added.
    _safe_set(
        response_cache_key(tenant_id, user_id, case_id, prompt_hash),
        value,
        ttl_sec=settings.CACHE_TTL_RESPONSE_SEC,
        tenant=tenant_id,
    )


def embedding_cache_key(text: str, tenant_id: str = "") -> str:
    # H-3: the mock embedding backend (rag.embed) salts vectors with tenant_id,
    # so the cache KEY must namespace by tenant — otherwise tenant_a's vector
    # would be served to tenant_b for the same text, silently undoing the
    # tenant isolation that test_cross_tenant.py protects. We fold tenant_id
    # INTO the hashed payload (not just a prefix) so it can't collide with a
    # text that happens to contain the delimiter. bge-m3 is content-only and
    # would be safe to share, but we always namespace for simplicity+safety.
    h = hashlib.sha256(f"{tenant_id}|{text}".encode()).hexdigest()
    return "emb:" + h


def get_embedding(text: str, tenant_id: str = "") -> list[float] | None:
    return _cache.get(embedding_cache_key(text, tenant_id))


def set_embedding(text: str, vec: list[float], tenant_id: str = ""):
    # Embedding entries live in the shared (uncapped) size bucket — they are
    # permanent and deterministic — but the KEY is tenant-namespaced (H-3).
    # The shared-bucket accounting (no tenant= kwarg) is therefore preserved
    # while cross-tenant reads still MISS.
    _safe_set(embedding_cache_key(text, tenant_id), vec, ttl_sec=0)  # permanent


def retrieval_cache_key(tenant_id: str, query_hash: str) -> str:
    # tenant scoped — different tenants have different on-prem patent corpora
    return "ret:" + _hash_key([tenant_id, query_hash])


def get_retrieval(tenant_id: str, query: str) -> Any | None:
    qh = hashlib.sha256(query.encode()).hexdigest()
    return _cache.get(retrieval_cache_key(tenant_id, qh))


def set_retrieval(tenant_id: str, query: str, results: Any):
    qh = hashlib.sha256(query.encode()).hexdigest()
    _safe_set(
        retrieval_cache_key(tenant_id, qh),
        results,
        ttl_sec=settings.CACHE_TTL_RETRIEVAL_SEC,
        tenant=tenant_id,
    )


def _safe_set(key: str, value: Any, ttl_sec: int = 0, tenant: str | None = None) -> None:
    """Backend-agnostic set helper.

    The in-memory backend gained a ``tenant`` kwarg for the M-8 per-tenant
    cap; the Redis backend's ``set`` signature predates that. Until both
    backends share a common ABC we sniff the signature and only forward
    the kwarg when supported, so the Redis path keeps working unchanged.
    """
    try:
        _cache.set(key, value, ttl_sec=ttl_sec, tenant=tenant)
    except TypeError:
        # Backend doesn't accept tenant= — fall through to the legacy call.
        _cache.set(key, value, ttl_sec=ttl_sec)


def hash_prompt(prompt: str, model: str, redaction_version: str = "v1") -> str:
    """Hash a prompt for cache-key derivation.

    M-7 fix: ``redaction_version`` is now part of the hash payload. A
    future bump to the redaction ruleset (new PII rule, tenant dictionary
    change) MUST come with a corresponding ``REDACTION_VERSION`` bump so
    existing cached responses — computed against the old ruleset — are
    invalidated rather than served stale.

    Caller contract: ``prompt`` MUST be the post-redaction text, not the
    raw user input. Pre-fix the orchestrator hashed raw text; a typo in
    the OA caused a miss, but two attorneys typing the same OA hit each
    other's responses (the surrounding tenant/user namespacing prevented
    cross-user leak via response_cache_key, but only because of that
    layer — the hash itself never namespaced).

    The signature defaults ``redaction_version="v1"`` for backwards
    compatibility with any caller still passing two args. The orchestrator
    passes ``settings.REDACTION_VERSION`` explicitly.
    """
    return hashlib.sha256(f"{model}|{redaction_version}|{prompt}".encode()).hexdigest()


def stats() -> dict:
    return _cache.stats()
