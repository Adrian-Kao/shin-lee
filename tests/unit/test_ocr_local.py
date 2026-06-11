"""Unit tests for the on-prem OCR backend + the pdf_parser OCR dispatch.

Two concerns are covered here:

1. **Routing logic** (no tesseract binary needed) — `_resolve_ocr_backend`
   and `_ocr_page` pick the right backend, and confidential docs are FORCED
   onto the on-prem tesseract path (invariant #7 / Q15). Cloud/mock backends
   are spied via monkeypatch.

2. **Live Tesseract OCR** — `@pytest.mark.skipif` when pytesseract / the
   tesseract binary is unavailable (mirrors the Qdrant-reachable skip in
   tests/unit/test_vector_store_contract.py). Skips cleanly in CI where the
   engine is absent.
"""

from __future__ import annotations

import asyncio
import io

import pytest

from backend.ai_engine import ocr_local, pdf_parser
from backend.shared.config import settings

# ---------------------------------------------------------------------------
# 1. OCR backend dispatch / confidential forcing (no tesseract needed)
# ---------------------------------------------------------------------------


def test_resolve_backend_public_passes_through(monkeypatch):
    for backend in ("mock", "vision", "tesseract"):
        monkeypatch.setattr(settings, "OCR_BACKEND", backend)
        assert pdf_parser._resolve_ocr_backend("public") == backend


@pytest.mark.parametrize("level", ["confidential", "top_secret"])
def test_resolve_backend_confidential_requires_tesseract(monkeypatch, level):
    # Anything other than tesseract for a confidential doc must raise — never
    # silently fall back to cloud/mock OCR.
    for bad in ("mock", "vision"):
        monkeypatch.setattr(settings, "OCR_BACKEND", bad)
        with pytest.raises(RuntimeError) as ei:
            pdf_parser._resolve_ocr_backend(level)
        assert "tesseract" in str(ei.value)
        assert "invariant #7" in str(ei.value) or "Q15" in str(ei.value)

    # tesseract is the one allowed backend for confidential.
    monkeypatch.setattr(settings, "OCR_BACKEND", "tesseract")
    assert pdf_parser._resolve_ocr_backend(level) == "tesseract"


def test_ocr_page_dispatches_to_tesseract(monkeypatch):
    calls = {"local": 0, "vision": 0}

    async def _spy_local(*, image_bytes, mime="image/png", lang=None):
        calls["local"] += 1
        return "LOCAL", pdf_parser._zero_usage()

    async def _spy_vision(*, image_bytes, mime="image/png", security_level="public"):
        calls["vision"] += 1
        return "VISION", pdf_parser._zero_usage()

    monkeypatch.setattr(settings, "OCR_BACKEND", "tesseract")
    monkeypatch.setattr(ocr_local, "ocr_image", _spy_local)
    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _spy_vision)

    text, _usage = asyncio.run(pdf_parser._ocr_page(b"png", security_level="public"))
    assert text == "LOCAL"
    assert calls == {"local": 1, "vision": 0}


def test_ocr_page_dispatches_to_vision(monkeypatch):
    calls = {"local": 0, "vision": 0}

    async def _spy_local(*, image_bytes, mime="image/png", lang=None):
        calls["local"] += 1
        return "LOCAL", pdf_parser._zero_usage()

    async def _spy_vision(*, image_bytes, mime="image/png", security_level="public"):
        calls["vision"] += 1
        return "VISION", pdf_parser._zero_usage()

    monkeypatch.setattr(settings, "OCR_BACKEND", "vision")
    monkeypatch.setattr(ocr_local, "ocr_image", _spy_local)
    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _spy_vision)

    text, _usage = asyncio.run(pdf_parser._ocr_page(b"png", security_level="public"))
    assert text == "VISION"
    assert calls == {"local": 0, "vision": 1}


def test_ocr_page_confidential_never_calls_cloud(monkeypatch):
    """A confidential page with a non-tesseract backend must raise BEFORE any
    cloud call — proving cloud OCR is unreachable for privileged docs."""
    cloud_called = {"n": 0}

    async def _spy_vision(*, image_bytes, mime="image/png", security_level="public"):
        cloud_called["n"] += 1
        return "VISION", pdf_parser._zero_usage()

    monkeypatch.setattr(settings, "OCR_BACKEND", "vision")
    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _spy_vision)

    with pytest.raises(RuntimeError):
        asyncio.run(pdf_parser._ocr_page(b"png", security_level="confidential"))
    assert cloud_called["n"] == 0


def test_zero_usage_is_cost_free():
    usage = ocr_local._zero_usage()
    assert usage["estimated_cost_usd"] == 0.0
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0


def test_ocr_image_sync_empty_bytes_returns_empty():
    # Empty render is not an error: returns "" + zero usage without needing
    # tesseract at all (early return).
    text, usage = ocr_local.ocr_image_sync(b"")
    assert text == ""
    assert usage["estimated_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# 2. Live Tesseract OCR — skipped when the engine is unavailable
# ---------------------------------------------------------------------------

_TESSERACT_AVAILABLE = ocr_local.is_available()


@pytest.mark.skipif(
    not _TESSERACT_AVAILABLE,
    reason="pytesseract / tesseract binary not installed (on-prem OCR optional)",
)
def test_tesseract_ocrs_rendered_text():
    """Render a tiny PNG with known text via Pillow, OCR it, assert non-empty
    and that the recognised text contains our token. Only runs where tesseract
    is actually installed."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 80), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 25), "PATENT 200", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    text, usage = ocr_local.ocr_image_sync(buf.getvalue(), lang="eng")
    assert text.strip() != ""
    # On-prem OCR is always cost-free.
    assert usage["estimated_cost_usd"] == 0.0
    # Tesseract on a clean default-font render reliably picks up the digits.
    assert "200" in text or "PATENT" in text.upper()


@pytest.mark.skipif(
    not _TESSERACT_AVAILABLE,
    reason="pytesseract / tesseract binary not installed (on-prem OCR optional)",
)
def test_tesseract_async_wrapper():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (200, 60), color="white")
    ImageDraw.Draw(img).text((10, 20), "HELLO", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    text, usage = asyncio.run(ocr_local.ocr_image(image_bytes=buf.getvalue(), lang="eng"))
    assert isinstance(text, str)
    assert usage["estimated_cost_usd"] == 0.0


def test_require_tesseract_raises_clearly_when_absent(monkeypatch):
    """If pytesseract import fails, _require_tesseract raises an actionable
    RuntimeError (not a bare ImportError)."""
    if _TESSERACT_AVAILABLE:
        pytest.skip("tesseract is installed; cannot simulate absence cleanly")
    with pytest.raises(RuntimeError) as ei:
        ocr_local._require_tesseract()
    assert "tesseract" in str(ei.value).lower()
