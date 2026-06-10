"""Unit tests for the per-tenant UPLOADABLE masking dictionary (Q10 layer 2).

The hard-coded ``TENANT_DICTIONARIES`` used to be the only source of a firm's
customer-identifier rules. These tests cover the on-disk JSON loader that
replaces it (with the hard-coded set kept as a fallback):

  - a tenant's rules load from JSON and fire in redact() (round-trip exact).
  - built-in PII rules still fire alongside the loaded dictionary.
  - a malformed regex in a tenant JSON is skipped (logged), without breaking
    redaction of the other rules.
  - an unknown tenant with no JSON falls back gracefully (built-ins only).
  - an uploaded/reloaded dictionary takes effect after reload().
  - the DoS length guard rejects over-long patterns.
"""
from __future__ import annotations

import json
import re

import pytest

from backend.gateway import masking
from backend.gateway.masking import (
    MAX_TENANT_PATTERN_LEN,
    MaskingStore,
    get_tenant_rules,
    redact,
    reload_tenant_dictionary,
)

_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")


# --- fixtures --------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_module_store(tmp_path, monkeypatch):
    """Fresh per-test mapping DB so redact/unmask don't share global state."""
    fresh = MaskingStore(path=tmp_path / "module_mapping.db")
    monkeypatch.setattr(masking, "_store", fresh)
    return fresh


@pytest.fixture(autouse=True)
def isolated_tenant_dicts(tmp_path, monkeypatch):
    """Point the loader at an empty temp dir and clear the compiled cache.

    Each test seeds whatever JSON it needs. Clearing the cache (before AND
    after) prevents cross-test leakage of compiled rules.
    """
    dict_dir = tmp_path / "tenant_dicts"
    dict_dir.mkdir()
    monkeypatch.setattr(masking, "TENANT_DICTS_DIR", dict_dir)
    reload_tenant_dictionary(None)  # clear all
    yield dict_dir
    reload_tenant_dictionary(None)


def _write_dict(dict_dir, tenant_id, rules):
    path = dict_dir / f"{tenant_id}.json"
    path.write_text(
        json.dumps({"tenant_id": tenant_id, "rules": rules}),
        encoding="utf-8",
    )
    return path


# --- 1. tenant rules load from JSON and fire (round-trip exact) ------------

def test_tenant_json_rules_fire_and_round_trip(isolated_tenant_dicts):
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "apex_case_no",
                "pattern": r"\bAPEX-\d{4}-\d{3,5}\b",
                "placeholder_prefix": "CASE_REF",
                "description": "Apex internal case number",
            }
        ],
    )
    reload_tenant_dictionary("tenant_a")

    case = "APEX-2025-0314"
    text = f"Internal file ref: {case}."
    masked, rules = redact(text, tenant_id="tenant_a")

    assert case not in masked
    assert "apex_case_no" in rules
    assert any(p.startswith("[CASE_REF_") for p in _PLACEHOLDER_RE.findall(masked))

    # exact round-trip
    assert masking.unmask(masked, "tenant_a") == text


# --- 2. built-in PII fires alongside the loaded dictionary -----------------

def test_builtin_pii_fires_alongside_tenant_dict(isolated_tenant_dicts):
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "apex_case_no",
                "pattern": r"\bAPEX-\d{4}-\d{3,5}\b",
                "placeholder_prefix": "CASE_REF",
                "description": "case no",
            }
        ],
    )
    reload_tenant_dictionary("tenant_a")

    text = "Email me at john.doe@example.com about APEX-2025-0314."
    masked, rules = redact(text, tenant_id="tenant_a")

    assert "john.doe@example.com" not in masked
    assert "APEX-2025-0314" not in masked
    assert "email" in rules           # built-in PII layer
    assert "apex_case_no" in rules    # tenant dictionary layer


# --- 3. malformed regex is skipped, others still fire ----------------------

def test_malformed_regex_is_skipped_others_survive(isolated_tenant_dicts, caplog):
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "broken",
                "pattern": r"(unclosed[group",  # invalid regex
                "placeholder_prefix": "BROKEN",
                "description": "intentionally broken",
            },
            {
                "rule_id": "good_code",
                "pattern": r"\bZZ-\d{3}\b",
                "placeholder_prefix": "ZCODE",
                "description": "valid rule",
            },
        ],
    )
    with caplog.at_level("WARNING"):
        rules = reload_tenant_dictionary("tenant_a")

    # the broken rule was dropped; the good one survived
    rule_ids = {r.rule_id for r in rules}
    assert "broken" not in rule_ids
    assert "good_code" in rule_ids
    assert any("broken" in rec.message and "invalid regex" in rec.message
               for rec in caplog.records)

    # redaction still works for the good rule AND built-in PII
    text = "Code ZZ-123 and mail x@y.com."
    masked, fired = redact(text, tenant_id="tenant_a")
    assert "ZZ-123" not in masked
    assert "x@y.com" not in masked
    assert "good_code" in fired
    assert "email" in fired


