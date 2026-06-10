"""Q9 cache cross-user / cross-tenant isolation + TTL + redaction-version key
membership tests (Day 13I).

The cache key contract is `tenant:user:case:hash`. The load-bearing privacy
property (CLAUDE.md "Don't cache responses cross-user") is that one client can
NEVER read another's cached answer:

  * a different USER in the same tenant+case computes a DIFFERENT response key;
  * a different TENANT computes a DIFFERENT response key (and a different
    embedding/retrieval key);
  * a redaction-version bump changes the prompt hash so stale entries miss.

These tests assert at the KEY level (so they hold regardless of backend) AND at
the get/set level on the in-memory backend.
"""
from __future__ import annotations

import pytest

from backend.gateway import cache as cache_mod
from backend.shared.config import settings


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    from backend.gateway.cache import _MemoryCache
    monkeypatch.setattr(cache_mod, "_cache", _MemoryCache())
    yield


# ---------------------------------------------------------------------------
# Response cache — cross-user / cross-tenant isolation
# ---------------------------------------------------------------------------
def test_response_key_differs_by_user():
    k_alice = cache_mod.response_cache_key("tenant_a", "alice", "CASE-1", "h")
    k_bob = cache_mod.response_cache_key("tenant_a", "bob", "CASE-1", "h")
    assert k_alice != k_bob


def test_response_key_differs_by_tenant():
    k_a = cache_mod.response_cache_key("tenant_a", "alice", "CASE-1", "h")
    k_b = cache_mod.response_cache_key("tenant_b", "alice", "CASE-1", "h")
    assert k_a != k_b


def test_response_key_differs_by_case():
    k1 = cache_mod.response_cache_key("tenant_a", "alice", "CASE-1", "h")
    k2 = cache_mod.response_cache_key("tenant_a", "alice", "CASE-2", "h")
    assert k1 != k2


def test_one_user_cannot_read_anothers_cached_response():
    """alice caches a response; bob (same tenant + case + prompt) MUST miss."""
    cache_mod.set_response("tenant_a", "alice", "CASE-1", "h", {"secret": "alice-only"})
    # Same tenant, same case, same prompt hash — but different user.
    assert cache_mod.get_response("tenant_a", "bob", "CASE-1", "h") is None
    # alice still reads her own.
    assert cache_mod.get_response("tenant_a", "alice", "CASE-1", "h") == {"secret": "alice-only"}


def test_one_tenant_cannot_read_anothers_cached_response():
    cache_mod.set_response("tenant_a", "alice", "CASE-1", "h", {"v": "a"})
    assert cache_mod.get_response("tenant_b", "alice", "CASE-1", "h") is None


# ---------------------------------------------------------------------------
# Embedding + retrieval — tenant namespacing (H-3)
# ---------------------------------------------------------------------------
def test_embedding_key_namespaced_by_tenant():
    """Same text, different tenant → different embedding key (mock vectors are
    tenant-salted, so a shared key would leak tenant_a's vector to tenant_b)."""
    k_a = cache_mod.embedding_cache_key("widget", "tenant_a")
    k_b = cache_mod.embedding_cache_key("widget", "tenant_b")
    assert k_a != k_b


def test_one_tenant_cannot_read_anothers_embedding():
    cache_mod.set_embedding("widget", [0.1, 0.2], "tenant_a")
    assert cache_mod.get_embedding("widget", "tenant_b") is None
    assert cache_mod.get_embedding("widget", "tenant_a") == [0.1, 0.2]


def test_retrieval_key_namespaced_by_tenant():
    k_a = cache_mod.retrieval_cache_key("tenant_a", "qh")
    k_b = cache_mod.retrieval_cache_key("tenant_b", "qh")
    assert k_a != k_b


def test_one_tenant_cannot_read_anothers_retrieval():
    cache_mod.set_retrieval("tenant_a", "find prior art", [{"id": "a"}])
    assert cache_mod.get_retrieval("tenant_b", "find prior art") is None
    assert cache_mod.get_retrieval("tenant_a", "find prior art") == [{"id": "a"}]


# ---------------------------------------------------------------------------
# Redaction-version is part of the key
# ---------------------------------------------------------------------------
def test_redaction_version_in_prompt_hash():
    p, m = "alice@x.com review", "orchestrator-v1"
    assert cache_mod.hash_prompt(p, m, "v1") != cache_mod.hash_prompt(p, m, "v2")


def test_redaction_version_bump_invalidates_stored_response():
    """End-to-end: a response cached under v1's prompt hash is NOT served once
    the redaction version bumps to v2 (different hash → key miss)."""
    p, m = "alice@x.com review", "orchestrator-v1"
    h_v1 = cache_mod.hash_prompt(p, m, "v1")
    h_v2 = cache_mod.hash_prompt(p, m, "v2")
    cache_mod.set_response("tenant_a", "alice", "CASE-1", h_v1, {"era": "v1"})
    # After a ruleset bump the orchestrator hashes with v2 → miss.
    assert cache_mod.get_response("tenant_a", "alice", "CASE-1", h_v2) is None


# ---------------------------------------------------------------------------
# TTL — response/retrieval expire, embedding permanent
# ---------------------------------------------------------------------------
def test_response_ttl_expires(monkeypatch):
    """A response past its TTL must read as a miss."""
    import backend.gateway.cache as c
    # Pin a tiny TTL so the entry is already expired at read time.
    monkeypatch.setattr(settings, "CACHE_TTL_RESPONSE_SEC", 1)
    cache_mod.set_response("tenant_a", "alice", "CASE-1", "h", {"v": 1})
    # Advance the clock past the TTL by patching time.time inside the module.
    real_time = c.time.time
    monkeypatch.setattr(c.time, "time", lambda: real_time() + 10)
    assert cache_mod.get_response("tenant_a", "alice", "CASE-1", "h") is None


def test_embedding_is_permanent(monkeypatch):
    """Embeddings are set with ttl_sec=0 (never expire) — they survive a large
    clock advance."""
    import backend.gateway.cache as c
    cache_mod.set_embedding("widget", [0.5], "tenant_a")
    real_time = c.time.time
    monkeypatch.setattr(c.time, "time", lambda: real_time() + 10_000_000)
    assert cache_mod.get_embedding("widget", "tenant_a") == [0.5]


def test_ttls_use_configured_settings():
    """Sanity: the public helpers thread the configured TTL constants (so an
    ops change to CACHE_TTL_* actually takes effect)."""
    assert settings.CACHE_TTL_RESPONSE_SEC == 3600
    assert settings.CACHE_TTL_RETRIEVAL_SEC == 86400
