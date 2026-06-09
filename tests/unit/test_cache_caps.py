"""Per-tenant cache cap + redaction-version invalidation tests (M-7 + M-8).

Pre-fix the in-memory cache was an unbounded dict per tenant. One noisy
tenant could fill RAM with a million response entries; the cap was
nominally enforced by Redis's allkeys-lru but no equivalent existed for
the in-memory backend (which is what the smoke tests + pytest use).

Post-fix:
  * ``_MemoryCache`` tracks insertion order per tenant in an OrderedDict.
  * When ``MAX_CACHE_ENTRIES_PER_TENANT`` is hit, the oldest entry is
    evicted (FIFO). Eviction is per-tenant — tenant_b's quiet keys are
    NOT touched when tenant_a goes over cap.
  * ``hash_prompt`` now folds ``REDACTION_VERSION`` into the hash so a
    redaction ruleset change invalidates pre-change cached responses.

These tests are the load-bearing assertions that close M-7 + M-8.
"""
from __future__ import annotations

import pytest

from backend.gateway import cache as cache_mod
from backend.shared.config import settings


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    """Each test starts with a fresh _MemoryCache so insertion-order
    state doesn't leak between cases. We swap in a new backend rather
    than clearing the module-level one because the autouse
    `_reset_module_state` fixture in conftest only clears `_data` — it
    doesn't reset the per-tenant order index added by M-8."""
    from backend.gateway.cache import _MemoryCache
    fresh = _MemoryCache()
    monkeypatch.setattr(cache_mod, "_cache", fresh)
    yield


def test_cache_evicts_oldest_when_tenant_hits_cap(monkeypatch):
    """Write CAP+5 entries for tenant_a, expect the oldest 5 evicted and
    the newest CAP keys still present.

    Asserts both the size invariant (per-tenant count == cap) and the
    FIFO eviction order (entries 0..4 gone, entries 5..(CAP+4) present).
    """
    # Use a small cap to keep the test fast. Pinning via monkeypatch
    # avoids depending on the env default of 1000.
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 10)
    cap = settings.MAX_CACHE_ENTRIES_PER_TENANT

    for i in range(cap + 5):
        cache_mod.set_response(
            tenant_id="tenant_a",
            user_id="alice",
            case_id=f"CASE-{i}",
            prompt_hash=f"h{i}",
            value={"i": i},
        )

    s = cache_mod.stats()
    assert s["per_tenant"]["tenant_a"] == cap, s
    # The first 5 entries are gone.
    for i in range(5):
        got = cache_mod.get_response("tenant_a", "alice", f"CASE-{i}", f"h{i}")
        assert got is None, f"entry {i} should have been evicted"
    # The newest CAP entries are still present.
    for i in range(5, cap + 5):
        got = cache_mod.get_response("tenant_a", "alice", f"CASE-{i}", f"h{i}")
        assert got == {"i": i}, f"entry {i} should still be cached"


def test_per_tenant_caps_are_isolated(monkeypatch):
    """tenant_a fills to cap; tenant_b writes one entry. tenant_b's
    entry must survive — tenant_a's cap MUST NOT evict tenant_b's
    keys.

    This is the load-bearing assertion that one tenant can't starve
    another via the in-memory cache. Pre-fix a single shared dict
    grew unbounded; the dict size cap would have to be cross-tenant,
    which is precisely the starvation problem M-8 fixes.
    """
    monkeypatch.setattr(settings, "MAX_CACHE_ENTRIES_PER_TENANT", 5)
    cap = settings.MAX_CACHE_ENTRIES_PER_TENANT

    # tenant_b writes ONE entry first (so it's the oldest globally).
    cache_mod.set_response(
        tenant_id="tenant_b",
        user_id="carol",
        case_id="CASE-B-1",
        prompt_hash="hb1",
        value={"src": "tenant_b"},
    )

    # tenant_a floods past cap.
    for i in range(cap + 3):
        cache_mod.set_response(
            tenant_id="tenant_a",
            user_id="alice",
            case_id=f"CASE-A-{i}",
            prompt_hash=f"ha{i}",
            value={"i": i},
        )

    # tenant_b's entry MUST still be there.
    got_b = cache_mod.get_response("tenant_b", "carol", "CASE-B-1", "hb1")
    assert got_b == {"src": "tenant_b"}, "tenant_b's entry was evicted by tenant_a's flood"

    # tenant_a's count is at cap exactly.
    s = cache_mod.stats()
    assert s["per_tenant"]["tenant_a"] == cap
    assert s["per_tenant"]["tenant_b"] == 1


def test_redaction_version_bump_invalidates_cache():
    """Same prompt + model, two different redaction_version values must
    produce different cache keys.

    The contract is that a redaction ruleset bump invalidates pre-bump
    cached responses — pre-fix, the key was `hash(model|prompt)` so a
    tenant adding a new dictionary rule would silently serve responses
    that pre-dated the rule (i.e. responses that contain unredacted
    forms of the now-redacted term).
    """
    prompt = "alice@apex-ip.com please review the case"
    model = "orchestrator-v1"

    key_v1 = cache_mod.hash_prompt(prompt, model, redaction_version="v1")
    key_v2 = cache_mod.hash_prompt(prompt, model, redaction_version="v2")

    assert key_v1 != key_v2, (
        "redaction_version not folded into hash — a ruleset bump would "
        "silently keep serving stale cached responses against the new rules."
    )
    # And the legacy 2-arg form defaults to v1 (backwards compat for any
    # caller that hasn't been updated yet).
    key_legacy = cache_mod.hash_prompt(prompt, model)
    assert key_legacy == key_v1, (
        "legacy 2-arg hash_prompt(prompt, model) must default to "
        "redaction_version='v1' so existing callers stay stable."
    )
