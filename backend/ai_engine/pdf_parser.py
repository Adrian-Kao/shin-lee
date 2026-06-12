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
import re
from typing import TypedDict

import fitz  # PyMuPDF

from backend.ai_engine import llm_client, ocr_local
from backend.shared.config import settings

logger = logging.getLogger(__name__)


# ---------- OCR backend dispatch (Q8 / invariant #7) ------------------------


def _is_confidential(security_level: str) -> bool:
    return security_level in settings.LOCAL_LLM_FOR_SECURITY_LEVELS


def _resolve_ocr_backend(security_level: str) -> str:
    """Decide which OCR backend a page should use, enforcing the Q15/invariant
    #7 rule that confidential docs MUST stay on-prem.

    Returns one of: "tesseract" | "vision" | "mock".

    Raises RuntimeError (defense-in-depth) if a confidential/top_secret doc is
    configured for anything other than the local tesseract backend — rather
    than silently leaking privileged pages to cloud OCR. The gateway already
    blocks -CONF uploads at the edge; this is the OCR-layer backstop.
    """
    backend = settings.OCR_BACKEND
    if _is_confidential(security_level):
        if backend != "tesseract":
            raise RuntimeError(
                f"confidential document (security_level={security_level!r}) "
                f"requires OCR_BACKEND=tesseract (on-prem); got "
                f"OCR_BACKEND={backend!r}. Cloud/mock OCR is forbidden for "
                "confidential cases (invariant #7 / Q15)."
            )
        return "tesseract"
    return backend


async def _ocr_page(png_bytes: bytes, *, security_level: str) -> tuple[str, dict]:
    """Route one rendered page through the configured OCR backend.

    - tesseract → on-prem Tesseract (threadpool; cost-free).
    - vision    → cloud Claude Vision via llm_client.vision_ocr.
    - mock      → deterministic MockLLM placeholder (default; tests/demo).

    Confidential docs are forced to tesseract by `_resolve_ocr_backend`.
    """
    backend = _resolve_ocr_backend(security_level)
    if backend == "tesseract":
        return await ocr_local.ocr_image(image_bytes=png_bytes, mime="image/png")
    # Both "vision" and "mock" go through llm_client.vision_ocr, which itself
    # dispatches on LLM_MODE (anthropic→cloud, mock→placeholder) and refuses
    # confidential levels — a second backstop we never reach for -CONF here.
    return await llm_client.vision_ocr(
        image_bytes=png_bytes,
        mime="image/png",
        security_level=security_level,
    )


class PageQuality(TypedDict):
    """Per-page extraction quality signal (Q8 — scan-quality surfacing).

    Lets a downstream caller (gateway / frontend) flag a page that came out of
    OCR nearly empty — the classic "the attorney scanned a crooked / blank
    page" failure — without the parser having to make the decision itself.
    """

    page: int  # 0-indexed page number
    source: str  # "text" (born-digital) | "ocr" (scanned)
    char_count: int  # characters extracted for this page
    low_text: bool  # True ⇒ suspiciously little text for the source
    # Coarse 0..1 confidence heuristic. Text-layer pages are 1.0 (PyMuPDF
    # extraction is exact); OCR pages get a length-derived proxy until a real
    # OCR engine returns per-word confidence (tesseract image_to_data / Vision).
    confidence: float


class ExtractResult(TypedDict):
    pages: list[str]  # extracted text per page (0-indexed)
    page_count: int
    ocr_pages: list[int]  # 0-indexed pages that were routed through OCR
    warnings: list[str]
    char_count: int
    # Aggregate OCR usage so the gateway can record cost in the audit row.
    # All zeros when no page hit the OCR fallback.
    usage: dict
    # Q8 element table: {reference_numeral: best description phrase}, extracted
    # from the joined page text (the "OCR 必跑 → element table" chain). Empty
    # dict when the doc carries no drawing reference numerals or extraction
    # failed — never breaks the upload.
    element_table: dict[int, str]
    # Q8 quality signals (Day 13J). One entry per returned page, same order /
    # indexing as `pages`. Empty list only for a zero-page extraction (which is
    # itself a hard error for PDF; possible for an all-blank DOCX).
    page_quality: list[PageQuality]
    # 0-indexed pages whose extraction looks too thin (bad scan / blank page).
    # Subset relationship is NOT guaranteed with ocr_pages: a born-digital page
    # can also be near-empty (e.g. a divider page).
    low_text_pages: list[int]


# ---------- PDF -------------------------------------------------------------


