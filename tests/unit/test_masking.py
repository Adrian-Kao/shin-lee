"""Unit tests for `backend.gateway.masking.redact`.

Covers the three masking layers wired into the POC:
    1. Built-in PII regex (email, TW phone).
    2. Tenant-specific dictionary (Apex case ref / client code).

Invariant under test: redact() never returns the original sensitive token
verbatim — it always replaces it with a stable bracketed placeholder.
"""
from __future__ import annotations

import re

from backend.gateway.masking import redact

_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")


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
