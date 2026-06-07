"""Integration tests for POST /v1/oa/upload (Day 2).

Covers all six gateway-side outcomes:
  1. Text-only PDF → 200, extracted text matches synthesised content.
  2. DOCX → 200, paragraphs round-trip through the page-break separator.
  3. Oversize body → 413 (override MAX_UPLOAD_MB via monkeypatch for speed).
  4. Wrong content type → 415.
  5. No Authorization header → 401.
  6. Confidential case id → 403 with the policy message.

All tests use the patched_ai_engine fixture which reroutes both the gateway
orchestrator AND the gateway upload endpoint's outbound httpx calls onto the
in-process AI Engine app. No socket is opened; LLM_MODE=mock means the OCR
fallback returns the deterministic MockLLM placeholder.
"""
from __future__ import annotations

import io

# ---------- helpers ---------------------------------------------------------


def _make_text_pdf(*pages: str) -> bytes:
    """Build a small PDF in memory using PyMuPDF.

    Each `pages` arg becomes one PDF page with the text inserted near the top.
    Keeping the helper here (rather than as a shared fixture) makes the test
    bodies self-contained and easy to read.
    """
    import fitz

    doc = fitz.open()
    for body in pages:
        page = doc.new_page(width=595, height=842)  # A4 in points
        page.insert_text((72, 100), body, fontsize=12)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _make_docx(*paragraphs: str) -> bytes:
    """Build a minimal DOCX in memory using python-docx."""
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


_PDF_MIME = "application/pdf"
_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


# ---------- tests -----------------------------------------------------------


def test_upload_text_only_pdf_extracts_correctly(
    gateway_client, alice_token, patched_ai_engine
):
    pdf_bytes = _make_text_pdf(
        "Page one body talking about claim 1 of US12345678.",
        "Page two body referencing prior art TW202131234.",
    )
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-001",
        },
        files={"file": ("sample.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2, body
    # No OCR fallback because PyMuPDF extracted enough text per page.
    assert body["ocr_pages_used"] == [], body
    assert "claim 1 of US12345678" in body["extracted_text"], body
    assert "TW202131234" in body["extracted_text"], body
    # Page-break separator survives the join.
    assert "--- page break ---" in body["extracted_text"], body
    assert body["cost_meta"]["estimated_cost_usd"] == 0.0


def test_upload_docx_extracts_correctly(
    gateway_client, alice_token, patched_ai_engine
):
    docx_bytes = _make_docx(
        "First paragraph of the answer brief.",
        "Second paragraph discussing claim 1.",
        "Third paragraph citing TW202131234.",
    )
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-001",
        },
        files={"file": ("brief.docx", docx_bytes, _DOCX_MIME)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 3, body
    assert body["ocr_pages_used"] == []
    text = body["extracted_text"]
    assert "First paragraph" in text
    assert "Second paragraph" in text
    assert "TW202131234" in text


def test_upload_oversize_returns_413(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    # Force the limit down to 1 MB so the test doesn't need to allocate 30+ MB.
    from backend.shared import config as cfg

    monkeypatch.setattr(cfg.settings, "MAX_UPLOAD_MB", 1)

    # A 2 MB blob is well over the 1 MB cap.
    big_bytes = b"%PDF-1.4\n" + (b"A" * (2 * 1024 * 1024))
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-001",
        },
        files={"file": ("big.pdf", big_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 413, resp.text
    assert "exceeds limit" in resp.text or "exceeds" in resp.text


def test_upload_wrong_content_type_returns_415(
    gateway_client, alice_token, patched_ai_engine
):
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-001",
        },
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 415, resp.text
    assert "unsupported" in resp.text.lower()


def test_upload_missing_auth_returns_401(gateway_client, patched_ai_engine):
    pdf_bytes = _make_text_pdf("nothing important")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={"X-Case-Id": "CASE-2025-001"},
        files={"file": ("x.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 401, resp.text


def test_upload_confidential_case_returns_403(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    # The default ACL doesn't list a -CONF case for alice; grant access just
    # for this test so we exercise the *upload-level* confidential block
    # rather than the ACL block (they would otherwise mask each other).
    from backend.gateway import auth as auth_mod

    monkeypatch.setitem(
        auth_mod._CASE_ACL, "alice",
        auth_mod._CASE_ACL["alice"] | {"CASE-2025-009-CONF"},
    )

    pdf_bytes = _make_text_pdf("confidential page content")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": "CASE-2025-009-CONF",
        },
        files={"file": ("conf.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 403, resp.text
    assert "Confidential" in resp.text or "confidential" in resp.text
    assert "cloud OCR" in resp.text or "manual text" in resp.text
