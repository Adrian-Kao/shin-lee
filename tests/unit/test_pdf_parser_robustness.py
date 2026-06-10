"""Unit tests for pdf_parser ingestion robustness (Q8 — Day 13J).

These exercise `extract_pdf_text` / `extract_docx_text` DIRECTLY (not through
the gateway) so every ingestion edge case has a focused, fast, hermetic test:

  - born-digital text-layer extraction (no OCR)
  - scanned (image-only) page → OCR fallback
  - mixed text + scan document, with deterministic page ordering
  - parallel OCR result ordering is deterministic regardless of completion order
  - rejection of: empty bytes, non-PDF-masquerading-as-PDF, encrypted PDF,
    zero-page PDF, over-the-hard-page-cap PDF
  - per-call max_pages truncation-with-warning
  - per-page quality signals + low-text (bad-scan) flagging
  - scanned-document ratio warning
  - figure-region stub returns [] and refuses the cloud path for confidential

All OCR is stubbed via monkeypatch on `_ocr_page`, so NO tesseract / Vision
binary is required — the suite stays hermetic. The MockLLM OCR path is the
default backend; we only swap it where we need to control the returned text.
"""
from __future__ import annotations

import asyncio
import io

import pytest

from backend.ai_engine import pdf_parser
from backend.shared.config import settings


# ---------------------------------------------------------------------------
# PDF fixture builders (tiny, in-memory, via PyMuPDF — no committed binaries)
# ---------------------------------------------------------------------------


def _text_pdf(*pages: str) -> bytes:
    import fitz

    doc = fitz.open()
    for body in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), body, fontsize=12)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _image_only_page(doc) -> None:
    """Append one image-only page (empty text layer → forces OCR fallback)."""
    import fitz

    page = doc.new_page(width=300, height=300)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80))
    pix.clear_with(220)
    page.insert_image(fitz.Rect(0, 0, 80, 80), pixmap=pix)


def _scanned_pdf(n_pages: int = 1) -> bytes:
    import fitz

    doc = fitz.open()
    for _ in range(n_pages):
        _image_only_page(doc)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _mixed_pdf() -> bytes:
    """page 0 = text, page 1 = image-only (scan), page 2 = text."""
    import fitz

    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text(
        (72, 100), "BORN DIGITAL PAGE ZERO claim 1 of US12345678.", fontsize=12
    )
    _image_only_page(doc)
    doc.new_page(width=595, height=842).insert_text(
        (72, 100), "BORN DIGITAL PAGE TWO referencing TW202131234.", fontsize=12
    )
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _encrypted_pdf() -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "secret", fontsize=12)
    out = io.BytesIO()
    doc.save(
        out,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    doc.close()
    return out.getvalue()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Born-digital extraction (no OCR)
# ---------------------------------------------------------------------------


def test_born_digital_pdf_uses_text_layer_not_ocr(monkeypatch):
    called = {"ocr": 0}

    async def _no_ocr(png, *, security_level):  # should never fire
        called["ocr"] += 1
        return "SHOULD-NOT-HAPPEN", pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _no_ocr)

    pdf = _text_pdf("Born digital page one with plenty of real text here.")
    res = _run(pdf_parser.extract_pdf_text(pdf))

    assert called["ocr"] == 0
    assert res["page_count"] == 1
    assert res["ocr_pages"] == []
    assert "Born digital page one" in res["pages"][0]
    assert res["usage"]["estimated_cost_usd"] == 0.0
    # Quality: a text-layer page is full confidence and never low-text.
    assert res["page_quality"][0]["source"] == "text"
    assert res["page_quality"][0]["confidence"] == 1.0
    assert res["page_quality"][0]["low_text"] is False
    assert res["low_text_pages"] == []


# ---------------------------------------------------------------------------
# Scanned page → OCR fallback
# ---------------------------------------------------------------------------


