"""Integration tests for the gateway /metrics endpoint (Q19).

Proves:
  * GET /metrics -> 200, Content-Type text/plain; version=0.0.4, and the
    expected four-layer metric names are present.
  * After an /v1/oa/analyze call, oa_analyzed_total increased and an
    http_request_duration_seconds sample was recorded for that endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_OA_US = _REPO_ROOT / "data" / "oa_samples" / "sample_oa_us.txt"

_EXPECTED_NAMES = [
    # 系統
    "http_request_duration_seconds",
    "llm_errors_total",
    "audit_write_duration_seconds",
    # 成本
    "llm_cost_usd_total",
    "llm_cost_usd_month_to_date",
    # 業務
    "oa_analyzed_total",
    "exports_total",
    "signoff_refused_total",
    # 品質
    "citations_total",
    "citations_invalid_total",
    "prompt_injection_detected_total",
]


def test_metrics_endpoint_ok_and_well_formed(gateway_client):
    resp = gateway_client.get("/metrics")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in resp.headers["content-type"]
    body = resp.text
    for name in _EXPECTED_NAMES:
        assert name in body, f"missing metric {name}"
    # HELP/TYPE present for at least one of each shape.
    assert "# TYPE oa_analyzed_total counter" in body
    assert "# TYPE http_request_duration_seconds histogram" in body


def test_metrics_is_ungated(gateway_client):
    # POC posture: /metrics is intentionally not auth-gated (network-restricted
    # in prod). No Authorization header -> still 200.
    resp = gateway_client.get("/metrics")
    assert resp.status_code == 200


def _oa_count(text: str) -> float:
    total = 0.0
    for ln in text.splitlines():
        if ln.startswith("oa_analyzed_total") and not ln.startswith("#"):
            total += float(ln.rsplit(" ", 1)[1])
    return total


@pytest.mark.asyncio
async def test_analyze_increments_business_and_latency_metrics(
    gateway_client, alice_token, patched_ai_engine
):
    before = _oa_count(gateway_client.get("/metrics").text)

    oa_text = _SAMPLE_OA_US.read_text(encoding="utf-8")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": oa_text,
            "case_id": "CASE-2025-001",
            "target_patent_no": "US17123456",
        },
    )
    assert resp.status_code == 200, resp.text

    after_text = gateway_client.get("/metrics").text
    after = _oa_count(after_text)
    assert after == before + 1.0, (before, after)

    # A request-duration sample for /v1/oa/analyze was recorded (count >= 1).
    found_analyze_duration_count = any(
        ln.startswith("http_request_duration_seconds_count") and "/v1/oa/analyze" in ln
        for ln in after_text.splitlines()
    )
    assert found_analyze_duration_count, after_text
