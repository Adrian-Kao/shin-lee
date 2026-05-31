"""Shared pytest fixtures for the patentmind-poc test suite.

This module is intentionally written so importing it has the side-effect of
configuring environment variables for mock/in-memory backends *before* the
backend FastAPI apps are imported. Pytest loads `conftest.py` ahead of any
collected test module, so any subsequent `from backend.xxx import app` will
see these env vars.

Fixtures provided:
    - gateway_client       : starlette.testclient.TestClient bound to
                             backend.gateway.main:app
    - alice_token          : valid JWT for the demo "alice" attorney user
    - patched_ai_engine    : autouse-ish helper that rewires the gateway
                             orchestrator's httpx.AsyncClient so its outbound
                             calls land on the in-process AI Engine app rather
                             than a real HTTP socket.
    - _reset_module_state  : autouse, function-scoped — wipes the in-memory
                             rate-limit / cache state between tests so the
                             session-scoped FastAPI apps don't leak across
                             tests.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Environment defaults — must be set BEFORE any backend.* import.
# ---------------------------------------------------------------------------
_TEST_ENV_DEFAULTS = {
    "LLM_MODE": "mock",
    "VECTOR_BACKEND": "memory",
    "EMBEDDING_BACKEND": "mock",
    "CACHE_BACKEND": "memory",
    # Distinct ports so a real local backend running on default ports is not
    # accidentally hit by an integration test.
    "GATEWAY_PORT": "18010",
    "AI_ENGINE_PORT": "18011",
    "GATEWAY_URL": "http://testserver-gateway",
    "AI_ENGINE_URL": "http://testserver-ai-engine",
    "JWT_SECRET": "test-secret-do-not-use-elsewhere-32bytes!!",
    # Security Chunk A — empty INTERNAL_TOKEN + LLM_MODE=mock = permit. The
    # patched_ai_engine fixture mounts the AI Engine in-process via
    # ASGITransport, so there's no realistic way to inject a header through
    # the gateway's httpx layer without a much larger refactor; the "empty
    # + mock" permit rule keeps the test suite hermetic while production
    # still requires a real token.
    "INTERNAL_TOKEN": "",
    # Security Chunk A — keep the demo-secret bypass disabled by default in
    # tests. Individual tests that exercise the bypass monkeypatch this on.
    "DEMO_LOGIN_SECRET": "",
}
# Per-session scratch dir for audit + masking SQLite DBs so the test run does
# not write into the developer's data/ tree (which would persist and grow
# between runs even though it is .gitignored).
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="patentmind-tests-"))
_TEST_ENV_DEFAULTS.setdefault("AUDIT_DB_PATH", str(_TEST_DATA_DIR / "audit.db"))
_TEST_ENV_DEFAULTS.setdefault("MAPPING_DB_PATH", str(_TEST_DATA_DIR / "mapping.db"))
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

# ---------------------------------------------------------------------------
# 2. Make the repo root importable so `import backend...` works even when
#    pytest is run from somewhere other than the project root.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# 2b. Redirect SQLite DB paths.
#
# `backend.shared.config` does NOT read AUDIT_DB_PATH / MAPPING_DB_PATH from
# the environment — they are module-level constants. The audit + masking
# modules then `from backend.shared.config import AUDIT_DB_PATH` (i.e. bind
# the name into their own namespace at import time) and the AuditWriter /
# MaskingStore singletons are instantiated at module top level with that
# default path. So the only way to redirect them per-session is to (a) import
# config first, (b) mutate the constants on it, and (c) let the backend
# modules import afterwards. The env vars above are kept for parity with the
# rest of the config surface and so any future config.py refactor that does
# read them will Just Work.
# ---------------------------------------------------------------------------
from backend.shared import config as _config_mod  # noqa: E402

_config_mod.AUDIT_DB_PATH = Path(os.environ["AUDIT_DB_PATH"])
_config_mod.MAPPING_DB_PATH = Path(os.environ["MAPPING_DB_PATH"])

import pytest  # noqa: E402  (must come after sys.path + env setup)
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# 3. App fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def gateway_app():
    from backend.gateway.main import app  # noqa: WPS433 (local import is intentional)
    return app


@pytest.fixture(scope="session")
def ai_engine_app():
    from backend.ai_engine.main import app  # noqa: WPS433
    return app


@pytest.fixture()
def gateway_client(gateway_app):
    with TestClient(gateway_app) as client:
        yield client


# ---------------------------------------------------------------------------
# 4. Auth fixture — log in as alice (attorney, tenant_a) and hand back JWT.
# ---------------------------------------------------------------------------
@pytest.fixture()
def alice_token(gateway_client) -> str:
    # Security Chunk A — /v1/auth/login now requires a credential. Default
    # demo password is `demo-{user_id}` (documented in .env.example).
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "demo-alice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "token" in body, body
    return body["token"]


# ---------------------------------------------------------------------------
# 5. Wire the gateway orchestrator's outbound httpx calls to the in-process
#    AI Engine app. The real orchestrator uses httpx.AsyncClient to POST to
#    `settings.AI_ENGINE_URL`; we replace that client with one that uses an
#    httpx.ASGITransport pointing at the AI Engine FastAPI app, so no socket
#    is opened and the integration test is hermetic.
# ---------------------------------------------------------------------------
@pytest.fixture()
def patched_ai_engine(monkeypatch, ai_engine_app):
    import httpx

    from backend.gateway import main as gw_main_mod
    from backend.gateway import orchestrator as orch_mod

    original_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        # Force every AsyncClient instantiated inside the gateway side of the
        # codebase (orchestrator + main upload endpoint) to talk to the
        # in-process AI Engine via ASGITransport.
        kwargs["transport"] = httpx.ASGITransport(app=ai_engine_app)
        kwargs.setdefault("base_url", "http://testserver-ai-engine")
        # setdefault — don't override a timeout the caller deliberately
        # chose. We only want to set a sane fallback when it didn't pass one.
        kwargs.setdefault("timeout", 30.0)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(orch_mod.httpx, "AsyncClient", _patched_async_client)
    monkeypatch.setattr(gw_main_mod.httpx, "AsyncClient", _patched_async_client)
    yield


# ---------------------------------------------------------------------------
# 6. Reset in-memory backend state between tests.
#
# `gateway_app` is session-scoped (fast: only one FastAPI startup) but the
# modules it pulls in (`rate_limit`, `cache`) hold module-level dicts that
# accumulate across tests. Without this teardown the first multi-test
# integration commit becomes the first flake — e.g. a test exercises the
# RPM limit and a later test inherits the depleted bucket. The fixture is
# autouse so tests don't have to opt in and the reset survives even if a
# test never touched these modules (imports are deferred + defensively
# wrapped so the fixture is a no-op when the modules aren't loaded).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_module_state():
    yield
    try:
        from backend.gateway import rate_limit as _rl
        # Names verified against backend/gateway/rate_limit.py.
        _rl._user_rpm.clear()
        _rl._user_daily_tokens.clear()
        _rl._tenant_monthly_tokens.clear()
        _rl._daily_cost_usd.clear()
        # Day 8 post-review: per-IP login bucket added (LOGIN_RPM, default
        # 10/min). Tests issue dozens of logins per session — must clear or
        # they trip the bucket and start returning 429s instead of 401s.
        if hasattr(_rl, "_login_ip_rpm"):
            _rl._login_ip_rpm.clear()
    except (ImportError, AttributeError):
        pass
    try:
        from backend.gateway import cache as _cache_mod
        # The cache module exposes a private `_MemoryCache` instance bound to
        # `_cache`; clearing its internal `_data` dict is the canonical reset.
        cache_obj = getattr(_cache_mod, "_cache", None)
        if cache_obj is not None and hasattr(cache_obj, "_data"):
            with cache_obj._lock:
                cache_obj._data.clear()
    except (ImportError, AttributeError):
        pass