def test_scanned_page_falls_back_to_ocr(monkeypatch):
    async def _ocr(png, *, security_level):
        return "OCR-TEXT-FROM-SCANNED-PAGE with claim 1 detail", pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)

    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(1)))

    assert res["ocr_pages"] == [0]
    assert "OCR-TEXT-FROM-SCANNED-PAGE" in res["pages"][0]
    assert res["page_quality"][0]["source"] == "ocr"
    # Non-empty OCR → confidence between 0 and the 0.95 ceiling, not low-text.
    assert 0.0 < res["page_quality"][0]["confidence"] <= 0.95
    assert res["page_quality"][0]["low_text"] is False


def test_blank_scan_flagged_low_text(monkeypatch):
    """An OCR page that comes back (near) empty is a bad/blank scan: flagged
    low_text + listed in low_text_pages + a document warning, but NOT an error."""

    async def _ocr(png, *, security_level):
        return "", pdf_parser._zero_usage()  # blank scan

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)

    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(1)))

    assert res["ocr_pages"] == [0]
    assert res["page_quality"][0]["low_text"] is True
    assert res["page_quality"][0]["confidence"] == 0.0
    assert res["low_text_pages"] == [0]
    assert any("low-text" in w for w in res["warnings"])


# ---------------------------------------------------------------------------
# Mixed text + scan document
# ---------------------------------------------------------------------------


def test_mixed_document_text_and_scan(monkeypatch):
    async def _ocr(png, *, security_level):
        return "OCR-PAGE-ONE scanned middle page", pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)

    res = _run(pdf_parser.extract_pdf_text(_mixed_pdf()))

    assert res["page_count"] == 3
    # Only the middle (image-only) page is OCR'd.
    assert res["ocr_pages"] == [1]
    assert "BORN DIGITAL PAGE ZERO" in res["pages"][0]
    assert "OCR-PAGE-ONE" in res["pages"][1]
    assert "BORN DIGITAL PAGE TWO" in res["pages"][2]
    # Per-page sources reflect the mix in order.
    assert [q["source"] for q in res["page_quality"]] == ["text", "ocr", "text"]


# ---------------------------------------------------------------------------
# Parallel OCR — deterministic page ordering regardless of completion order
# ---------------------------------------------------------------------------


def test_parallel_ocr_preserves_page_order(monkeypatch):
    """Five scanned pages whose OCR completes out of order must still land in
    page order. We make later pages resolve FIRST (longer sleep for earlier
    pages) and assert the output is still ordered 0..4."""
    monkeypatch.setattr(settings, "OCR_PARALLELISM", 5)

    # Encode the page identity in the rendered PNG so the stub knows which page
    # it is. We round-trip via a side channel: distinct page sizes per index.
    # Simpler: stub _ocr_page to label by call order is not deterministic, so
    # instead we vary by png length which differs per page render. Because that
    # is fragile, we patch the lower-level _ocr_one inputs by using a counter
    # keyed on the png bytes object identity is unavailable; use a delay scheme.
    order_seen: list[int] = []

    # Build a scanned PDF whose pages carry tiny embedded numeral images so the
    # OCR stub can map png→index by size. Easiest robust approach: monkeypatch
    # the gather to feed indices. Instead we exploit that _ocr_page receives the
    # png for a specific page and we return text derived from a per-call latency
    # that inverts ordering.
    call_idx = {"n": 0}

    async def _ocr(png, *, security_level):
        i = call_idx["n"]
        call_idx["n"] += 1
        # Earlier-dispatched pages sleep longer so they finish LAST — this
        # guarantees completion order != dispatch order.
        await asyncio.sleep((5 - i) * 0.002)
        order_seen.append(i)
        return f"PAGE-{i}", pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)

    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(5)))

    # Dispatch order is 0..4 (sequential gather construction), so call_idx maps
    # 1:1 to page index. Completion order is reversed by the sleeps...
    assert order_seen == sorted(order_seen, reverse=True), order_seen
    # ...yet the assembled pages are still in correct page order.
    assert res["ocr_pages"] == [0, 1, 2, 3, 4]
    assert [p for p in res["pages"]] == [f"PAGE-{i}" for i in range(5)]