async def extract_pdf_text(
    pdf_bytes: bytes,
    max_pages: int = 100,
    *,
    security_level: str = "public",
) -> ExtractResult:
    """Parse a PDF in memory; OCR any page whose text layer is too thin.

    Raises:
        ValueError       — bytes are not a valid PDF, are empty, the document
                           has zero pages, or the page count exceeds the hard
                           `MAX_PDF_PAGES` ceiling. Each is a clear, testable
                           error — never a crash or a silent empty result.
        PermissionError  — PDF is password-protected / encrypted.
        RuntimeError     — PyMuPDF could not render/parse a page, or an OCR
                           backend call failed.

    The per-call `max_pages` cap is enforced as *truncation-with-warning*:
    pages beyond the cap are dropped and a warning recorded. We do NOT 413
    here — that's the gateway's job (bandwidth) vs. ours (compute). The
    separate `settings.MAX_PDF_PAGES` is an absolute upper bound: a document
    with more pages than that is refused outright as a likely malformed /
    zip-bomb payload.
    """
    if not pdf_bytes:
        raise ValueError("empty PDF bytes")

    warnings: list[str] = []
    pages_text: list[str] = []
    ocr_page_indices: list[int] = []
    page_sources: list[str] = []  # "text" | "ocr", same order as pages_text

    # Defense-in-depth (invariant #7 / Q15): for a confidential/top_secret doc
    # we must guarantee on-prem OCR. Validate the backend choice up-front —
    # before reading any page — so a misconfigured caller is refused even if
    # the PDF happens to have a full text layer (the policy is about *capability*
    # to keep the doc local, not just the pages that need OCR today).
    if _is_confidential(security_level):
        _resolve_ocr_backend(security_level)  # raises if not tesseract

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises various exceptions; normalise.
        raise ValueError(f"not a valid PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise PermissionError("PDF is password-protected. Decrypt before uploading.")

        total_pages = doc.page_count

        # Zero-page document: a structurally-valid PDF container with no pages
        # (or a non-PDF whose bytes happened to start with "%PDF-" and opened
        # but carry no page tree). Refuse loudly rather than returning an empty
        # result that a downstream caller would mistake for "nothing to say".
        if total_pages <= 0:
            raise ValueError(
                "PDF has zero pages — the file is empty, corrupt, or not a "
                "real PDF despite its header."
            )

        # Absolute ceiling — independent of the per-call truncation cap. A doc
        # claiming millions of pages is almost certainly a malformed / hostile
        # payload; reject before we allocate per-page work.
        if total_pages > settings.MAX_PDF_PAGES:
            raise ValueError(
                f"PDF declares {total_pages} pages, exceeding the hard cap of "
                f"{settings.MAX_PDF_PAGES} (MAX_PDF_PAGES). Refusing as a "
                "likely malformed or hostile document."
            )

        if total_pages > max_pages:
            warnings.append(f"PDF has {total_pages} pages; truncated to first {max_pages}.")
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
                raise RuntimeError(f"failed to parse page {page_idx} of PDF: {exc}") from exc

            text = text.strip()
            if len(text) >= settings.MIN_CHARS_PER_PAGE_FOR_TEXT:
                # Born-digital page: embedded text layer is rich enough; use it
                # directly and skip OCR entirely.
                pages_text.append(text)
                page_sources.append("text")
                continue

            # Scanned / image-only page: the text layer is too thin, so fall
            # back to OCR. Render at 200 dpi and queue for the parallel pass.
            try:
                pix = page.get_pixmap(dpi=200, alpha=False)
                png_bytes = pix.tobytes("png")
            except Exception as exc:
                raise RuntimeError(f"failed to render page {page_idx} for OCR: {exc}") from exc
            pages_text.append("")  # placeholder, filled in below
            page_sources.append("ocr")
            ocr_jobs.append((page_idx, png_bytes))

        # Phase 2: bounded-concurrency OCR. Default cap of 4 keeps us under
        # Anthropic per-key rate limits during a 50-page scanned PDF burst.
        usage_totals = _zero_usage()
        if ocr_jobs:
            ocr_page_indices = [idx for idx, _ in ocr_jobs]
            sem = asyncio.Semaphore(max(1, settings.OCR_PARALLELISM))

            async def _ocr_one(page_idx: int, png: bytes) -> tuple[int, str, dict]:
                async with sem:
                    text, usage = await _ocr_page(png, security_level=security_level)
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

    page_quality, low_text_pages = _build_quality(pages_text, page_sources)

    # Document-level scan warning: if a large fraction of pages needed OCR the
    # document is effectively a scan, and the caller may want to set lower
    # expectations on extraction fidelity / element-table completeness.
    if effective_pages and ocr_page_indices:
        ratio = len(ocr_page_indices) / effective_pages
        if ratio >= settings.OCR_SCANNED_DOC_WARN_RATIO:
            warnings.append(
                f"{len(ocr_page_indices)}/{effective_pages} pages required OCR "
                f"({ratio:.0%}); document is likely a scan — extraction quality "
                "may be degraded."
            )
    if low_text_pages:
        warnings.append(f"low-text pages detected (possible bad/blank scan): {low_text_pages}")

    return ExtractResult(
        pages=pages_text,
        page_count=len(pages_text),
        ocr_pages=ocr_page_indices,
        warnings=warnings,
        char_count=char_count,
        usage=usage_totals,
        element_table=_safe_element_table(pages_text),
        page_quality=page_quality,
        low_text_pages=low_text_pages,
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
            "python-docx not installed. Add `python-docx==1.1.2` to backend/requirements.txt."
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

    # Every DOCX "page" is a text paragraph (source="text"); OCR never runs.
    page_quality, low_text_pages = _build_quality(paragraphs, ["text"] * len(paragraphs))

    return ExtractResult(
        pages=paragraphs,
        page_count=len(paragraphs),
        ocr_pages=[],
        warnings=[],
        char_count=char_count,
        usage=_zero_usage(),
        element_table=_safe_element_table(paragraphs),
        page_quality=page_quality,
        low_text_pages=low_text_pages,
    )


# ---------- Q8 element table -----------------------------------------------


def _safe_element_table(pages: list[str]) -> dict[int, str]:
    """Run the Q8 reference-numeral extractor over the joined page text.

    Defensive by contract: a failed or empty extraction returns {} and never
    propagates — the element table is a value-add over the extracted text, not
    a hard dependency of the upload. Numerals are stringified would-be-int keys
    so the result is JSON-clean (FastAPI serialises int keys to strings anyway,
    but we keep the int→str mapping explicit so the gateway field is stable).
    """
    try:
        from backend.ai_engine.element_table import extract_element_table

        joined = "\n".join(p for p in pages if p)
        if not joined.strip():
            return {}
        return extract_element_table(joined)
    except Exception as exc:  # never let element-table extraction break upload
        logger.warning("element-table extraction failed; returning empty: %s", exc)
        return {}


# ---------- Q8 per-page quality signals ------------------------------------


def _build_quality(pages: list[str], sources: list[str]) -> tuple[list[PageQuality], list[int]]:
    """Compute the per-page quality signal + the low-text-page index list.

    `sources[i]` is "text" (born-digital text layer) or "ocr" (scanned page
    that went through an OCR backend). The two lists are positional — caller
    guarantees `len(sources) == len(pages)` (asserted defensively).

    Heuristics (deliberately simple; replace with real OCR per-word confidence
    when tesseract `image_to_data` / Claude-Vision structured output lands):
      - text-layer page  → confidence 1.0 (PyMuPDF extraction is exact).
      - ocr page         → confidence scales with extracted length, capped at
                           0.95 since OCR is never certain; an empty/near-empty
                           OCR page lands near 0 and is flagged low_text.
      - low_text is true when an OCR page came back under
        OCR_LOW_TEXT_WARN_CHARS chars — the bad/blank-scan signal a downstream
        caller surfaces to the attorney. Born-digital pages are not flagged
        (a legitimately short divider page is not a scan failure).
    """
    if len(sources) != len(pages):  # pragma: no cover — internal invariant
        # Be forgiving rather than crash the whole upload: pad with "text".
        sources = (sources + ["text"] * len(pages))[: len(pages)]

    warn_chars = settings.OCR_LOW_TEXT_WARN_CHARS
    quality: list[PageQuality] = []
    low_text_pages: list[int] = []

    for idx, (text, source) in enumerate(zip(pages, sources, strict=True)):
        n = len(text)
        if source == "ocr":
            low = n < warn_chars
            # Length-derived proxy: 0 chars → 0.0, ramps to a 0.95 ceiling by
            # ~400 chars. Keeps the signal monotone without pretending an OCR
            # page is ever perfectly trustworthy.
            confidence = 0.0 if n == 0 else min(0.95, 0.3 + n / 400.0 * 0.65)
        else:  # text layer
            low = False
            confidence = 1.0
        if low:
            low_text_pages.append(idx)
        quality.append(
            PageQuality(
                page=idx,
                source=source,
                char_count=n,
                low_text=low,
                confidence=round(confidence, 3),
            )
        )

    return quality, low_text_pages


# ---------- Q8 figure / region extraction (P1 — layout-based detector) ------

# Caption patterns mapping a figure label to its drawing region.
#   western: "FIG. 1", "FIG 2A", "FIGURE 3", "Figs. 4" …
#   CJK:     「第 1 圖」「第三圖」「第2图」 (TW 圖 + CN 简体 图)
_FIG_CAPTION_RE = re.compile(
    r"FIG(?:URE)?S?\.?\s*(?P<western>\d{1,3}[A-Za-z]?)"
    r"|第\s*(?P<cjk>[0-9０-９一二三四五六七八九十百]{1,4})\s*[圖图]",
    re.IGNORECASE,
)

_CJK_DIGIT_MAP = str.maketrans("０１２３４５６７８９", "0123456789")
_CJK_NUMERALS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}  # fmt: skip

# Clustering / filtering knobs (PDF points; 72 pt = 1 inch).
_CLUSTER_GAP_PT = 24.0  # rects closer than this merge into one figure region
_MIN_REGION_AREA_PT2 = 400.0  # drop clusters smaller than ~20×20pt (stray rules)
_CAPTION_MAX_DIST_PT = 200.0  # a caption further than this is not "for" a region


def _normalise_fig_label(match: re.Match[str]) -> str:
    """Normalise a caption regex match to a plain figure label string.

    "FIG. 2A" -> "2A"; 「第３圖」-> "3"; 「第三圖」-> "3". CJK numerals are
    resolved for the common 1–99 range (十/廿 composition); anything exotic is
    returned verbatim — the label is an identifier, not arithmetic.
    """
    western = match.group("western")
    if western:
        return western.upper()
    raw = (match.group("cjk") or "").translate(_CJK_DIGIT_MAP)
    if raw.isdigit():
        return str(int(raw))
    # CJK numeral composition: 三 -> 3, 十 -> 10, 十五 -> 15, 二十一 -> 21.
    total, current = 0, 0
    for ch in raw:
        val = _CJK_NUMERALS.get(ch)
        if val is None:
            return raw  # unexpected char — return verbatim
        if val == 10:
            total += (current or 1) * 10
            current = 0
        else:
            current = val
    return str(total + current) if (total or current) else raw


def _rects_close(a: fitz.Rect, b: fitz.Rect, gap: float) -> bool:
    """True when two rects intersect once each is inflated by ``gap/2``."""
    ax = fitz.Rect(a.x0 - gap / 2, a.y0 - gap / 2, a.x1 + gap / 2, a.y1 + gap / 2)
    return ax.intersects(fitz.Rect(b.x0 - gap / 2, b.y0 - gap / 2, b.x1 + gap / 2, b.y1 + gap / 2))


def _cluster_rects(
    items: list[tuple[fitz.Rect, str]], gap: float
) -> list[tuple[fitz.Rect, set[str]]]:
    """Agglomerate (rect, source) items into merged regions.

    Classic union-by-merge loop: keep folding any two clusters whose bounding
    boxes come within ``gap`` of each other until a fixed point. O(n²) per
    pass, fine for the tens-to-hundreds of strokes a patent drawing page has.
    """
    clusters: list[tuple[fitz.Rect, set[str]]] = [(fitz.Rect(r), {src}) for r, src in items]
    merged = True
    while merged:
        merged = False
        out: list[tuple[fitz.Rect, set[str]]] = []
        for rect, sources in clusters:
            for i, (orect, osources) in enumerate(out):
                if _rects_close(rect, orect, gap):
                    out[i] = (orect | rect, osources | sources)
                    merged = True
                    break
            else:
                out.append((rect, sources))
        clusters = out
    return clusters


async def extract_figure_regions(
    pdf_bytes: bytes,
    page_index: int,
    *,
    security_level: str = "public",
) -> list[dict]:
    """Q8 P1 — detect per-figure regions on a (drawing) page.

    Layout-based detector, fully on-prem (PyMuPDF only — no LLM call):

      1. Collect raster-image placements (``page.get_images`` +
         ``get_image_rects``) and vector-drawing strokes (``page.get_drawings``).
      2. Agglomerate them into figure-sized clusters (rects within
         ``_CLUSTER_GAP_PT`` of each other merge; sub-``_MIN_REGION_AREA_PT2``
         clusters — stray rules/underlines — are dropped).
      3. Match "FIG. N" / 「第 N 圖」 caption text blocks to the nearest
         cluster so each region carries its figure label.

    Returns a list of region dicts, top-to-bottom::

        {
          "page":    int,                  # 0-indexed page
          "figure":  str | None,           # normalised label ("1", "2A") or None
          "caption": str | None,           # matched caption text, e.g. "FIG. 1"
          "bbox":    [x0, y0, x1, y1],     # PDF points, page coordinate space
          "sources": ["image" | "drawing", ...],
        }

    A text-only page (no images, no vector art) yields ``[]`` — the historical
    stub contract callers already rely on. A future Vision pass can crop each
    ``bbox`` and ask "what does numeral 102 point at"; the routing guard below
    already enforces that a confidential doc's crops could only ever go to an
    on-prem backend (invariant #7 / Q15).

    Raises ``ValueError`` for empty/invalid PDF bytes or an out-of-range
    ``page_index``; ``PermissionError`` for an encrypted PDF — mirroring
    ``extract_pdf_text`` so callers handle one error surface.
    """
    if _is_confidential(security_level):
        # Defense-in-depth, same as `_resolve_ocr_backend`: refuse to even
        # *contemplate* cloud figure extraction for a privileged doc. Checked
        # BEFORE parsing so a misconfigured caller is refused outright.
        if settings.OCR_BACKEND != "tesseract":
            raise RuntimeError(
                f"figure-region extraction for confidential document "
                f"(security_level={security_level!r}) requires an on-prem "
                f"backend; OCR_BACKEND={settings.OCR_BACKEND!r} is forbidden "
                "(invariant #7 / Q15). Cloud Vision figure crops are not "
                "allowed for confidential cases."
            )

    if not pdf_bytes:
        raise ValueError("empty PDF bytes")
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"not a valid PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise PermissionError("PDF is password-protected. Decrypt before uploading.")
        if not 0 <= page_index < doc.page_count:
            raise ValueError(
                f"page_index {page_index} out of range for a {doc.page_count}-page PDF"
            )
        page = doc.load_page(page_index)

        # --- 1. candidate rects: raster image placements + vector strokes ---
        candidates: list[tuple[fitz.Rect, str]] = []
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001 — a broken xref must not kill the page
                continue
            for r in rects:
                if not r.is_empty:
                    candidates.append((fitz.Rect(r), "image"))
        try:
            drawings = page.get_drawings()
        except Exception:  # noqa: BLE001 — malformed content stream
            drawings = []
        for d in drawings:
            r = d.get("rect")
            if r is not None and not fitz.Rect(r).is_infinite:
                candidates.append((fitz.Rect(r), "drawing"))

        if not candidates:
            return []  # text-only page — no figure regions (stub-compatible)

        # --- 2. cluster + size-filter ---
        clusters = [
            (rect, sources)
            for rect, sources in _cluster_rects(candidates, _CLUSTER_GAP_PT)
            if rect.get_area() >= _MIN_REGION_AREA_PT2
        ]
        if not clusters:
            return []

        # --- 3. captions: "FIG. N" / 「第 N 圖」 text blocks ---
        captions: list[tuple[str, str, fitz.Rect]] = []  # (label, text, rect)
        try:
            blocks = page.get_text("blocks") or []
        except Exception:  # noqa: BLE001
            blocks = []
        for blk in blocks:
            # block tuple: (x0, y0, x1, y1, text, block_no, block_type)
            if len(blk) >= 7 and blk[6] != 0:
                continue  # not a text block
            text = (blk[4] or "").strip()
            m = _FIG_CAPTION_RE.search(text)
            if m:
                captions.append((_normalise_fig_label(m), m.group(0).strip(), fitz.Rect(blk[:4])))

        # --- 4. label each region with its nearest caption ---
        def _center(r: fitz.Rect) -> tuple[float, float]:
            return ((r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0)

        regions: list[dict] = []
        for rect, sources in clusters:
            best: tuple[float, str, str] | None = None  # (dist, label, caption)
            cx, cy = _center(rect)
            for label, cap_text, cap_rect in captions:
                px, py = _center(cap_rect)
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                # Distance to the region EDGE matters more than to its center
                # for big figures whose caption hugs the bottom edge.
                edge_dy = max(cap_rect.y0 - rect.y1, rect.y0 - cap_rect.y1, 0.0)
                score = min(dist, edge_dy + abs(cx - px))
                if score <= _CAPTION_MAX_DIST_PT and (best is None or score < best[0]):
                    best = (score, label, cap_text)
            regions.append(
                {
                    "page": page_index,
                    "figure": best[1] if best else None,
                    "caption": best[2] if best else None,
                    "bbox": [
                        round(rect.x0, 2),
                        round(rect.y0, 2),
                        round(rect.x1, 2),
                        round(rect.y1, 2),
                    ],
                    "sources": sorted(sources),
                }
            )

        regions.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
        return regions


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
