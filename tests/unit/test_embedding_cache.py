"""Q9 embedding-cache wiring + H-3 tenant isolation tests.

Q9 decision: embeddings are cached permanently (patents don't change
post-publication). Pre-fix, ``rag.embed`` recomputed the vector on every call
and the gateway ``get_embedding/set_embedding`` helpers — though present — were
never wired in. Worse, the gateway key was ``sha256(text)`` only, with NO
tenant, while ``rag.embed(text, tenant_id)`` is tenant-SALTED in mock mode
(H-3). A naive wiring would have served tenant_a's vector to tenant_b.

These tests are the load-bearing assertions that close Q9 wiring WITHOUT
regressing H-3:

  * the rag-layer cache actually serves a hit on the second embed;
  * mock embeddings stay tenant-distinct AND never cross-tenant-hit;
  * the gateway helpers are now tenant-namespaced (cross-tenant miss).
"""
from __future__ import annotations

import pytest

from backend.ai_engine import rag
from backend.gateway import cache as cache_mod


@pytest.fixture(autouse=True)
def _hermetic_caches(monkeypatch):
    """Each test starts from an empty rag-layer embedding cache (with zeroed
    hit/miss counters) and a fresh gateway _MemoryCache, so state never leaks
    between cases."""
    rag.clear_embedding_cache()
    from backend.gateway.cache import _MemoryCache
    monkeypatch.setattr(cache_mod, "_cache", _MemoryCache())
    yield
    rag.clear_embedding_cache()


# ---------------------------------------------------------------------------
# rag-layer cache
# ---------------------------------------------------------------------------
def test_embed_serves_second_call_from_cache():
    """Embedding the same (tenant, text) twice returns an identical vector and
    the second call is a cache HIT (observed via embedding_cache_stats)."""
    text = "A widget comprising a sprocket and a flange."

    v1 = rag.embed(text, tenant_id="t1")
    after_first = rag.embedding_cache_stats()
    assert after_first["hits"] == 0
    assert after_first["misses"] == 1
    assert after_first["entries"] == 1

    v2 = rag.embed(text, tenant_id="t1")
    after_second = rag.embedding_cache_stats()
    assert v2 == v1
    assert after_second["hits"] == 1, "second embed should be served from cache"
    assert after_second["misses"] == 1, "second embed must not recompute"
    assert after_second["entries"] == 1, "no new entry on a hit"


def test_cache_hit_does_not_recompute(monkeypatch):
    """Belt-and-braces: monkeypatch the underlying compute to blow up, prove
    the 2nd embed is served purely from cache without touching it."""
    text = "claim 1 ... claim 2 ..."

    # Prime the cache (real compute path runs once).
    rag.embed(text, tenant_id="t1")

    # Now sabotage the mock compute path: np.array is only reached on a MISS,
    # so if the 2nd embed recomputes, this explodes.
    def _explode(*a, **k):
        raise AssertionError("recomputed a cached embedding")

    monkeypatch.setattr(rag.np, "array", _explode)

    v = rag.embed(text, tenant_id="t1")  # must be a pure cache hit
    assert isinstance(v, list) and v, "cached vector should be returned intact"
    assert rag.embedding_cache_stats()["hits"] >= 1


def test_h3_tenant_isolation_preserved():
    """Same text, two tenants → DIFFERENT mock vectors, and the cache must NOT
    serve tenant_a's vector to tenant_b (no cross-tenant hit)."""
    text = "An apparatus for cooling a semiconductor die."

    va = rag.embed(text, tenant_id="tenant_a")
    # After tenant_a: 1 miss, 0 hits.
    assert rag.embedding_cache_stats() == {"hits": 0, "misses": 1, "entries": 1}

    vb = rag.embed(text, tenant_id="tenant_b")
    # tenant_b must be a fresh MISS (no cross-tenant hit) and a distinct vector.
    stats = rag.embedding_cache_stats()
    assert stats["hits"] == 0, "tenant_b must not hit tenant_a's cached entry"
    assert stats["misses"] == 2
    assert stats["entries"] == 2, "each tenant gets its own cache entry"
    assert va != vb, "H-3: mock embeddings must differ per tenant"

    # And each tenant re-reading its own entry is a clean hit returning its own
    # vector (never the other tenant's).
    assert rag.embed(text, tenant_id="tenant_a") == va
    assert rag.embed(text, tenant_id="tenant_b") == vb


def test_empty_tenant_is_its_own_namespace():
    """tenant_id='' (standalone chunker context) must still work and not
    collide with a real tenant's entry."""
    text = "independent claim text"
    v_default = rag.embed(text)  # tenant_id="" default
    v_real = rag.embed(text, tenant_id="tenant_a")
    assert v_default != v_real, "'' namespace must be distinct from a real tenant"


# ---------------------------------------------------------------------------
# gateway-layer helpers (now tenant-aware)
# ---------------------------------------------------------------------------
def test_gateway_embedding_cache_is_tenant_namespaced():
    """set_embedding(text, vec, tenant_a) then get for tenant_a HITS; the same
    text for tenant_b MISSES (returns None) — closes the latent H-3 bug."""
    text = "A method of manufacturing a lens."
    vec = [0.1, 0.2, 0.3]

    cache_mod.set_embedding(text, vec, tenant_id="tenant_a")

    assert cache_mod.get_embedding(text, tenant_id="tenant_a") == vec
    assert cache_mod.get_embedding(text, tenant_id="tenant_b") is None, (
        "cross-tenant read must miss — tenant_a's vector must not leak to tenant_b"
    )


def test_gateway_embedding_keys_differ_by_tenant():
    text = "shared text"
    ka = cache_mod.embedding_cache_key(text, "tenant_a")
    kb = cache_mod.embedding_cache_key(text, "tenant_b")
    assert ka != kb
    assert ka.startswith("emb:") and kb.startswith("emb:")
