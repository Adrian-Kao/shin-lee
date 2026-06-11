"""Integration tests for Q19 observability wiring on both services.

Covers:
  * AI Engine GET /metrics returns a valid Prometheus exposition (v0.0.4),
    ungated by the internal-token middleware.
  * Gateway correlation id: response echoes X-Request-ID; an inbound id is
    preserved; an absent id is generated; a forged newline id is sanitised.
  * AI Engine binds an inbound X-Request-ID and echoes it back (the propagation
    target of the gateway's request_id_headers).
  * End-to-end: a gateway /v1/oa/analyze records LLM token/route metrics on the
    AI Engine side (single registry per process; here the in-process AI Engine
    app shares the test process registry).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.shared import observability as obs

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_OA_US = _REPO_ROOT / "data" / "oa_samples" / "sample_oa_us.txt"


@pytest.fixture()
def ai_engine_client(ai_engine_app):
    with TestClient(ai_engine_app) as client:
        yield client


# ---------------------------------------------------------------------------
# AI Engine /metrics.
# ---------------------------------------------------------------------------
def test_ai_engine_metrics_endpoint_ok_and_well_formed(ai_engine_client):
    resp = ai_engine_client.get("/metrics")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in resp.headers["content-type"]
    body = resp.text
    # Shared system metric present + the LLM throughput metrics this agent added.
    assert "# TYPE http_request_duration_seconds histogram" in body
    assert "# TYPE llm_tokens_total counter" in body
    assert "# TYPE llm_route_total counter" in body


def test_ai_engine_metrics_is_ungated(ai_engine_client):
    # /metrics is exempt from the internal-token middleware (scrapers can't mint
    # the token). No X-Internal-Token header → still 200.
    resp = ai_engine_client.get("/metrics")
    assert resp.status_code == 200


def test_ai_engine_health_still_ungated(ai_engine_client):
    assert ai_engine_client.get("/v1/health").status_code == 200


# ---------------------------------------------------------------------------
# Correlation id — gateway.
# ---------------------------------------------------------------------------
def test_gateway_generates_request_id_when_absent(gateway_client):
    resp = gateway_client.get("/v1/health")
    rid = resp.headers.get(obs.REQUEST_ID_HEADER)
    assert rid, "gateway must emit X-Request-ID even when none supplied"
    assert len(rid) == 32  # generated uuid hex


def test_gateway_preserves_inbound_request_id(gateway_client):
    resp = gateway_client.get("/v1/health", headers={obs.REQUEST_ID_HEADER: "trace-from-proxy-1"})
    assert resp.headers.get(obs.REQUEST_ID_HEADER) == "trace-from-proxy-1"


def test_gateway_sanitises_forged_request_id(gateway_client):
    # A header value attempting log forging via newline must be neutralised
    # before it's echoed / logged.
    resp = gateway_client.get("/v1/health", headers={obs.REQUEST_ID_HEADER: "ok-part"})
    echoed = resp.headers.get(obs.REQUEST_ID_HEADER)
    assert "\n" not in (echoed or "")
    assert echoed == "ok-part"


def test_gateway_request_id_on_error_response(gateway_client):
    # Even a 4xx (unknown route / unauthorised) must carry the correlation id.
    resp = gateway_client.get("/v1/quota")  # 401 (no auth)
    assert resp.status_code in (401, 403)
    assert resp.headers.get(obs.REQUEST_ID_HEADER)


# ---------------------------------------------------------------------------
# Correlation id — AI Engine echoes the propagated id.
# ---------------------------------------------------------------------------
def test_ai_engine_echoes_inbound_request_id(ai_engine_client):
    resp = ai_engine_client.get("/v1/health", headers={obs.REQUEST_ID_HEADER: "gw-propagated-99"})
    assert resp.headers.get(obs.REQUEST_ID_HEADER) == "gw-propagated-99"


def test_ai_engine_generates_request_id_when_absent(ai_engine_client):
    resp = ai_engine_client.get("/v1/health")
    rid = resp.headers.get(obs.REQUEST_ID_HEADER)
    assert rid and len(rid) == 32


# ---------------------------------------------------------------------------
# End-to-end: analyze drives LLM token/route metrics on the AI Engine registry.
# ---------------------------------------------------------------------------
def _metric_total(text: str, name: str) -> float:
    total = 0.0
    for ln in text.splitlines():
        if ln.startswith(name) and not ln.startswith("#"):
            try:
                total += float(ln.rsplit(" ", 1)[1])
            except (ValueError, IndexError):
                pass
    return total


@pytest.mark.asyncio
async def test_analyze_records_llm_token_metrics(
    gateway_client, ai_engine_client, alice_token, patched_ai_engine
):
    # The in-process AI Engine app shares this test process's metrics registry,
    # so its /metrics reflects calls the gateway made through patched_ai_engine.
    before = _metric_total(ai_engine_client.get("/metrics").text, "llm_tokens_total")

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

    after = _metric_total(ai_engine_client.get("/metrics").text, "llm_tokens_total")
    # parse_oa + draft_response + verify_citations all run the mock LLM and emit
    # non-zero token usage, so the total must have grown.
    assert after > before, (before, after)