# --- 4. unknown tenant with no JSON -> built-ins only (graceful) -----------

def test_unknown_tenant_no_json_falls_back_to_builtins(isolated_tenant_dicts):
    # No JSON file for "ghost_tenant" and no hard-coded entry either.
    rules = get_tenant_rules("ghost_tenant")
    assert rules == []  # no layer-2 rules

    text = "reach me at jane@firm.com"
    masked, fired = redact(text, tenant_id="ghost_tenant")
    assert "jane@firm.com" not in masked
    assert "email" in fired  # built-in PII still applies


def test_known_tenant_no_json_falls_back_to_hardcoded(isolated_tenant_dicts):
    """No JSON file but a hard-coded TENANT_DICTIONARIES entry exists -> use it."""
    # isolated_tenant_dicts dir is empty, so tenant_a has no JSON here.
    rules = get_tenant_rules("tenant_a")
    rule_ids = {r.rule_id for r in rules}
    # falls back to the hard-coded demo rules
    assert "apex_case_no" in rule_ids
    assert "apex_client_code" in rule_ids


# --- 5. uploaded/reloaded dictionary takes effect after reload -------------

def test_reload_picks_up_newly_uploaded_rule(isolated_tenant_dicts):
    # Start: a dictionary WITHOUT the new rule.
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "old_code",
                "pattern": r"\bOLD-\d{3}\b",
                "placeholder_prefix": "OLD",
                "description": "old",
            }
        ],
    )
    reload_tenant_dictionary("tenant_a")

    new_id = "NEW-555"
    masked_before, fired_before = redact(f"id {new_id}", tenant_id="tenant_a")
    assert new_id in masked_before  # NEW-* not yet a rule
    assert "new_code" not in fired_before

    # Ops uploads an updated dictionary including the new rule, then reloads.
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "old_code",
                "pattern": r"\bOLD-\d{3}\b",
                "placeholder_prefix": "OLD",
                "description": "old",
            },
            {
                "rule_id": "new_code",
                "pattern": r"\bNEW-\d{3}\b",
                "placeholder_prefix": "NEW",
                "description": "new",
            },
        ],
    )
    reload_tenant_dictionary("tenant_a")

    masked_after, fired_after = redact(f"id {new_id}", tenant_id="tenant_a")
    assert new_id not in masked_after  # now redacted
    assert "new_code" in fired_after


# --- 6. DoS length guard ---------------------------------------------------

def test_overlong_pattern_is_rejected(isolated_tenant_dicts, caplog):
    long_pattern = "a" * (MAX_TENANT_PATTERN_LEN + 1)
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [
            {
                "rule_id": "huge",
                "pattern": long_pattern,
                "placeholder_prefix": "HUGE",
                "description": "too long",
            },
            {
                "rule_id": "fine",
                "pattern": r"\bQQ-\d{2}\b",
                "placeholder_prefix": "QQ",
                "description": "ok",
            },
        ],
    )
    with caplog.at_level("WARNING"):
        rules = reload_tenant_dictionary("tenant_a")

    rule_ids = {r.rule_id for r in rules}
    assert "huge" not in rule_ids
    assert "fine" in rule_ids
    assert any("safety cap" in rec.message for rec in caplog.records)


# --- 7. caching: redact doesn't re-read disk every call --------------------

def test_rules_are_cached_until_reload(isolated_tenant_dicts, monkeypatch):
    _write_dict(
        isolated_tenant_dicts,
        "tenant_a",
        [{"rule_id": "c", "pattern": r"\bC-\d\b", "placeholder_prefix": "C",
          "description": "c"}],
    )
    reload_tenant_dictionary("tenant_a")

    calls = {"n": 0}
    real_reader = masking._read_tenant_dictionary

    def _counting_reader(tid):
        calls["n"] += 1
        return real_reader(tid)

    monkeypatch.setattr(masking, "_read_tenant_dictionary", _counting_reader)

    # Many redact calls -> loader is NOT invoked again (served from cache).
    for _ in range(5):
        redact("C-1", tenant_id="tenant_a")
    assert calls["n"] == 0

    # reload bypasses the cache and re-reads exactly once.
    reload_tenant_dictionary("tenant_a")
    assert calls["n"] == 1


# --- 8. malformed JSON file falls back, never crashes ----------------------

def test_corrupt_json_file_falls_back_gracefully(isolated_tenant_dicts):
    path = isolated_tenant_dicts / "tenant_a.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    reload_tenant_dictionary("tenant_a")

    # Falls back to hard-coded tenant_a rules; redaction still works.
    rules = get_tenant_rules("tenant_a")
    rule_ids = {r.rule_id for r in rules}
    assert "apex_case_no" in rule_ids

    masked, fired = redact("mail z@z.com", tenant_id="tenant_a")
    assert "z@z.com" not in masked
    assert "email" in fired
