from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

from .models import PageText


class OcrUnavailable(RuntimeError):
    pass


def _get_ocr():
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # pragma: no cover
        raise OcrUnavailable(
            "PaddleOCR is not installed or could not load. Install requirements and try again."
        ) from exc
    return PaddleOCR(use_angle_cls=True, lang="ch")


def _ocr_image(path: Path, page: int, ocr=None) -> PageText:
    ocr = ocr or _get_ocr()
    result = ocr.ocr(str(path), cls=True)
    lines: list[str] = []
    for block in result or []:
        for item in block or []:
            if len(item) >= 2 and item[1]:
                lines.append(str(item[1][0]))
    return PageText(file_name=path.name, page=page, text="\n".join(lines).strip(), source_path=str(path))


def _ocr_pdf_page(doc: fitz.Document, path: Path, page_index: int, ocr) -> PageText:
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    tmp = path.with_suffix(f".page-{page_index + 1}.png")
    pix.save(tmp)
    try:
        page_text = _ocr_image(tmp, page_index + 1, ocr=ocr)
        return PageText(path.name, page_index + 1, page_text.text, str(path))
    finally:
        tmp.unlink(missing_ok=True)


def load_document(path: str | Path, force_ocr: bool = False) -> list[PageText]:
    source = Path(path).resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        pages: list[PageText] = []
        doc = fitz.open(source)
        ocr = None
        for index, page in enumerate(doc):
            text = "" if force_ocr else page.get_text("text").strip()
            if text:
                pages.append(PageText(source.name, index + 1, text, str(source)))
            else:
                ocr = ocr or _get_ocr()
                pages.append(_ocr_pdf_page(doc, source, index, ocr))
        return pages

    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        Image.open(source).verify()
        return [_ocr_image(source, 1)]

    raise ValueError(f"Unsupported file type: {suffix}")