def test_ocr_parallelism_respects_bounded_workers(monkeypatch):
    """With OCR_PARALLELISM=2 over 6 pages, no more than 2 OCR calls run
    concurrently."""
    monkeypatch.setattr(settings, "OCR_PARALLELISM", 2)
    state = {"cur": 0, "max": 0}

    async def _ocr(png, *, security_level):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0.005)
        state["cur"] -= 1
        return "x" * 50, pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)

    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(6)))
    assert res["ocr_pages"] == [0, 1, 2, 3, 4, 5]
    assert state["max"] <= 2, state


# ---------------------------------------------------------------------------
# Rejection / error cases — each a clear, testable error (never a crash)
# ---------------------------------------------------------------------------


def test_empty_bytes_rejected():
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_pdf_text(b""))


def test_non_pdf_masquerading_as_pdf_rejected():
    """Bytes with a %PDF- header but garbage body must raise ValueError, not
    crash or return an empty result."""
    fake = b"%PDF-1.4\nthis is not actually a pdf body at all\n%%EOF"
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_pdf_text(fake))


def test_random_garbage_rejected():
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_pdf_text(b"\x00\x01\x02not a pdf\xff\xfe"))


def test_encrypted_pdf_rejected_with_permission_error():
    with pytest.raises(PermissionError) as ei:
        _run(pdf_parser.extract_pdf_text(_encrypted_pdf()))
    assert "password" in str(ei.value).lower() or "decrypt" in str(ei.value).lower()


def test_zero_page_pdf_rejected(monkeypatch):
    """A structurally-openable but zero-page document must raise ValueError —
    never return a silent empty extraction. PyMuPDF won't *save* a zero-page
    PDF, so we simulate one by stubbing fitz.open to yield a 0-page doc."""

    class _FakeDoc:
        needs_pass = False
        page_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pdf_parser.fitz, "open", lambda *a, **k: _FakeDoc())

    with pytest.raises(ValueError) as ei:
        _run(pdf_parser.extract_pdf_text(b"%PDF-1.4 anything"))
    assert "zero pages" in str(ei.value).lower()


def test_over_hard_page_cap_rejected(monkeypatch):
    """A document declaring more than MAX_PDF_PAGES pages is refused outright
    (malformed/hostile), independent of the per-call max_pages truncation."""

    class _FakeDoc:
        needs_pass = False
        page_count = 10_000

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 2000)
    monkeypatch.setattr(pdf_parser.fitz, "open", lambda *a, **k: _FakeDoc())

    with pytest.raises(ValueError) as ei:
        _run(pdf_parser.extract_pdf_text(b"%PDF-1.4 anything", max_pages=100000))
    assert "MAX_PDF_PAGES" in str(ei.value) or "hard cap" in str(ei.value)


def test_max_pages_truncation_warns_not_errors():
    """Per-call max_pages cap truncates with a warning (not an error) for a
    normal-sized large doc."""
    pdf = _text_pdf("p1 text body here", "p2 text body here", "p3 text body here")
    res = _run(pdf_parser.extract_pdf_text(pdf, max_pages=2))
    assert res["page_count"] == 2
    assert any("truncated" in w for w in res["warnings"])


# ---------------------------------------------------------------------------
# OCR page failure surfaces as RuntimeError (no silent blank page)
# ---------------------------------------------------------------------------


def test_ocr_failure_surfaces_runtime_error(monkeypatch):
    async def _boom(png, *, security_level):
        raise RuntimeError("vision backend exploded")

    monkeypatch.setattr(pdf_parser, "_ocr_page", _boom)

    with pytest.raises(RuntimeError):
        _run(pdf_parser.extract_pdf_text(_scanned_pdf(1)))


# ---------------------------------------------------------------------------
# Document-level scanned-doc ratio warning
# ---------------------------------------------------------------------------


