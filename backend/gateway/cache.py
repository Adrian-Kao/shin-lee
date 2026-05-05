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
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from backend.shared.config import settings


@dataclass
class _Entry:
    value: Any
    expires_at: float  # 0 means permanent


class _MemoryCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, _Entry] = {}

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            e = self._data.get(key)
            if e is None:
                return None
            if e.expires_at and time.time() > e.expires_at:
                del self._data[key]
                return None
            return e.value

    def set(self, key: str, value: Any, ttl_sec: int = 0):
        with self._lock:
            expires_at = time.time() + ttl_sec if ttl_sec > 0 else 0
            self._data[key] = _Entry(value=value, expires_at=expires_at)

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._data)}


_cache = _MemoryCache()


def _hash_key(parts: list[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# --- Public API ---

def response_cache_key(tenant_id: str, user_id: str, case_id: str, prompt_hash: str) -> str:
    return "resp:" + _hash_key([tenant_id, user_id, case_id, prompt_hash])


def get_response(tenant_id: str, user_id: str, case_id: str, prompt_hash: str) -> Optional[Any]:
    return _cache.get(response_cache_key(tenant_id, user_id, case_id, prompt_hash))


def set_response(tenant_id: str, user_id: str, case_id: str, prompt_hash: str, value: Any):
    _cache.set(
        response_cache_key(tenant_id, user_id, case_id, prompt_hash),
        value,
        ttl_sec=settings.CACHE_TTL_RESPONSE_SEC,
    )


def embedding_cache_key(text_hash: str) -> str:
    return "emb:" + text_hash


def get_embedding(text: str) -> Optional[list[float]]:
    h = hashlib.sha256(text.encode()).hexdigest()
    return _cache.get(embedding_cache_key(h))


def set_embedding(text: str, vec: list[float]):
    h = hashlib.sha256(text.encode()).hexdigest()
    _cache.set(embedding_cache_key(h), vec, ttl_sec=0)  # permanent


def retrieval_cache_key(tenant_id: str, query_hash: str) -> str:
    # tenant scoped — different tenants have different on-prem patent corpora
    return "ret:" + _hash_key([tenant_id, query_hash])


def get_retrieval(tenant_id: str, query: str) -> Optional[Any]:
    qh = hashlib.sha256(query.encode()).hexdigest()
    return _cache.get(retrieval_cache_key(tenant_id, qh))


def set_retrieval(tenant_id: str, query: str, results: Any):
    qh = hashlib.sha256(query.encode()).hexdigest()
    _cache.set(
        retrieval_cache_key(tenant_id, qh),
        results,
        ttl_sec=settings.CACHE_TTL_RETRIEVAL_SEC,
    )


def hash_prompt(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}|{prompt}".encode()).hexdigest()


def stats() -> dict:
    return _cache.stats()
