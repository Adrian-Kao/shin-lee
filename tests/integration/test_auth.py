"""Integration tests for Security Chunk A — "Lock the front door".

Covers the four audit findings fixed by this chunk:

* **C-1** — `/v1/auth/login` used to mint a token for any `user_id` with no
  credential. Now requires either (a) a per-user password or (b) a matching
  `X-Demo-Secret` header (only when `DEMO_LOGIN_SECRET` is configured).
* **C-2** — AI Engine had zero per-endpoint auth. Now refuses every
  non-`/v1/health` request that lacks `X-Internal-Token` (with a mock-mode
  permit for hermetic pytest runs).
* **C-4** — JWT_SECRET placeholder guardrail used to only fire in non-mock
  mode. Now refuses the placeholder in ALL modes except pytest.
* **H-8** — login response previously differed (404 vs 200) between known
  and unknown users, leaking the user roster. Now always 401 on failure,
  regardless of which leg failed.

Test fixtures come from ``tests/conftest.py``. The conftest sets
``INTERNAL_TOKEN=""`` and ``DEMO_LOGIN_SECRET=""`` in the test environment
so the empty-token-permit and disabled-demo-secret paths are the default;
individual tests monkeypatch ``settings`` on the live module to flip them.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from backend.shared.config import settings

# ---------------------------------------------------------------------------
# C-1 / H-8 — /v1/auth/login credential checks
# ---------------------------------------------------------------------------


def test_login_rate_limited_per_ip(gateway_client, monkeypatch):
    """Day 8 post-review Important #1: login must be rate-limited per IP.

    Without this, sha256 + 16-byte salt is fast enough that an attacker
    reaching the gateway can brute-force `demo-{user_id}` passwords at
    hundreds of attempts/sec. The check_login_rpm() bucket caps this.

    We pin LOGIN_RPM=2 so the test runs in milliseconds, then issue 3
    login attempts back-to-back. The 3rd must 429 BEFORE password check
    (we send a wrong password to prove the gate fires regardless of
    credential correctness).
    """
    from backend.gateway import rate_limit as rl

    monkeypatch.setattr(settings, "LOGIN_RPM", 2)
    # Clear any leaked state from earlier tests in the same session.
    rl._login_ip_rpm.clear()

    body = {"user_id": "alice", "password": "wrong"}
    r1 = gateway_client.post("/v1/auth/login", json=body)
    r2 = gateway_client.post("/v1/auth/login", json=body)
    r3 = gateway_client.post("/v1/auth/login", json=body)

    # First two consume the bucket; both 401 (wrong password).
    assert r1.status_code == 401, r1.text
    assert r2.status_code == 401, r2.text
    # Third must 429 — rate-limited before the password check.
    assert r3.status_code == 429, r3.text
    assert "login attempts" in r3.text.lower(), r3.text


def test_login_rate_limit_fires_before_password_check(gateway_client, monkeypatch):
    """The 429 must arrive without any signal about whether the credential
    was correct or not. Otherwise the attacker can use the timing /
    response-shape difference as an oracle."""
    from backend.gateway import rate_limit as rl

    monkeypatch.setattr(settings, "LOGIN_RPM", 1)
    rl._login_ip_rpm.clear()

    # Exhaust the bucket with a wrong-password attempt.
    r1 = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "wrong"},
    )
    assert r1.status_code == 401, r1.text

    # Now try with the CORRECT password — must still 429, not 200.
    r2 = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "demo-alice"},
    )
    assert r2.status_code == 429, r2.text


# ---------------------------------------------------------------------------
# C-1 / H-8 — /v1/auth/login credential checks (original tests below)
# ---------------------------------------------------------------------------

def test_login_without_password_or_demo_secret_returns_401(gateway_client):
    """Body with only `user_id` (the old pre-Chunk-A shape) must now 401.

    Demo-secret env is unset in conftest, so the only path left is password
    — and there's no password in the body. Same 401 / "Invalid credentials"
    response as every other failure mode (H-8).
    """
    resp = gateway_client.post("/v1/auth/login", json={"user_id": "alice"})
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Invalid credentials"}


def test_login_with_correct_password_returns_token(gateway_client):
    """Default demo password is `demo-{user_id}` — documented in .env.example."""
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "demo-alice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == "alice"
    assert body["tenant_id"] == "tenant_a"
    assert body["role"] == "attorney"
    assert "token" in body and len(body["token"]) > 0


def test_login_with_wrong_password_returns_401_same_as_unknown_user(gateway_client):
    """H-8: unknown user and known-user-wrong-password must collapse to the
    SAME response — same status code, same body. Otherwise the response is a
    user-enumeration oracle ("status=401-A means user exists, status=401-B
    means user doesn't"). The previous behaviour was 404 vs 200 — even worse.
    """
    wrong_pw_known_user = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "definitely-wrong"},
    )
    unknown_user = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "nobody-by-this-name", "password": "anything"},
    )
    assert wrong_pw_known_user.status_code == 401, wrong_pw_known_user.text
    assert unknown_user.status_code == 401, unknown_user.text
    # Bytes-equal — if a future refactor adds a "code": "USER_NOT_FOUND"
    # field to one branch this test goes red.
    assert wrong_pw_known_user.json() == unknown_user.json()


def test_login_with_demo_secret_works_when_env_set(gateway_client, monkeypatch):
    """When `DEMO_LOGIN_SECRET` is set on the backend, the matching header
    is a sufficient credential — no password required. This is the "click
    Alice" path that lets stakeholder demos run without typing.
    """
    monkeypatch.setattr(settings, "DEMO_LOGIN_SECRET", "test-secret-abc123")
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice"},
        headers={"X-Demo-Secret": "test-secret-abc123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == "alice"


def test_login_with_demo_secret_unset_in_env_rejects_header(gateway_client):
    """Env unset (the conftest default) — the header MUST NOT authenticate,
    even if the attacker happens to supply the magic string `""`. Without
    this guard a deployment that forgot to set the env var would silently
    accept any X-Demo-Secret value.
    """
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice"},
        headers={"X-Demo-Secret": ""},
    )
    assert resp.status_code == 401, resp.text


def test_login_with_demo_secret_wrong_value_returns_401(gateway_client, monkeypatch):
    """Env set, header present, but value mismatched — still 401, same body
    as unknown user, so the demo-secret feature itself is not a probe oracle."""
    monkeypatch.setattr(settings, "DEMO_LOGIN_SECRET", "expected-secret")
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice"},
        headers={"X-Demo-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Invalid credentials"}


def test_login_with_demo_secret_unknown_user_still_401(gateway_client, monkeypatch):
    """The demo-secret bypass is a CREDENTIAL, not an identity selector.
    Supplying the matching header but a user_id that isn't in `_USERS` must
    still 401 — otherwise an attacker who learns the demo secret could mint
    tokens for `eve` / `mallory` / any synthetic identity.
    """
    monkeypatch.setattr(settings, "DEMO_LOGIN_SECRET", "test-secret-abc123")
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "nobody-by-this-name"},
        headers={"X-Demo-Secret": "test-secret-abc123"},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# C-2 — AI Engine internal-token middleware
# ---------------------------------------------------------------------------

@pytest.fixture()
def ai_engine_client(ai_engine_app):
    """Direct in-process TestClient against the AI Engine app. We need this
    rather than the shared `gateway_client` fixture because the AI Engine
    middleware is what's under test, and the gateway's httpx layer would
    obscure header propagation.
    """
    with TestClient(ai_engine_app) as client:
        yield client


def test_ai_engine_endpoint_without_internal_token_returns_401(
    ai_engine_client, monkeypatch
):
    """C-2: with INTERNAL_TOKEN configured, a request lacking
    X-Internal-Token must 401 — even in mock mode. The mock-mode "permit"
    rule only applies when the token is EMPTY (the local-dev case).
    """
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "real-token-from-env")
    resp = ai_engine_client.post(
        "/v1/parse_oa",
        json={
            "oa_text": "irrelevant",
            "tenant_id": "tenant_a",
            "case_id": "CASE-2025-001",
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Unauthorized"}


def test_ai_engine_endpoint_with_internal_token_works(
    ai_engine_client, monkeypatch
):
    """Sanity-check the happy path: token configured + header matches =>
    request reaches the handler. Without this, a future regression that
    broke the comparison logic would silently lock out the gateway entirely.
    """
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "real-token-from-env")
    resp = ai_engine_client.post(
        "/v1/parse_oa",
        json={
            "oa_text": "irrelevant",
            "tenant_id": "tenant_a",
            "case_id": "CASE-2025-001",
            "target_patent_no": "US-1234567",
        },
        headers={"X-Internal-Token": "real-token-from-env"},
    )
    assert resp.status_code == 200, resp.text


def test_ai_engine_health_endpoint_works_without_token(ai_engine_client, monkeypatch):
    """`/v1/health` is the only exempt path so k8s liveness probes can run
    without provisioning the token in the probe config. The middleware
    skips the auth check before reading any header.
    """
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "real-token-from-env")
    resp = ai_engine_client.get("/v1/health")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_ai_engine_mock_mode_empty_token_permits(ai_engine_client, monkeypatch):
    """Documented permit: empty INTERNAL_TOKEN + LLM_MODE=mock = allow.
    This is the pytest path (the conftest sets the env to empty + mock)
    and the local-dev path (`bash scripts/start_demo.sh` without a token).
    """
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "")
    monkeypatch.setattr(settings, "LLM_MODE", "mock")
    resp = ai_engine_client.post(
        "/v1/parse_oa",
        json={
            "oa_text": "irrelevant",
            "tenant_id": "tenant_a",
            "case_id": "CASE-2025-001",
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# C-4 — JWT_SECRET placeholder boot guardrail
# ---------------------------------------------------------------------------

def test_jwt_secret_placeholder_refuses_boot(tmp_path):
    """Importing `backend.shared.config` with the published placeholder in
    JWT_SECRET and NO PYTEST_CURRENT_TEST in the env must raise RuntimeError.

    Run in a subprocess because the guard fires at module-import time and
    the current test process has its own (non-placeholder) JWT_SECRET set
    in conftest. The subprocess gets a stripped env so we can prove the
    guard fires in the demo deployment shape (mock mode, no test harness).
    """
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    script = textwrap.dedent(
        """
        import sys
        try:
            import backend.shared.config  # noqa: F401
        except RuntimeError as exc:
            sys.stdout.write(f"GUARD_FIRED: {exc}")
            sys.exit(0)
        sys.stdout.write("NO_GUARD")
        sys.exit(1)
        """
    )
    env = {
        # Only the bare minimum to import — explicitly NO PYTEST_CURRENT_TEST.
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows DLL search
        "LLM_MODE": "mock",  # the demo deployment shape — was the C-4 hole
        "JWT_SECRET": "changeme-generate-with-openssl-rand-hex-32",
        "PYTHONPATH": repo_root,
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        # The child writes UTF-8 (PYTHONIOENCODING above); decode the pipes as
        # UTF-8 too — `text=True` alone uses the locale codec (cp950 on a
        # zh-TW Windows host), which chokes on the em-dash in the guard message.
        encoding="utf-8",
        cwd=repo_root,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"expected guard to fire; got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert proc.stdout.startswith("GUARD_FIRED:"), proc.stdout
    # The error message must mention openssl so an operator who hits this
    # knows exactly how to fix it.
    assert "openssl rand -hex 32" in proc.stdout, proc.stdout