def test_scanned_doc_ratio_warning(monkeypatch):
    async def _ocr(png, *, security_level):
        return "x" * 50, pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser, "_ocr_page", _ocr)
    monkeypatch.setattr(settings, "OCR_SCANNED_DOC_WARN_RATIO", 0.5)

    # All-scanned 3-page doc → ratio 1.0 ≥ 0.5 → warning.
    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(3)))
    assert any("likely a scan" in w for w in res["warnings"]), res["warnings"]


# ---------------------------------------------------------------------------
# Confidential routing — never cloud (parser-level entry guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["confidential", "top_secret"])
def test_confidential_pdf_refused_when_backend_not_tesseract(monkeypatch, level):
    """extract_pdf_text validates the OCR backend UP FRONT for a confidential
    doc — even a fully born-digital one — so a misconfigured deployment can
    never process a privileged doc on a cloud-capable backend."""
    monkeypatch.setattr(settings, "OCR_BACKEND", "vision")
    pdf = _text_pdf("born digital but the case is confidential")
    with pytest.raises(RuntimeError) as ei:
        _run(pdf_parser.extract_pdf_text(pdf, security_level=level))
    assert "tesseract" in str(ei.value)


@pytest.mark.parametrize("level", ["confidential", "top_secret"])
def test_confidential_scanned_pdf_routes_local_only(monkeypatch, level):
    """A confidential SCANNED doc with OCR_BACKEND=tesseract routes through the
    on-prem path only; the cloud vision_ocr is never called."""
    monkeypatch.setattr(settings, "OCR_BACKEND", "tesseract")

    cloud = {"n": 0}

    async def _spy_vision(*, image_bytes, mime="image/png", security_level="public"):
        cloud["n"] += 1
        return "CLOUD", pdf_parser._zero_usage()

    async def _spy_local(*, image_bytes, mime="image/png", lang=None):
        return "LOCAL-OCR", pdf_parser._zero_usage()

    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _spy_vision)
    monkeypatch.setattr(pdf_parser.ocr_local, "ocr_image", _spy_local)

    res = _run(pdf_parser.extract_pdf_text(_scanned_pdf(1), security_level=level))
    assert cloud["n"] == 0
    assert res["pages"][0] == "LOCAL-OCR"


# ---------------------------------------------------------------------------
# DOCX path quality signals
# ---------------------------------------------------------------------------


def test_docx_quality_signals_all_text():
    from docx import Document

    doc = Document()
    doc.add_paragraph("First paragraph with content.")
    doc.add_paragraph("Second paragraph with more content.")
    buf = io.BytesIO()
    doc.save(buf)

    res = _run(pdf_parser.extract_docx_text(buf.getvalue()))
    assert res["page_count"] == 2
    assert res["ocr_pages"] == []
    assert all(q["source"] == "text" for q in res["page_quality"])
    assert all(q["confidence"] == 1.0 for q in res["page_quality"])
    assert res["low_text_pages"] == []


def test_docx_empty_bytes_rejected():
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_docx_text(b""))


# ---------------------------------------------------------------------------
# Figure-region stub (future Claude-Vision) — returns [], routing-guarded
# ---------------------------------------------------------------------------


def test_figure_regions_stub_returns_empty():
    res = _run(
        pdf_parser.extract_figure_regions(_text_pdf("anything"), 0, security_level="public")
    )
    assert res == []


@pytest.mark.parametrize("level", ["confidential", "top_secret"])
def test_figure_regions_confidential_refuses_cloud(monkeypatch, level):
    monkeypatch.setattr(settings, "OCR_BACKEND", "vision")
    with pytest.raises(RuntimeError) as ei:
        _run(
            pdf_parser.extract_figure_regions(
                _text_pdf("x"), 0, security_level=level
            )
        )
    assert "invariant #7" in str(ei.value) or "forbidden" in str(ei.value)


def test_figure_regions_confidential_ok_on_tesseract(monkeypatch):
    monkeypatch.setattr(settings, "OCR_BACKEND", "tesseract")
    res = _run(
        pdf_parser.extract_figure_regions(
            _text_pdf("x"), 0, security_level="confidential"
        )
    )
    assert res == []
