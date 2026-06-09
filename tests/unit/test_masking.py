"""Unit tests for the data-masking / redaction layer (Q10) and its at-rest
encryption of the reversible un-redaction table (Q3/Q10 crown jewel).

Covers:
  - the original PII / tenant-dictionary rules still fire and never echo the
    raw token (email, phone_tw, apex_case_no, apex_client_code).
  - redact -> unmask round-trips to the exact original (behaviour preserved).
  - the on-disk `original` column is ciphertext, not plaintext.
  - per-tenant key isolation: tenant_a ciphertext is undecryptable as tenant_b.
  - graceful degradation when a stored value cannot be decrypted.
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from backend.gateway import masking
from backend.gateway.masking import MaskingStore, redact


# --- helpers ---------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")

EMAIL = "john.doe@example.com"
PHONE = "0912-345-678"
CASE = "APEX-2024-00123"
CLIENT = "CL-ABCD12"
SAMPLE = (
    f"Please contact {EMAIL} or call {PHONE}. "
    f"Re case {CASE} for client {CLIENT}."
)


@pytest.fixture()
def store(tmp_path):
    """A MaskingStore backed by an isolated on-disk SQLite file."""
    return MaskingStore(path=tmp_path / "redaction_mapping.db")


@pytest.fixture(autouse=True)
def isolated_module_store(tmp_path, monkeypatch):
    """Point the module-level ``_store`` at a fresh per-test DB so the public
    ``redact`` / ``unmask`` helpers never share global on-disk state (which would
    otherwise leak between tests and across runs via INSERT OR IGNORE)."""
    fresh = MaskingStore(path=tmp_path / "module_mapping.db")
    monkeypatch.setattr(masking, "_store", fresh)
    return fresh


# --- original rule coverage (preserved from the pre-encryption suite) -------

def test_email_is_redacted():
    text = "Please contact alice.chen@apex-ip.com for follow up."
    masked, rules = redact(text, tenant_id="tenant_a")

    assert "alice.chen@apex-ip.com" not in masked
    assert "email" in rules
    placeholders = _PLACEHOLDER_RE.findall(masked)
    assert any(p.startswith("[EMAIL_") for p in placeholders), placeholders


def test_tw_phone_is_redacted():
    text = "Mobile: 0912-345-678 (Taipei office)."
    masked, rules = redact(text, tenant_id="tenant_a")

    assert "0912-345-678" not in masked
    assert "phone_tw" in rules
    placeholders = _PLACEHOLDER_RE.findall(masked)
    assert any(p.startswith("[PHONE_") for p in placeholders), placeholders


def test_tenant_dictionary_terms_are_redacted():
    # Both rules under TENANT_DICTIONARIES["tenant_a"] should trigger:
    # apex_case_no  → APEX-2025-0314
    # apex_client_code → CL-EVCO12
    text = "Internal file ref: APEX-2025-0314, client code CL-EVCO12."
    masked, rules = redact(text, tenant_id="tenant_a")

    assert "APEX-2025-0314" not in masked
    assert "CL-EVCO12" not in masked
    assert "apex_case_no" in rules
    assert "apex_client_code" in rules
    placeholders = _PLACEHOLDER_RE.findall(masked)
    assert any(p.startswith("[CASE_REF_") for p in placeholders), placeholders
    assert any(p.startswith("[CLIENT_CODE_") for p in placeholders), placeholders


# --- round-trip / behaviour preservation -----------------------------------

def test_redact_unmask_round_trip_exact():
    redacted, triggered = masking.redact(SAMPLE, "tenant_a")

    # placeholders replaced the raw PII
    assert EMAIL not in redacted
    assert PHONE not in redacted
    assert CASE not in redacted
    assert CLIENT not in redacted

    # un-redaction restores the exact original cleartext for the attorney
    restored = masking.unmask(redacted, "tenant_a")
    assert restored == SAMPLE


def test_verify_sh_rules_all_fire():
    _, triggered = masking.redact(SAMPLE, "tenant_a")
    for rule_id in ("email", "phone_tw", "apex_case_no", "apex_client_code"):
        assert rule_id in triggered, f"{rule_id} did not fire"


def test_same_value_same_placeholder_per_tenant():
    """Stable id: identical input value maps to identical placeholder."""
    text = f"{EMAIL} and again {EMAIL}"
    redacted, _ = masking.redact(text, "tenant_a")
    # exactly one distinct placeholder for the repeated email
    placeholders = set(re.findall(r"\[EMAIL_[0-9A-F]{8}\]", redacted))
    assert len(placeholders) == 1


def test_store_round_trip_via_public_store_api(store):
    placeholder = "[EMAIL_DEADBEEF]"
    store.remember("tenant_a", placeholder, EMAIL, "email")
    assert store.get_original("tenant_a", placeholder) == EMAIL


# --- at-rest encryption ----------------------------------------------------

def test_original_column_is_encrypted_on_disk(tmp_path):
    db_path = tmp_path / "redaction_mapping.db"
    store = MaskingStore(path=db_path)
    placeholder = "[EMAIL_CAFEBABE]"
    store.remember("tenant_a", placeholder, EMAIL, "email")

    # Read the raw bytes straight off disk, bypassing the store API entirely.
    raw_blob = db_path.read_bytes()
    assert EMAIL.encode() not in raw_blob, "plaintext email leaked into the .db file"

    # And the column value itself is not the plaintext.
    conn = sqlite3.connect(db_path)
    try:
        stored = conn.execute(
            "SELECT original FROM mappings WHERE tenant_id=? AND placeholder=?",
            ("tenant_a", placeholder),
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored != EMAIL
    assert EMAIL not in stored
    # but the store can still decrypt it back
    assert store.get_original("tenant_a", placeholder) == EMAIL


def test_cross_tenant_isolation(tmp_path):
    """A value encrypted under tenant_a must not decrypt under tenant_b."""
    db_path = tmp_path / "redaction_mapping.db"
    store = MaskingStore(path=db_path)
    placeholder = "[EMAIL_FEEDFACE]"
    store.remember("tenant_a", placeholder, EMAIL, "email")

    # Same placeholder, but queried as tenant_b -> no row for tenant_b at all.
    assert store.get_original("tenant_b", placeholder) is None

    # Now force the ciphertext bytes into tenant_b's namespace and confirm
    # tenant_b's derived key cannot decrypt tenant_a's ciphertext.
    conn = sqlite3.connect(db_path)
    try:
        ciphertext = conn.execute(
            "SELECT original FROM mappings WHERE tenant_id=? AND placeholder=?",
            ("tenant_a", placeholder),
        ).fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO mappings(tenant_id, placeholder, original, rule_id) "
            "VALUES (?, ?, ?, ?)",
            ("tenant_b", placeholder, ciphertext, "email"),
        )
        conn.commit()
    finally:
        conn.close()

    # tenant_b sees a row but cannot decrypt it -> graceful None (keeps placeholder)
    assert store.get_original("tenant_b", placeholder) is None
    # tenant_a still decrypts fine
    assert store.get_original("tenant_a", placeholder) == EMAIL


def test_unmask_keeps_placeholder_when_undecryptable(tmp_path, monkeypatch):
    """Legacy/corrupt plaintext row degrades to the placeholder, not a crash."""
    db_path = tmp_path / "redaction_mapping.db"
    store = MaskingStore(path=db_path)
    placeholder = "[EMAIL_0BADF00D]"

    # Simulate a stray legacy plaintext row (pre-encryption) written directly.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO mappings(tenant_id, placeholder, original, rule_id) "
            "VALUES (?, ?, ?, ?)",
            ("tenant_a", placeholder, "not-a-valid-fernet-token", "email"),
        )
        conn.commit()
    finally:
        conn.close()

    # Does not raise; returns None so unmask leaves the placeholder in place.
    assert store.get_original("tenant_a", placeholder) is None

    # And the module-level unmask path leaves an undecryptable placeholder intact.
    monkeypatch.setattr(masking, "_store", store)
    text = f"see {placeholder} here"
    assert masking.unmask(text, "tenant_a") == text
