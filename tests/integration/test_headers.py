"""Integration tests for Security Chunk C — M-1 security response headers.

The gateway adds six baseline browser-defence headers on every response.
This module verifies each one is present, has the expected literal value
(where appropriate), and persists across success + error response paths.

Headers under test:
  * Strict-Transport-Security — HSTS, forces https on subsequent visits.
  * Content-Security-Policy   — declarative XSS / data-exfil bound.
  * X-Frame-Options           — clickjacking deny (paired with frame-ancestors).
  * X-Content-Type-Options    — refuse MIME sniffing.
  * Referrer-Policy           — bounds Referer leak on cross-origin nav.
  * Permissions-Policy        — disables sensor / payment APIs.

If a future refactor breaks one of these (e.g. someone removes the
middleware to "simplify") this module goes red. The header values
themselves are owned by ``backend/gateway/main.py`` constants — these
tests assert on the visible HTTP wire.
"""
from __future__ import annotations


# The six headers we set unconditionally. Names match the literal HTTP
# header (case-insensitive in HTTP/1.1, but starlette preserves the
# original case so we use the canonical capitalisation).
_REQUIRED_SECURITY_HEADERS = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)


def test_security_headers_present_on_health(gateway_client):
    """GET /v1/health is unauth + cheap — every browser reaches it during
    boot if the operator pings the URL. All six headers must be present.

    This is the canonical "fast smoke test" for the middleware — if any
    header is missing here, no other endpoint will have it either."""
    resp = gateway_client.get("/v1/health")
    assert resp.status_code == 200, resp.text
    for header in _REQUIRED_SECURITY_HEADERS:
        assert header in resp.headers, (
            f"missing {header!r} on /v1/health; got: {dict(resp.headers)}"
        )


def test_security_headers_present_on_4xx_response(gateway_client):
    """A 404 (unknown route) still goes through the middleware chain — so
    a clickjacking attack on a /typo URL is still blocked by X-Frame-Options.

    The pre-fix codepath added headers via a per-handler dependency would
    miss this; the post-fix `@app.middleware("http")` decorator runs on
    every response including error paths."""
    resp = gateway_client.get("/v1/does-not-exist-12345")
    assert resp.status_code == 404, resp.text
    for header in _REQUIRED_SECURITY_HEADERS:
        assert header in resp.headers, (
            f"missing {header!r} on 404 response; got: {dict(resp.headers)}"
        )


def test_csp_has_default_src_self(gateway_client):
    """CSP must include `default-src 'self'` — this is the catch-all that
    refuses arbitrary third-party loads when no more-specific directive
    matches. Without it CSP is effectively decorative."""
    resp = gateway_client.get("/v1/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp, (
        f"CSP missing `default-src 'self'`; got: {csp!r}"
    )
    # Also assert frame-ancestors 'none' — paired with X-Frame-Options for
    # browsers that support both. Without this, X-Frame-Options DENY alone
    # is bypassable in old Safari builds.
    assert "frame-ancestors 'none'" in csp, csp


def test_x_frame_options_deny(gateway_client):
    """X-Frame-Options must be the literal string `DENY` — `SAMEORIGIN`
    is the more common default but it admits framing from any subdomain,
    which the threat model (admin tricked into clicking overlay) doesn't
    tolerate."""
    resp = gateway_client.get("/v1/health")
    assert resp.headers.get("X-Frame-Options") == "DENY", (
        f"X-Frame-Options must be 'DENY'; got: "
        f"{resp.headers.get('X-Frame-Options')!r}"
    )


def test_x_content_type_options_nosniff(gateway_client):
    """X-Content-Type-Options must be 'nosniff' — refusing MIME-sniffing
    is the defence against an upload endpoint serving a .html file as
    text/plain and the browser deciding it's actually HTML."""
    resp = gateway_client.get("/v1/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff", (
        f"X-Content-Type-Options must be 'nosniff'; got: "
        f"{resp.headers.get('X-Content-Type-Options')!r}"
    )


def test_hsts_includes_subdomains(gateway_client):
    """HSTS must include `includeSubDomains` so a subdomain on http://
    cannot be used to dodge the https requirement. We omit `preload`
    intentionally (irrevocable browser-list commitment)."""
    resp = gateway_client.get("/v1/health")
    hsts = resp.headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts, hsts
    assert "includeSubDomains" in hsts, hsts
