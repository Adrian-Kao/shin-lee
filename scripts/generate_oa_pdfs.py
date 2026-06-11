"""Generate realistic Office Action PDFs for testing the upload → extract →
analyze pipeline.

Why this exists
---------------
The repo already ships TEXT office actions (`data/oa_samples/*.txt` and
`data/cases/CASE-DEMO-*/oa.txt`) whose content is aligned with the seed
patents, so analysis produces grounded citations. The upload flow, however,
takes PDF/DOCX. This script renders those existing, citation-grounded texts
into real text-based PDFs so you can exercise the actual PDF text-extraction
path (`backend/ai_engine/pdf_parser.py`) with meaningful, varied input.

Adversarial/binary fixtures (password-protected, scan-only-no-text) are NOT
generated here — see `scripts/generate_test_data.py` for those.

Outputs (idempotent unless --force)
-----------------------------------
  data/oa_samples/pdf/oa_us_sample.pdf
  data/oa_samples/pdf/oa_tw_sample.pdf
  data/oa_samples/pdf/oa_CASE-DEMO-001.pdf ... (first --cases dirs)
  data/oa_samples/pdf/oa_multipage_long.pdf   (concatenated → many pages)
  data/oa_samples/pdf/oa_minimal.pdf          (one short paragraph)
  data/oa_samples/pdf/oa_empty.pdf            (a single blank page, no text)

Usage
-----
  python scripts/generate_oa_pdfs.py                 # samples + 10 cases
  python scripts/generate_oa_pdfs.py --cases 80      # all CASE-DEMO dirs
  python scripts/generate_oa_pdfs.py --force         # overwrite existing

Dependencies: PyMuPDF (fitz) — already required by the PDF upload tests.
Exit code 0 on success, non-zero if any PDF failed to write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "data" / "oa_samples"
CASES_DIR = ROOT / "data" / "cases"
OUT_DIR = SAMPLES_DIR / "pdf"

# Built-in PyMuPDF CJK font (Traditional Chinese; also covers Latin/digits),
# so mixed zh-TW + English Office Actions render without shipping a font file.
_FONT = "china-t"
_FONTSIZE = 11
_LINE_H = 16  # point height per rendered line
_MARGIN = 56  # ~2cm margins
_PAGE = fitz.paper_rect("a4")
_WRAP = 46  # max display-width units per line (CJK counts as 2)


def _disp_width(s: str) -> int:
    """Display width treating CJK/full-width glyphs as 2 columns."""
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E7F else 1  # CJK & full-width punctuation block start
    return w


def _wrap_line(line: str) -> list[str]:
    """Greedy wrap a single logical line to <= _WRAP display units."""
    if not line:
        return [""]
    out: list[str] = []
    cur = ""
    cur_w = 0
    for ch in line:
        cw = 2 if ord(ch) > 0x2E7F else 1
        if cur_w + cw > _WRAP:
            out.append(cur)
            cur, cur_w = ch, cw
        else:
            cur += ch
            cur_w += cw
    out.append(cur)
    return out


def _paginate(text: str) -> list[list[str]]:
    """Turn raw text into pages of wrapped lines."""
    usable_h = _PAGE.height - 2 * _MARGIN
    lines_per_page = max(1, int(usable_h // _LINE_H))
    wrapped: list[str] = []
    for logical in text.replace("\r\n", "\n").split("\n"):
        wrapped.extend(_wrap_line(logical))
    pages: list[list[str]] = []
    for i in range(0, len(wrapped), lines_per_page):
        pages.append(wrapped[i : i + lines_per_page])
    return pages or [[""]]


def text_to_pdf(text: str, dest: Path, *, force: bool) -> bool:
    """Render `text` to a text-based PDF at `dest`. Returns True if written."""
    if dest.exists() and not force:
        print(f"  · skip (exists): {dest.relative_to(ROOT)}")
        return False
    doc = fitz.open()
    for page_lines in _paginate(text):
        page = doc.new_page(width=_PAGE.width, height=_PAGE.height)
        y = _MARGIN
        for line in page_lines:
            if line:
                page.insert_text((_MARGIN, y), line, fontname=_FONT, fontsize=_FONTSIZE)
            y += _LINE_H
    doc.set_metadata({"title": dest.stem, "producer": "patentmind generate_oa_pdfs"})
    doc.save(str(dest), deflate=True)
    doc.close()
    pages = fitz.open(str(dest)).page_count
    print(f"  ✓ {dest.relative_to(ROOT)} ({pages} page{'s' if pages != 1 else ''})")
    return True


def empty_pdf(dest: Path, *, force: bool) -> bool:
    """A valid PDF with one blank page and zero extractable text (boundary
    case for the text-vs-OCR classifier in pdf_parser.py)."""
    if dest.exists() and not force:
        print(f"  · skip (exists): {dest.relative_to(ROOT)}")
        return False
    doc = fitz.open()
    doc.new_page(width=_PAGE.width, height=_PAGE.height)
    doc.save(str(dest))
    doc.close()
    print(f"  ✓ {dest.relative_to(ROOT)} (1 blank page, no text)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cases",
        type=int,
        default=10,
        help="how many CASE-DEMO-* oa.txt files to convert (default 10, max 80)",
    )
    ap.add_argument("--force", action="store_true", help="overwrite existing PDFs")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    failures = 0

    def _try(fn, *a, **k):
        nonlocal written, failures
        try:
            if fn(*a, **k):
                written += 1
        except Exception as exc:  # noqa: BLE001 — report and continue
            failures += 1
            print(f"  ✗ {a[1] if len(a) > 1 else a[0]}: {exc}")

    print("Generating Office Action PDFs → data/oa_samples/pdf/")

    # 1. The two curated samples.
    for stem, src in (("oa_us_sample", "sample_oa_us.txt"), ("oa_tw_sample", "sample_oa_tw.txt")):
        p = SAMPLES_DIR / src
        if p.exists():
            _try(
                text_to_pdf,
                p.read_text(encoding="utf-8"),
                OUT_DIR / f"{stem}.pdf",
                force=args.force,
            )

    # 2. CASE-DEMO oa.txt → one PDF each (aligned with seeded patents).
    case_dirs = sorted(CASES_DIR.glob("CASE-DEMO-*"))[: max(0, args.cases)]
    long_blob: list[str] = []
    for d in case_dirs:
        oa = d / "oa.txt"
        if not oa.exists():
            continue
        body = oa.read_text(encoding="utf-8")
        long_blob.append(f"===== {d.name} =====\n{body}")
        _try(text_to_pdf, body, OUT_DIR / f"oa_{d.name}.pdf", force=args.force)

    # 3. Edge cases.
    if long_blob:
        _try(
            text_to_pdf, "\n\n".join(long_blob), OUT_DIR / "oa_multipage_long.pdf", force=args.force
        )
    _try(
        text_to_pdf,
        "Office Action (minimal).\nClaim 1 is rejected under 35 U.S.C. § 103.",
        OUT_DIR / "oa_minimal.pdf",
        force=args.force,
    )
    _try(empty_pdf, OUT_DIR / "oa_empty.pdf", force=args.force)

    print(f"\nDone. {written} written, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
