"""H-5: in-memory session-token revocation store.

The Redis backend (REVOCATION_BACKEND=redis) is exercised only when a Redis
server is reachable; here we test the default in-memory store's contract:
revoke → is_revoked, TTL expiry (with lazy prune), and clear.
"""
from __future__ import annotations

import time

from backend.gateway.revocation import InMemoryRevocationStore


def test_revoke_then_is_revoked():
    s = InMemoryRevocationStore()
    assert s.is_revoked("j1") is False
    s.revoke("j1", 60)
    assert s.is_revoked("j1") is True
    # An unrelated jti is unaffected.
    assert s.is_revoked("other") is False


def test_expired_entry_is_not_revoked_and_is_pruned():
    s = InMemoryRevocationStore()
    s.revoke("j1", 60)
    # Force the entry's expiry into the past without sleeping.
    s._d["j1"] = time.time() - 1
    assert s.is_revoked("j1") is False
    assert "j1" not in s._d  # lazily pruned on the failed lookup


def test_clear_drops_all_entries():
    s = InMemoryRevocationStore()
    s.revoke("j1", 60)
    s.revoke("j2", 60)
    s.clear()
    assert s.is_revoked("j1") is False
    assert s.is_revoked("j2") is False
