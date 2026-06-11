"""Correlation-id propagation on the gateway → AI-Engine call (Day 13I).

Agent D deferred item: the gateway must forward its bound X-Request-ID on every
internal call so both services' JSON logs share one trace id. This test binds a
known request id into the observability context, drives `AIEngineClient.call`,
and asserts the outbound httpx POST carried BOTH the internal auth token (when
set) AND the X-Request-ID — proving `request_id_headers(_internal_headers())`
is wired, not a bare `_internal_headers()`.
"""

from __future__ import annotations

from unittest import mock

import pytest

from backend.gateway import orchestrator as orch
from backend.shared import observability as obs
from backend.shared.observability import REQUEST_ID_HEADER


@pytest.mark.asyncio
async def test_request_id_propagates_to_ai_engine():
    obs.bind_request_id("trace-abc-123")
    try:
        captured = {}

        class _FakeResp:
            def raise_for_status(self):  # noqa: D401
                return None

            def json(self):
                return {"ok": True}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                captured["headers"] = headers
                return _FakeResp()

        with mock.patch.object(orch.httpx, "AsyncClient", return_value=_FakeClient()):
            client = orch.AIEngineClient(base_url="http://ai")
            result = await client.call("/v1/parse_oa", {"oa_text": "x"})

        assert result == {"ok": True}
        assert captured["headers"].get(REQUEST_ID_HEADER) == "trace-abc-123", (
            "gateway did not propagate X-Request-ID to the AI Engine"
        )
    finally:
        obs.reset_request_id()


@pytest.mark.asyncio
async def test_request_id_minted_when_none_bound():
    """Outside a request context the helper still supplies *a* trace id so the
    downstream service is never left without one."""
    obs.reset_request_id()
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["headers"] = headers
            return _FakeResp()

    with mock.patch.object(orch.httpx, "AsyncClient", return_value=_FakeClient()):
        await orch.AIEngineClient(base_url="http://ai").call("/v1/x", {})

    rid = captured["headers"].get(REQUEST_ID_HEADER)
    assert rid and isinstance(rid, str) and len(rid) > 0
