"""DifyLLM (Phase 3 — LLM_MODE=dify) unit tests. Fully hermetic.

What is proven here:

  1. REQUEST SHAPE — DifyLLM posts to {DIFY_API_URL}/v1/workflows/run with
     Bearer auth, response_mode=blocking, and inputs={"intent","query"} —
     the exact contract of the `patentmind-analyze-oa` Dify workflow app.
  2. JSON EXTRACTION — markdown fences / prose around the model's JSON are
     stripped so oa_analyzer._safe_json always gets a clean object.
  3. DEGRADE PATH — Dify unreachable / non-2xx / workflow failed / missing
     API key ⇒ loud fallback to MockLLM with a "-DEGRADED-mock" model label
     (the degraded flag that surfaces in response metadata + audit rows).
  4. VERIFIER STAYS LOCAL — intent=verify_citations never makes an HTTP
     call (the Q14 hard wall lives in our code, by design).
  5. ROUTER WIRING — llm_client.chat() with LLM_MODE=dify dispatches to the
     DifyLLM singleton; route_model reports the DIFY_MODEL_LABEL.

No network: every HTTP interaction uses httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx

from backend.ai_engine import llm_client
from backend.ai_engine.llm_client import DifyLLM, LLMResponse
from backend.shared.config import settings

API_URL = "http://dify.test:8088"
API_KEY = "app-unit-test-key"


def _workflow_ok(text: str, total_tokens: int = 321) -> dict:
    """Shape of a successful blocking /v1/workflows/run response (Dify 1.x)."""
    return {
        "workflow_run_id": "wfr-123",
        "task_id": "task-123",
        "data": {
            "id": "wfr-123",
            "workflow_id": "wf-1",
            "status": "succeeded",
            "outputs": {"text": text},
            "error": None,
            "elapsed_time": 1.23,
            "total_tokens": total_tokens,
            "total_steps": 3,
        },
    }


def _dify(handler) -> DifyLLM:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return DifyLLM(api_url=API_URL, api_key=API_KEY, client=client)


PARSE_JSON = json.dumps(
    {
        "rejections": [
            {
                "rejection_id": "rej-1",
                "rejection_type": "103_obviousness",
                "affected_claims": [1, 2, 3],
                "cited_prior_art": ["TW202131234"],
                "examiner_argument": "不具進步性",
                "confidence": 0.9,
            }
        ]
    }
)


# ---------------------------------------------------------------------------
# 1. Request shape
# ---------------------------------------------------------------------------


def test_request_shape_parse_oa():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_workflow_ok(PARSE_JSON))

    resp = _dify(handler).chat("SYSTEM", "OA text 請求項1不具進步性", "parse_oa", "hint")

    assert seen["url"] == f"{API_URL}/v1/workflows/run"
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert seen["body"]["response_mode"] == "blocking"
    assert seen["body"]["inputs"]["intent"] == "parse_oa"
    assert seen["body"]["inputs"]["query"] == "OA text 請求項1不具進步性"
    assert seen["body"]["user"]  # attribution required by Dify API

    assert isinstance(resp, LLMResponse)
    assert resp.model == settings.DIFY_MODEL_LABEL
    assert "DEGRADED" not in resp.model
    assert json.loads(resp.text)["rejections"][0]["rejection_type"] == "103_obviousness"


def test_token_accounting_from_total_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok(PARSE_JSON, total_tokens=500))

    resp = _dify(handler).chat("S", "U", "parse_oa", "hint")
    assert resp.prompt_tokens + resp.completion_tokens >= 1
    assert resp.completion_tokens >= 1


# ---------------------------------------------------------------------------
# 2. JSON extraction (qwen loves markdown fences)
# ---------------------------------------------------------------------------


def test_json_extracted_from_markdown_fence():
    fenced = f"Here you go:\n```json\n{PARSE_JSON}\n```\nHope that helps!"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok(fenced))

    resp = _dify(handler).chat("S", "U", "parse_oa", "hint")
    data = json.loads(resp.text)  # must be directly parseable after extraction
    assert data["rejections"][0]["rejection_id"] == "rej-1"


def test_json_extracted_from_prose_with_trailing_braces():
    noisy = "Sure. " + PARSE_JSON + " }} extra junk {"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok(noisy))

    resp = _dify(handler).chat("S", "U", "parse_oa", "hint")
    assert json.loads(resp.text)["rejections"][0]["affected_claims"] == [1, 2, 3]


def test_non_json_output_passes_through_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok("plain prose, no json"))

    resp = _dify(handler).chat("S", "U", "parse_oa", "hint")
    assert resp.text == "plain prose, no json"  # _safe_json downstream → {}


# ---------------------------------------------------------------------------
# 3. Degrade paths — every failure mode falls back to MockLLM, loudly
# ---------------------------------------------------------------------------


def _assert_degraded_but_usable(resp: LLMResponse):
    assert "DEGRADED" in resp.model
    # the mock still emits a parseable parse_oa contract → demo never dies
    assert "rejections" in json.loads(resp.text)


def test_degrade_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    resp = _dify(handler).chat("S", "請求項1不具進步性", "parse_oa", "hint")
    _assert_degraded_but_usable(resp)


def test_degrade_on_http_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    resp = _dify(handler).chat("S", "請求項1不具進步性", "parse_oa", "hint")
    _assert_degraded_but_usable(resp)


def test_degrade_on_workflow_failed_status():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _workflow_ok("")
        body["data"]["status"] = "failed"
        body["data"]["error"] = "model provider error"
        return httpx.Response(200, json=body)

    resp = _dify(handler).chat("S", "請求項1不具進步性", "parse_oa", "hint")
    _assert_degraded_but_usable(resp)


def test_degrade_on_empty_output():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok("   "))

    resp = _dify(handler).chat("S", "請求項1不具進步性", "parse_oa", "hint")
    _assert_degraded_but_usable(resp)


def test_degrade_when_api_key_missing():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(200, json=_workflow_ok(PARSE_JSON))

    transport = httpx.MockTransport(handler)
    d = DifyLLM(api_url=API_URL, api_key="", client=httpx.Client(transport=transport))
    resp = d.chat("S", "請求項1不具進步性", "parse_oa", "hint")
    _assert_degraded_but_usable(resp)
    assert called["n"] == 0  # never even tried the network


# ---------------------------------------------------------------------------
# 4. Verifier stays local — Q14 hard wall is OUR code, not the Dify model
# ---------------------------------------------------------------------------


def test_verify_citations_never_hits_dify():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(200, json=_workflow_ok("{}"))

    d = _dify(handler)
    user = (
        "DRAFT:\n<untrusted_input>\nsee [GROUNDED_REF_1]\n</untrusted_input>\n\n"
        "GROUNDED_SET keys: ['[GROUNDED_REF_1]']\n\nConfirm."
    )
    resp = d.chat("S", user, "verify_citations", "hint")
    assert called["n"] == 0
    assert resp.model == "local-verifier-mock"
    vdata = json.loads(resp.text)
    assert vdata["valid"] is True
    assert "[GROUNDED_REF_1]" in vdata["valid_citations"]


# ---------------------------------------------------------------------------
# 5. Router wiring (LLM_MODE=dify)
# ---------------------------------------------------------------------------


def test_chat_router_dispatches_to_dify(monkeypatch):
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        return httpx.Response(200, json=_workflow_ok(PARSE_JSON))

    monkeypatch.setattr(settings, "LLM_MODE", "dify")
    monkeypatch.setattr(llm_client, "_dify_singleton", _dify(handler), raising=True)
    try:
        resp = llm_client.chat(
            system="S",
            user="請求項1不具進步性",
            intent="parse_oa",
            security_level="public",
        )
        assert seen["n"] == 1
        assert resp.model == settings.DIFY_MODEL_LABEL
    finally:
        llm_client.reset_dify_singleton()


def test_chat_router_dify_confidential_stays_local_path(monkeypatch):
    """Invariant #7: confidential under LLM_MODE=dify is allowed because the
    Dify workflow's LLM nodes run on local Ollama — no cloud egress exists.
    The call must succeed (NOT raise the anthropic cloud-refusal)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_workflow_ok(PARSE_JSON))

    monkeypatch.setattr(settings, "LLM_MODE", "dify")
    monkeypatch.setattr(llm_client, "_dify_singleton", _dify(handler), raising=True)
    try:
        resp = llm_client.chat(
            system="S",
            user="機密 OA",
            intent="parse_oa",
            security_level="confidential",
        )
        assert "rejections" in json.loads(resp.text)
    finally:
        llm_client.reset_dify_singleton()


def test_route_model_reports_dify_label(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "dify")
    model = llm_client.route_model(intent="parse_oa", security_level="public", circuit_open=False)
    assert model == settings.DIFY_MODEL_LABEL
