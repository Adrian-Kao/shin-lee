"""Q8 P1 — figure-region extraction (pdf_parser.extract_figure_regions).

Synthetic PDFs are generated programmatically with PyMuPDF so the suite stays
offline and deterministic: vector drawings via page.draw_*, raster figures via
an inserted PNG, captions via insert_text.
"""

from __future__ import annotations

import asyncio

import fitz
import pytest

from backend.ai_engine import pdf_parser


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _insert_caption(page: fitz.Page, point: fitz.Point, text: str) -> None:
    """Insert caption text, using PyMuPDF's built-in CJK font when needed
    (the default helv base-14 font cannot encode 圖/图 and silently drops
    the glyphs, which would make the caption invisible to get_text)."""
    if "图" in text:  # simplified glyph is absent from the traditional font
        fontname = "china-s"
    elif any(ord(c) > 0x2E80 for c in text):
        fontname = "china-t"
    else:
        fontname = "helv"
    page.insert_text(point, text, fontsize=11, fontname=fontname)


def _png_bytes(w: int = 60, h: int = 60) -> bytes:
    """A small rendered PNG to embed as a raster image."""
    tmp = fitz.open()
    p = tmp.new_page(width=w, height=h)
    p.draw_rect(fitz.Rect(5, 5, w - 5, h - 5), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    png = p.get_pixmap(dpi=72, alpha=False).tobytes("png")
    tmp.close()
    return png


def _drawing_pdf_with_caption(caption: str) -> bytes:
    """One page: a clustered vector drawing at (100,100)-(300,260) with the
    given caption text just below it."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    # Several nearby strokes that must agglomerate into ONE region.
    page.draw_rect(fitz.Rect(100, 100, 300, 240), color=(0, 0, 0), width=1.5)
    page.draw_line(fitz.Point(100, 170), fitz.Point(300, 170), color=(0, 0, 0))
    page.draw_circle(fitz.Point(200, 200), 30, color=(0, 0, 0))
    page.draw_rect(fitz.Rect(120, 245, 180, 260), color=(0, 0, 0))  # within gap
    _insert_caption(page, fitz.Point(170, 285), caption)
    out = doc.tobytes()
    doc.close()
    return out


def _image_pdf_with_caption(caption: str) -> bytes:
    """One page: a raster image at (150,120)-(350,320) with a caption below."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(150, 120, 350, 320), stream=_png_bytes())
    _insert_caption(page, fitz.Point(220, 350), caption)
    out = doc.tobytes()
    doc.close()
    return out


def _two_figure_pdf() -> bytes:
    """Two well-separated drawings, each with its own caption."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(100, 80, 280, 220), color=(0, 0, 0), width=1.5)
    page.insert_text(fitz.Point(160, 245), "FIG. 1", fontsize=11)
    page.draw_rect(fitz.Rect(100, 480, 280, 620), color=(0, 0, 0), width=1.5)
    page.insert_text(fitz.Point(160, 645), "FIG. 2", fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _text_only_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 100), "Just words, including FIG. 9 mentioned inline.")
    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_vector_drawing_detected_and_labelled():
    regions = _run(pdf_parser.extract_figure_regions(_drawing_pdf_with_caption("FIG. 1"), 0))
    assert len(regions) == 1
    region = regions[0]
    assert region["figure"] == "1"
    assert region["caption"].upper().startswith("FIG")
    assert region["sources"] == ["drawing"]
    assert region["page"] == 0
    # bbox covers the drawn strokes (100,100)-(300,260)
    x0, y0, x1, y1 = region["bbox"]
    assert x0 <= 101 and y0 <= 101 and x1 >= 299 and y1 >= 244


def test_raster_image_detected_with_cjk_caption():
    regions = _run(pdf_parser.extract_figure_regions(_image_pdf_with_caption("第 2 圖"), 0))
    assert len(regions) == 1
    region = regions[0]
    assert region["figure"] == "2"
    assert "image" in region["sources"]
    x0, y0, x1, y1 = region["bbox"]
    assert x0 <= 151 and x1 >= 349  # covers the placed image rect


def test_simplified_cjk_and_numeral_captions_normalise():
    regions = _run(pdf_parser.extract_figure_regions(_drawing_pdf_with_caption("第三图"), 0))
    assert regions[0]["figure"] == "3"
    regions = _run(pdf_parser.extract_figure_regions(_drawing_pdf_with_caption("第１０圖"), 0))
    assert regions[0]["figure"] == "10"
    regions = _run(pdf_parser.extract_figure_regions(_drawing_pdf_with_caption("FIGURE 2A"), 0))
    assert regions[0]["figure"] == "2A"


def test_two_figures_map_to_their_own_captions():
    regions = _run(pdf_parser.extract_figure_regions(_two_figure_pdf(), 0))
    assert len(regions) == 2
    # Sorted top-to-bottom: FIG. 1 first, FIG. 2 second.
    assert regions[0]["figure"] == "1"
    assert regions[1]["figure"] == "2"
    assert regions[0]["bbox"][1] < regions[1]["bbox"][1]


def test_drawing_without_caption_returns_unlabelled_region():
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(100, 100, 300, 260), color=(0, 0, 0), width=1.5)
    pdf = doc.tobytes()
    doc.close()
    regions = _run(pdf_parser.extract_figure_regions(pdf, 0))
    assert len(regions) == 1
    assert regions[0]["figure"] is None
    assert regions[0]["caption"] is None


def test_text_only_page_returns_empty():
    # The historical stub contract: no drawings/images → [] (an inline textual
    # "FIG. 9" mention is NOT a figure region).
    assert _run(pdf_parser.extract_figure_regions(_text_only_pdf(), 0)) == []


def test_tiny_stray_strokes_filtered_out():
    # A lone 10×10pt mark (underline / stray rule) is below the area floor.
    doc = fitz.open()
    page = doc.new_page()
    page.draw_line(fitz.Point(100, 100), fitz.Point(110, 100), color=(0, 0, 0))
    pdf = doc.tobytes()
    doc.close()
    assert _run(pdf_parser.extract_figure_regions(pdf, 0)) == []


# ---------------------------------------------------------------------------
# Error surface (mirrors extract_pdf_text)
# ---------------------------------------------------------------------------


def test_empty_bytes_rejected():
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_figure_regions(b"", 0))


def test_non_pdf_bytes_rejected():
    with pytest.raises(ValueError):
        _run(pdf_parser.extract_figure_regions(b"definitely not a pdf", 0))


def test_page_index_out_of_range_rejected():
    pdf = _text_only_pdf()
    with pytest.raises(ValueError, match="out of range"):
        _run(pdf_parser.extract_figure_regions(pdf, 5))
    with pytest.raises(ValueError, match="out of range"):
        _run(pdf_parser.extract_figure_regions(pdf, -1))


# ---------------------------------------------------------------------------
# Label normalisation unit coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FIG. 1", "1"),
        ("Figure 12", "12"),
        ("FIG 2A", "2A"),
        ("fig. 7b", "7B"),
        ("第 4 圖", "4"),
        ("第５圖", "5"),
        ("第十五圖", "15"),
        ("第二十一图", "21"),
    ],
)
def test_caption_label_normalisation(text, expected):
    m = pdf_parser._FIG_CAPTION_RE.search(text)
    assert m is not None, text
    assert pdf_parser._normalise_fig_label(m) == expected
