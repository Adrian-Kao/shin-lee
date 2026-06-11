"""Q12 (Day 13F) — additional revocation-store adversarial unit tests.

Complements test_revocation.py with the TTL-bound + clamp behaviour a leaked-
token kill-switch relies on: a revoke with a non-positive TTL must still be
honoured (clamped to a floor) so a clock-skew or off-by-one can never produce a
revocation that is silently a no-op.
"""

from __future__ import annotations

import time

from backend.gateway.revocation import InMemoryRevocationStore


def test_revoke_clamps_non_positive_ttl_to_floor():
    """A revoke(jti, 0) or revoke(jti, -5) must still register the jti as
    revoked (clamped to >=1s), not silently vanish."""
    s = InMemoryRevocationStore()
    s.revoke("j-zero", 0)
    assert s.is_revoked("j-zero") is True
    s.revoke("j-neg", -10)
    assert s.is_revoked("j-neg") is True


def test_revoke_overwrite_extends_ttl():
    s = InMemoryRevocationStore()
    s.revoke("j", 1)
    s.revoke("j", 3600)  # re-revoke with a longer TTL
    # Push the original short TTL into the past to prove the longer one stuck.
    assert s.is_revoked("j") is True


def test_independent_jtis_have_independent_ttls():
    s = InMemoryRevocationStore()
    s.revoke("short", 60)
    s.revoke("long", 3600)
    # Force `short` to expire without touching `long`.
    s._d["short"] = time.time() - 1
    assert s.is_revoked("short") is False
    assert s.is_revoked("long") is True


def test_clear_is_total():
    s = InMemoryRevocationStore()
    for i in range(50):
        s.revoke(f"j{i}", 3600)
    s.clear()
    assert all(s.is_revoked(f"j{i}") is False for i in range(50))
