"""On-prem Tesseract OCR backend (Q8 — "OCR 必跑", invariant #7).

Why this exists
---------------
The cloud Vision OCR path (`llm_client.vision_ocr`) is **forbidden** for
confidential / top_secret documents — their pages must never leave the box
(CLAUDE.md §4 invariant #7, Q15). Before this module there was simply no way
to OCR a *scanned* confidential PDF: the text layer is empty and cloud OCR is
off-limits, so extraction failed. This adds a real, local OCR path using
Tesseract so a confidential scan can be processed entirely on-prem.

Layering rules (CLAUDE.md §4)
-----------------------------
- AI Engine module — runs inside the AI Engine FastAPI process.
- Holds no business state. Writes to no DB.
- On-prem only: no network egress. Zero $ cost (the returned usage dict is
  all-zeros so the gateway's cost circuit breaker sees on-prem OCR as free).

Lazy import
-----------
`pytesseract` + the `tesseract` binary are an *optional* on-prem dependency
(see backend/requirements.txt). They are NOT installed in CI. We therefore
import lazily and raise a clear RuntimeError if either is missing, rather than
failing at module import and turning every test red.
"""

from __future__ import annotations

import io
import logging

from backend.shared.config import settings

logger = logging.getLogger(__name__)


def _zero_usage() -> dict:
    """On-prem OCR has no per-token cost — return an all-zero usage dict so the
    gateway's cost accounting / circuit breaker treats it as free."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _require_tesseract():
    """Import pytesseract + verify the binary is reachable.

    Raises RuntimeError with an actionable message if either the Python
    binding or the underlying tesseract executable is unavailable. Callers
    should let this propagate — silently degrading to cloud OCR would violate
    invariant #7 for confidential docs.
    """
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:  # pragma: no cover — exercised via skip in CI
        raise RuntimeError(
            "OCR_BACKEND=tesseract but pytesseract is not installed. Install "
            "the optional on-prem OCR group: `pip install pytesseract` and the "
            "tesseract binary (e.g. `apt-get install tesseract-ocr "
            "tesseract-ocr-chi-tra`)."
        ) from exc

    try:
        # Cheap liveness probe: this shells out to `tesseract --version` and
        # raises pytesseract.TesseractNotFoundError if the binary is missing.
        pytesseract.get_tesseract_version()
    except Exception as exc:  # pragma: no cover — exercised via skip in CI
        raise RuntimeError(
            "OCR_BACKEND=tesseract but the `tesseract` binary was not found on "
            "PATH (pytesseract is installed but the engine is not). Install it "
            "with your OS package manager, e.g. `apt-get install tesseract-ocr "
            "tesseract-ocr-chi-tra`."
        ) from exc

    return pytesseract


def is_available() -> bool:
    """True iff pytesseract + the tesseract binary are usable. Never raises.

    Used by tests to skip the live-OCR assertion when the engine is absent
    (mirrors the Qdrant-reachable skip in test_vector_store_contract.py).
    """
    try:
        _require_tesseract()
        return True
    except Exception:
        return False


def ocr_image_sync(png_bytes: bytes, *, lang: str | None = None) -> tuple[str, dict]:
    """Blocking on-prem OCR of one rendered page (PNG bytes) → (text, usage).

    Traditional Chinese + English by default (`settings.OCR_TESSERACT_LANG`).
    This is synchronous/blocking (pytesseract shells out + waits); the async
    wrapper runs it in a threadpool so it never blocks the event loop.

    Raises RuntimeError if Tesseract is unavailable (see `_require_tesseract`).
    """
    if not png_bytes:
        # An empty render is not an error — just no text. Keeps the parser's
        # per-page loop robust to a blank scanned page.
        return "", _zero_usage()

    pytesseract = _require_tesseract()
    lang = lang or settings.OCR_TESSERACT_LANG

    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover — Pillow ships with pytesseract
        raise RuntimeError(
            "OCR_BACKEND=tesseract requires Pillow (PIL) to decode the rendered "
            "page image. `pip install Pillow`."
        ) from exc

    with Image.open(io.BytesIO(png_bytes)) as img:
        text = pytesseract.image_to_string(img, lang=lang)

    return text.strip(), _zero_usage()


async def ocr_image(
    *, image_bytes: bytes, mime: str = "image/png", lang: str | None = None
) -> tuple[str, dict]:
    """Async wrapper matching `llm_client.vision_ocr`'s signature shape.

    Runs the blocking Tesseract call in a threadpool (`asyncio.to_thread`) so
    the parser's bounded-concurrency gather doesn't stall the event loop. The
    `mime` arg is accepted for signature parity with the cloud path; the page
    renderer always hands us PNG bytes.
    """
    import asyncio

    return await asyncio.to_thread(ocr_image_sync, image_bytes, lang=lang)
