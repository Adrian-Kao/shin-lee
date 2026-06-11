"""Unit tests for the gateway egress guard (Q3 / invariant #3 enforcement).

The egress guard lives in `backend.gateway.orchestrator` and runs inside the
single egress point to the AI Engine (`AIEngineClient.call`). It recursively
scans every outbound payload for raw PII patterns (reusing
`masking.PII_RULES`). A hit means redaction escaped upstream — the guard logs
an error-level alert and raises `EgressGuardError` (fail closed).

These tests exercise the pure scan/assert helpers directly (no network) plus
the async `call` path with a stubbed httpx layer, so they stay hermetic.
"""

from __future__ import annotations

import logging

import pytest

from backend.gateway import orchestrator as orch
from backend.gateway.orchestrator import (
    AIEngineClient,
    EgressGuardError,
    _assert_no_raw_pii,
    _scan_value_for_pii,
)
from backend.shared.config import settings


# ---------------------------------------------------------------------------
# Pure scanner: raw PII is detected, placeholders are not.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected_rule",
    [
        ("Contact alice.chen@apex-ip.com please", "email"),
        ("ID is A123456789 on file", "tw_id"),
        ("SSN 123-45-6789 redacted?", "ssn"),
        ("call 0912-345-678 today", "phone_tw"),
    ],
)
def test_scanner_flags_raw_pii(value, expected_rule):
    assert _scan_value_for_pii(value) == expected_rule


def test_scanner_passes_placeholders():
    # The shapes produced by masking.redact() must NOT trip the guard.
    placeholders = [
        "[EMAIL_A1B2C3D4]",
        "[SSN_12345678]",
        "[TW_ID_A1234567]",
        "[PHONE_DEADBEEF]",
        "Per [EMAIL_A1B2C3D4], see ref [CASE_REF_00112233].",
    ]
    for p in placeholders:
        assert _scan_value_for_pii(p) is None, p


def test_scanner_recurses_nested_payload():
    payload = {
        "tenant_id": "tenant_a",
        "rejection": {
            "examiner_argument": "redacted text [EMAIL_A1B2C3D4]",
            "cited": ["US123", {"note": "raw leak alice@x.com here"}],
        },
    }
    assert _scan_value_for_pii(payload) == "email"


def test_scanner_clean_realistic_payload():
    # A realistic *already-redacted* outbound payload must scan clean so the
    # guard never false-positives on the happy path.
    payload = {
        "oa_text": "Claim 1 rejected under 35 USC 102. See [EMAIL_A1B2C3D4].",
        "tenant_id": "tenant_a",
        "case_id": "CASE-2025-001",
        "target_patent_no": "US17123456",
        "security_level": "public",
    }
    assert _scan_value_for_pii(payload) is None


# ---------------------------------------------------------------------------
# _assert_no_raw_pii: blocks raw PII, honours the enable flag, logs an alert.
# ---------------------------------------------------------------------------
def test_assert_blocks_raw_email():
    with pytest.raises(EgressGuardError) as ei:
        _assert_no_raw_pii("/v1/parse_oa", {"oa_text": "alice@x.com"})
    assert ei.value.rule_id == "email"
    assert ei.value.path == "/v1/parse_oa"


def test_assert_blocks_raw_tw_id():
    with pytest.raises(EgressGuardError) as ei:
        _assert_no_raw_pii("/v1/draft_response", {"x": {"y": "A123456789"}})
    assert ei.value.rule_id == "tw_id"


def test_assert_blocks_raw_ssn():
    with pytest.raises(EgressGuardError) as ei:
        _assert_no_raw_pii("/v1/parse_oa", {"oa_text": "123-45-6789"})
    assert ei.value.rule_id == "ssn"


def test_assert_allows_placeholder_only_payload():
    # Must NOT raise.
    _assert_no_raw_pii(
        "/v1/parse_oa",
        {"oa_text": "see [EMAIL_A1B2C3D4] and [SSN_12345678]", "case_id": "C-1"},
    )


def test_assert_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(settings, "EGRESS_GUARD_ENABLED", False)
    # Even with raw PII present, the guard is a no-op when disabled.
    _assert_no_raw_pii("/v1/parse_oa", {"oa_text": "alice@x.com"})


def test_assert_logs_error_alert(caplog):
    with caplog.at_level(logging.ERROR, logger="patentmind.gateway.egress"):
        with pytest.raises(EgressGuardError):
            _assert_no_raw_pii("/v1/parse_oa", {"oa_text": "alice@x.com"})
    msgs = [r.getMessage() for r in caplog.records]
    assert any("EGRESS GUARD" in m and "email" in m for m in msgs), msgs
    # The alert must NOT echo the offending value (no PII re-leak into logs).
    assert all("alice@x.com" not in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# AIEngineClient.call: the guard runs BEFORE any HTTP egress.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_call_blocks_before_http(monkeypatch):
    """A raw-PII payload must raise EgressGuardError without opening a socket."""

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("httpx.AsyncClient must not be constructed")

    monkeypatch.setattr(orch.httpx, "AsyncClient", _boom)
    client = AIEngineClient()
    with pytest.raises(EgressGuardError):
        await client.call("/v1/parse_oa", {"oa_text": "leak alice@x.com"})
