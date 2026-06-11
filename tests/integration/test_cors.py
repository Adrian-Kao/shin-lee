"""Integration tests for Security Chunk C — H-1 CORS hardening.

Pre-fix CORS allowed `*` methods + `*` headers from a localhost origin.
Localhost was tight but the wildcards would propagate to production.

Post-fix:
  * Origin: env-driven ``CORS_ALLOWED_ORIGINS`` (default
    ``http://localhost:5173``).
  * Methods: explicit ``["GET","POST","PUT","DELETE","OPTIONS"]``.
  * Headers: explicit ``["Authorization","Content-Type","X-Case-Id",
    "X-Demo-Secret"]``.
  * ``allow_credentials=True``, ``max_age=600``.

Starlette's ``CORSMiddleware`` only echoes back the
``Access-Control-Allow-Origin`` header when the request's ``Origin``
header is in the allow-list — that's what we test below.
"""

from __future__ import annotations


def test_cors_allowed_origin_returns_acao_header(gateway_client):
    """A simple GET with the configured Origin must get the matching
    ACAO echoed back. Without this the SPA's fetch() calls fail with a
    CORS error in the browser."""
    resp = gateway_client.get(
        "/v1/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200, resp.text
    acao = resp.headers.get("access-control-allow-origin")
    assert acao == "http://localhost:5173", (
        f"expected ACAO=http://localhost:5173; got {acao!r}; headers={dict(resp.headers)}"
    )


def test_cors_disallowed_origin_omits_acao(gateway_client):
    """An Origin that's NOT in the allow-list must NOT receive an ACAO
    header — Starlette's CORSMiddleware silently omits it, and the
    browser then blocks the response on its own. We assert the omission
    directly rather than expecting a 403 (the middleware does NOT 403)."""
    resp = gateway_client.get(
        "/v1/health",
        headers={"Origin": "https://evil.example.com"},
    )
    # Health endpoint always 200s; CORS just doesn't echo the header.
    assert resp.status_code == 200, resp.text
    acao = resp.headers.get("access-control-allow-origin")
    assert acao is None or acao == "", f"disallowed origin should not get ACAO; got: {acao!r}"


def test_cors_preflight_options_returns_specific_methods(gateway_client):
    """Preflight OPTIONS with an allowed Origin + ACRM (Access-Control-
    Request-Method) must echo back the specific methods we configured —
    NOT the pre-fix `*` wildcard. Asserting on the literal value catches
    a future "let's just put * back" regression."""
    resp = gateway_client.options(
        "/v1/oa/analyze",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, X-Case-Id",
        },
    )
    # Preflight is 200 (per Starlette default) — the body is empty but
    # the headers carry the negotiation result.
    assert resp.status_code == 200, resp.text
    acam = resp.headers.get("access-control-allow-methods", "")
    # We configured exactly these five methods. Order is implementation-
    # defined so assert membership, not equality.
    for expected in ("GET", "POST", "PUT", "DELETE", "OPTIONS"):
        assert expected in acam, f"missing {expected!r} in {acam!r}"
    # Critically: NOT the wildcard. If a future refactor reintroduces
    # `allow_methods=["*"]` this assertion goes red.
    assert "*" not in acam, f"CORS methods must NOT include wildcard; got: {acam!r}"


def test_cors_preflight_does_not_allow_wildcard_headers(gateway_client):
    """Same as the methods test but for allow-headers. The pre-fix
    `allow_headers=["*"]` was the riskier of the two wildcards because
    a future cookie-based auth scheme could silently enable cross-origin
    credentialed reads of arbitrary headers."""
    resp = gateway_client.options(
        "/v1/oa/analyze",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, X-Case-Id",
        },
    )
    assert resp.status_code == 200, resp.text
    acah = resp.headers.get("access-control-allow-headers", "")
    # The configured list contains Authorization + X-Case-Id; assert
    # both are present. NOT wildcard.
    assert "authorization" in acah.lower(), acah
    assert "x-case-id" in acah.lower(), acah
    assert "*" not in acah, f"CORS headers must NOT include wildcard; got: {acah!r}"
