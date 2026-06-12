"""P1 hardening — argon2id password KDF (backend/gateway/auth.py).

Covers the upgrade contract:
  * new hashes are argon2id (PHC string) whenever argon2-cffi is importable;
  * legacy ``salt:sha256`` hashes still verify (back-compat);
  * successful legacy verification can be opportunistically re-hashed;
  * when argon2-cffi is ABSENT the module degrades to the legacy scheme
    (the gateway must never fail to boot over an optional dependency);
  * the login timing-equalisation dummy hash matches the active scheme.
"""

from __future__ import annotations

import pytest

from backend.gateway import auth

argon2_available = auth._ARGON2_HASHER is not None

requires_argon2 = pytest.mark.skipif(
    not argon2_available, reason="argon2-cffi not installed in this environment"
)


# ---------------------------------------------------------------------------
# New-hash format + roundtrip
# ---------------------------------------------------------------------------


@requires_argon2
def test_new_hashes_are_argon2id():
    stored = auth._hash_password("s3cret-pw")
    assert stored.startswith("$argon2id$")


@requires_argon2
def test_argon2_roundtrip_accepts_correct_password():
    stored = auth._hash_password("correct horse battery staple")
    assert auth._verify_password("correct horse battery staple", stored) is True


@requires_argon2
def test_argon2_rejects_wrong_password():
    stored = auth._hash_password("right-password")
    assert auth._verify_password("wrong-password", stored) is False


@requires_argon2
def test_argon2_hashes_are_salted_unique():
    # Two hashes of the same password must differ (argon2 random salt).
    assert auth._hash_password("same") != auth._hash_password("same")


def test_verify_handles_malformed_stored_values():
    # Never raises; always a uniform False (no shape oracle).
    for stored in ("", "no-colon-no-prefix", "$argon2id$garbage", ":", "$argon2"):
        assert auth._verify_password("anything", stored) is False


@requires_argon2
def test_demo_user_table_uses_argon2():
    # The import-time demo table regenerates under the active scheme.
    for uid, stored in auth._PASSWORD_HASHES.items():
        assert stored.startswith("$argon2id$"), uid
    # And the published demo password still verifies.
    assert auth._verify_password("demo-alice", auth._PASSWORD_HASHES["alice"]) is True


# ---------------------------------------------------------------------------
# Legacy back-compat
# ---------------------------------------------------------------------------


def test_legacy_sha256_hash_still_verifies():
    legacy = auth._legacy_hash_password("old-password", salt="a" * 32)
    assert ":" in legacy and not legacy.startswith("$argon2")
    assert auth._verify_password("old-password", legacy) is True
    assert auth._verify_password("not-it", legacy) is False


def test_explicit_salt_produces_legacy_format():
    # The salt kwarg exists only for deterministic legacy fixtures.
    stored = auth._hash_password("pw", salt="b" * 32)
    assert stored.startswith("b" * 32 + ":")
    assert auth._verify_password("pw", stored) is True


# ---------------------------------------------------------------------------
# Opportunistic re-hash on successful legacy verification
# ---------------------------------------------------------------------------


@requires_argon2
def test_maybe_upgrade_rehashes_legacy_to_argon2(monkeypatch):
    legacy = auth._legacy_hash_password("demo-alice")
    monkeypatch.setitem(auth._PASSWORD_HASHES, "alice", legacy)

    assert auth._verify_password("demo-alice", auth._PASSWORD_HASHES["alice"]) is True
    assert auth._maybe_upgrade_hash("alice", "demo-alice") is True

    upgraded = auth._PASSWORD_HASHES["alice"]
    assert upgraded.startswith("$argon2id$")
    # The upgraded hash verifies the same password.
    assert auth._verify_password("demo-alice", upgraded) is True


@requires_argon2
def test_maybe_upgrade_noop_for_current_argon2_hash():
    # Demo table is already argon2 at current policy — nothing to upgrade.
    before = auth._PASSWORD_HASHES["bob"]
    assert auth._maybe_upgrade_hash("bob", "demo-bob") is False
    assert auth._PASSWORD_HASHES["bob"] == before


def test_maybe_upgrade_noop_for_unknown_user():
    assert auth._maybe_upgrade_hash("nobody-here", "whatever") is False


# ---------------------------------------------------------------------------
# argon2-absent fallback (POC must boot without the optional dependency)
# ---------------------------------------------------------------------------


def test_fallback_without_argon2_uses_legacy_scheme(monkeypatch, caplog):
    monkeypatch.setattr(auth, "_ARGON2_HASHER", None)

    with caplog.at_level("WARNING", logger="backend.gateway.auth"):
        stored = auth._hash_password("pw-no-argon2")
    assert not stored.startswith("$argon2")
    assert ":" in stored
    assert auth._verify_password("pw-no-argon2", stored) is True
    assert any("argon2" in rec.message for rec in caplog.records)


def test_fallback_without_argon2_refuses_argon2_hashes(monkeypatch):
    # An argon2 hash cannot be verified without the library — uniform False,
    # never a crash.
    if argon2_available:
        stored = auth._hash_password("pw")
    else:
        stored = "$argon2id$v=19$m=65536,t=3,p=4$AAAAAAAAAAAAAAAAAAAAAA$AAAA"
    monkeypatch.setattr(auth, "_ARGON2_HASHER", None)
    assert auth._verify_password("pw", stored) is False


def test_fallback_without_argon2_never_rehashes(monkeypatch):
    monkeypatch.setattr(auth, "_ARGON2_HASHER", None)
    legacy = auth._legacy_hash_password("demo-alice")
    monkeypatch.setitem(auth._PASSWORD_HASHES, "alice", legacy)
    assert auth._maybe_upgrade_hash("alice", "demo-alice") is False
    assert auth._PASSWORD_HASHES["alice"] == legacy


# ---------------------------------------------------------------------------
# Timing-equalisation dummy hash matches the active scheme (H-8)
# ---------------------------------------------------------------------------


def test_dummy_timing_hash_matches_active_scheme():
    if argon2_available:
        assert auth._DUMMY_HASH_FOR_TIMING.startswith("$argon2id$")
    else:
        assert ":" in auth._DUMMY_HASH_FOR_TIMING
    # It must never verify any plausible password.
    assert auth._verify_password("demo-alice", auth._DUMMY_HASH_FOR_TIMING) is False


# ---------------------------------------------------------------------------
# End-to-end: the login endpoint still authenticates demo users
# ---------------------------------------------------------------------------


@requires_argon2
def test_login_endpoint_password_path_with_argon2():
    from fastapi.testclient import TestClient

    from backend.gateway.main import app

    with TestClient(app) as client:
        ok = client.post("/v1/auth/login", json={"user_id": "alice", "password": "demo-alice"})
        assert ok.status_code == 200
        assert ok.json()["user_id"] == "alice"

        bad = client.post("/v1/auth/login", json={"user_id": "alice", "password": "nope"})
        assert bad.status_code == 401

        unknown = client.post("/v1/auth/login", json={"user_id": "mallory", "password": "x"})
        assert unknown.status_code == 401
        # H-8: identical body for unknown user vs wrong password.
        assert unknown.json() == bad.json()


@requires_argon2
def test_login_upgrades_legacy_hash_in_place(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.gateway.main import app

    legacy = auth._legacy_hash_password("demo-alice")
    monkeypatch.setitem(auth._PASSWORD_HASHES, "alice", legacy)

    with TestClient(app) as client:
        ok = client.post("/v1/auth/login", json={"user_id": "alice", "password": "demo-alice"})
        assert ok.status_code == 200

    assert auth._PASSWORD_HASHES["alice"].startswith("$argon2id$")
