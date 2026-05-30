"""PDF + DOCX text extraction with Vision OCR fallback (Day 2).

Layering rules (CLAUDE.md §4):
    - AI Engine module — runs inside the AI Engine FastAPI process.
    - Holds no business state. Does not write to any DB.
    - All cloud LLM access goes through `llm_client.vision_ocr` so cost
      accounting + retry + confidential-routing all stay centralised.

Public surface:
    extract_pdf_text(pdf_bytes, max_pages=100, security_level="public")
        -> ExtractResult

    extract_docx_text(docx_bytes) -> ExtractResult

File bytes never touch disk: PyMuPDF and python-docx are both happy with
in-memory byte streams.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import TypedDict

import fitz  # PyMuPDF

from backend.ai_engine import llm_client
from backend.shared.config import settings


logger = logging.getLogger(__name__)


class ExtractResult(TypedDict):
    pages: list[str]            # extracted text per page (0-indexed)
    page_count: int
    ocr_pages: list[int]        # 0-indexed pages that were routed through OCR
    warnings: list[str]
    char_count: int
    # Aggregate OCR usage so the gateway can record cost in the audit row.
    # All zeros when no page hit the OCR fallback.
    usage: dict


# ---------- PDF -------------------------------------------------------------


async def extract_pdf_text(
    pdf_bytes: bytes,
    max_pages: int = 100,
    *,
    security_level: str = "public",
) -> ExtractResult:
    """Parse a PDF in memory; OCR any page whose text layer is too thin.

    Raises:
        ValueError       — bytes are not a valid PDF.
        PermissionError  — PDF is password-protected.
        RuntimeError     — PyMuPDF could not open / parse the document.

    The `max_pages` cap is enforced at the start: pages beyond the cap are
    silently dropped and a warning recorded. We do NOT 413 here — that's the
    gateway's job (different concern: bandwidth vs. compute).
    """
    if not pdf_bytes:
        raise ValueError("empty PDF bytes")

    warnings: list[str] = []
    pages_text: list[str] = []
    ocr_page_indices: list[int] = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises various exceptions; normalise.
        raise ValueError(f"not a valid PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise PermissionError(
                "PDF is password-protected. Decrypt before uploading."
            )

        total_pages = doc.page_count
        if total_pages > max_pages:
            warnings.append(
                f"PDF has {total_pages} pages; truncated to first {max_pages}."
            )
            effective_pages = max_pages
        else:
            effective_pages = total_pages

        # Phase 1: cheap PyMuPDF text extract. Pages with too little text are
        # marked for OCR but we *don't* serialise the OCR calls inside this
        # loop — we collect them and fire them in parallel below.
        ocr_jobs: list[tuple[int, bytes]] = []  # (page_index, png_bytes)
        for page_idx in range(effective_pages):
            try:
                page = doc.load_page(page_idx)
                text = page.get_text() or ""
            except Exception as exc:
                raise RuntimeError(
                    f"failed to parse page {page_idx} of PDF: {exc}"
                ) from exc

            text = text.strip()
            if len(text) >= settings.MIN_CHARS_PER_PAGE_FOR_TEXT:
                pages_text.append(text)
                continue

            # Scanned page (or image-only). Render and queue for OCR.
            try:
                pix = page.get_pixmap(dpi=200, alpha=False)
                png_bytes = pix.tobytes("png")
            except Exception as exc:
                raise RuntimeError(
                    f"failed to render page {page_idx} for OCR: {exc}"
                ) from exc
            pages_text.append("")  # placeholder, filled in below
            ocr_jobs.append((page_idx, png_bytes))

        # Phase 2: bounded-concurrency OCR. Default cap of 4 keeps us under
        # Anthropic per-key rate limits during a 50-page scanned PDF burst.
        usage_totals = _zero_usage()
        if ocr_jobs:
            ocr_page_indices = [idx for idx, _ in ocr_jobs]
            sem = asyncio.Semaphore(max(1, settings.OCR_PARALLELISM))

            async def _ocr_one(page_idx: int, png: bytes) -> tuple[int, str, dict]:
                async with sem:
                    text, usage = await llm_client.vision_ocr(
                        image_bytes=png,
                        mime="image/png",
                        security_level=security_level,
                    )
                    return page_idx, text, usage

            results = await asyncio.gather(
                *(_ocr_one(idx, png) for idx, png in ocr_jobs),
                return_exceptions=True,
            )

            for r in results:
                if isinstance(r, BaseException):
                    # Surface as RuntimeError so the gateway returns 5xx; the
                    # alternative — swallowing the error and returning a blank
                    # page — would silently lose evidence in a legal workflow.
                    raise RuntimeError(f"vision_ocr failed for a page: {r}") from r
                page_idx, text, usage = r
                pages_text[page_idx] = text
                _add_usage(usage_totals, usage)

    char_count = sum(len(p) for p in pages_text)

    return ExtractResult(
        pages=pages_text,
        page_count=len(pages_text),
        ocr_pages=ocr_page_indices,
        warnings=warnings,
        char_count=char_count,
        usage=usage_totals,
    )


# ---------- DOCX ------------------------------------------------------------


async def extract_docx_text(docx_bytes: bytes) -> ExtractResult:
    """Parse a DOCX in memory.

    DOCX has no real "page" concept (pagination is decided by the renderer),
    so we treat each paragraph as one logical "page" purely so the response
    shape matches the PDF extractor. The frontend then re-joins everything
    with the same page-break separator.

    OCR is never used here — DOCX is by definition a text format. If it
    contains images, those are intentionally left to the attorney to handle
    manually (Vision OCR on every embedded image would explode cost without
    a clear win).
    """
    if not docx_bytes:
        raise ValueError("empty DOCX bytes")

    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover — listed in requirements
        raise RuntimeError(
            "python-docx not installed. Add `python-docx==1.1.2` to "
            "backend/requirements.txt."
        ) from exc

    try:
        doc = Document(io.BytesIO(docx_bytes))
    except Exception as exc:
        # python-docx wraps zipfile/parse errors in PackageNotFoundError /
        # InvalidXmlError. Surface a consistent type for the gateway.
        raise ValueError(f"not a valid DOCX: {exc}") from exc

    paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    if not paragraphs:
        # Fallback: try table cells. Some legal templates put body text in
        # a single-cell table for layout reasons.
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if p.text and p.text.strip():
                            paragraphs.append(p.text)

    char_count = sum(len(p) for p in paragraphs)

    return ExtractResult(
        pages=paragraphs,
        page_count=len(paragraphs),
        ocr_pages=[],
        warnings=[],
        char_count=char_count,
        usage=_zero_usage(),
    )


# ---------- usage aggregation helpers --------------------------------------


def _zero_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _add_usage(into: dict, frm: dict) -> None:
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        into[key] = int(into.get(key, 0)) + int(frm.get(key, 0) or 0)
    into["estimated_cost_usd"] = float(into.get("estimated_cost_usd", 0.0)) + float(
        frm.get("estimated_cost_usd", 0.0) or 0.0
    )
