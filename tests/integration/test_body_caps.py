"""Integration tests for Security Chunk C — H-2 body-size + field caps.

Two distinct enforcement layers:

1. ``max_body_size_middleware`` reads ``Content-Length`` BEFORE any body
   bytes are parsed and 413s anything over ``settings.MAX_BODY_BYTES``
   (default 100MB). This protects memory — a 1GB JSON POST is rejected
   without ever being buffered.

2. ``Field(..., max_length=N)`` on each Pydantic schema rejects bodies
   that fit under the byte cap but contain a per-field string above the
   sensible upper bound. This protects downstream consumers (audit hash
   chain, LLM tokeniser, cache key hasher) that walk the parsed dict.

Both layers are necessary: the middleware can't see inside the body so
it'd let a 4MB JSON with a single oversized string through; the Pydantic
caps can't help if the body is too big to buffer in the first place.

We test the boundaries explicitly so a future "let's bump the cap" only
breaks these tests (and not in surprising downstream ways).
"""
from __future__ import annotations

from backend.shared import config as cfg

_ALICE_CASE = "CASE-2025-001"


# ---------------------------------------------------------------------------
# 1. Middleware-layer cap (Content-Length header check, BEFORE Pydantic)
# ---------------------------------------------------------------------------
def test_analyze_oversize_body_returns_413_via_middleware(
    gateway_client, alice_token, monkeypatch
):
    """Pin MAX_BODY_BYTES to a tiny value (4KB) so we can drive the
    middleware without uploading actual megabytes. A request whose
    Content-Length exceeds the cap must 413 BEFORE Pydantic gets a chance
    to inspect the body.

    Sanity assertion: the response carries the security headers from the
    M-1 middleware too, proving the middleware chain ordering is correct
    (security headers wrap the body-size check, not the other way around)."""
    monkeypatch.setattr(cfg.settings, "MAX_BODY_BYTES", 4 * 1024)

    # 8 KB body > 4 KB cap. We build a deliberately large oa_text just to
    # push Content-Length above the cap; the inner JSON shape doesn't
    # matter because the middleware short-circuits before Pydantic runs.
    big_text = "x" * (8 * 1024)
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": big_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 413, resp.text
    # Security headers must persist on 4xx responses (paired test in
    # test_headers.py — repeat the assertion here so a regression in
    # middleware ordering surfaces in two places).
    assert "X-Frame-Options" in resp.headers, dict(resp.headers)


def test_health_get_with_no_body_is_unaffected_by_cap(
    gateway_client, monkeypatch
):
    """GET requests have no body, so Content-Length is absent or zero.
    The middleware must NOT trip the 413 just because the cap is set
    low — otherwise every health probe breaks under a tight cap."""
    monkeypatch.setattr(cfg.settings, "MAX_BODY_BYTES", 1)  # absurdly low
    resp = gateway_client.get("/v1/health")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 2. Pydantic-layer cap (per-field max_length)
# ---------------------------------------------------------------------------
def test_analyze_oversize_oa_text_returns_422_via_pydantic(
    gateway_client, alice_token, patched_ai_engine
):
    """Body fits under MAX_BODY_BYTES (default 100MB), but oa_text exceeds
    the 5MB per-field cap. Pydantic must 422 — NOT 413, because the
    middleware sees the body fits the byte cap. This proves the two
    enforcement layers compose correctly: middleware can't reach inside
    so the per-field cap is the real defence against "small JSON, huge
    string" abuse.

    We stay just over the 5MB cap to keep the test fast (still ~5MB of
    request body in memory but well under the GC threshold)."""
    # 5MB + 1 char. The per-field cap is `_MAX_OA_TEXT_CHARS = 5 * 1024 * 1024`.
    oa_text = "x" * (5 * 1024 * 1024 + 1)
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": oa_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = str(resp.json()).lower()
    # Pydantic v2 error message mentions either "string_too_long" or
    # the constrained field name; one or the other is enough.
    assert "string_too_long" in detail or "oa_text" in detail, resp.text


def test_login_oversize_password_returns_422(gateway_client):
    """LoginRequest.password is capped at 256 chars — any IdP-issued
    credential will be far shorter. A multi-MB password attempt must
    422 before the timing-equalisation `_verify_password` call so a
    pathological client can't DoS the login endpoint with sha256 work."""
    resp = gateway_client.post(
        "/v1/auth/login",
        json={"user_id": "alice", "password": "x" * 1024},
    )
    assert resp.status_code == 422, resp.text


def test_login_extra_fields_rejected(gateway_client):
    """LoginRequest sets extra=forbid — a body containing unexpected
    fields (a future client typo, or an attacker probing for accepted
    fields) must 422 rather than be silently dropped. Without this an
    accidental `"role": "auditor"` in the body would be ignored without
    feedback, which is exactly the kind of silent failure that turns
    into a security finding later."""
    resp = gateway_client.post(
        "/v1/auth/login",
        json={
            "user_id": "alice",
            "password": "demo-alice",
            "role": "auditor",  # extra field — forbid
        },
    )
    assert resp.status_code == 422, resp.text


def test_analyze_extra_fields_rejected(gateway_client, alice_token):
    """AnalysisRequest sets extra=forbid — extra fields in the body must
    422 (not be silently dropped). Belt-and-braces against H-2-style
    smuggling where a future field-rename leaves the old name accepted."""
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": "any",
            "case_id": _ALICE_CASE,
            "target_patent_no": "US-1234567",
            "force_security_level": "public",   # extra — must 422
        },
    )
    assert resp.status_code == 422, resp.text
