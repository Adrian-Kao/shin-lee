"""Regenerate binary adversarial fixtures for patentmind-poc test suite.

When to re-run:
  - After cloning the repo, since binary fixtures (PDFs) are gitignored
    in some configurations and need on-demand regeneration.
  - When changing the password / page count of fixtures (edit the
    constants below first, then re-run).
  - After upgrading PyMuPDF if the new version changes default metadata.

Idempotent:
  Each fixture is only written if the target path doesn't already exist.
  Delete the file first if you want to force regeneration.

Outputs:
  data/cases/fixtures_adversarial/pdf_password_protected.pdf
  data/cases/fixtures_adversarial/pdf_scan_only_no_text.pdf

Dependencies:
  - PyMuPDF (fitz) ≥ 1.20  (already required by tests/integration/test_pdf_upload.py)
  - Pillow                 (used to render a "scanned" page as image-only PDF)

Usage:
  python scripts/generate_test_data.py

Exit code 0 on success, non-zero if any fixture failed to write.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "data" / "cases" / "fixtures_adversarial"

# ---- Tunable constants -----------------------------------------------------
_PASSWORD = "test-password-do-not-use-in-prod"  # documented in companion .md
_SCAN_DPI = 100  # keep page bytes < 200 KB so we don't blow past CI tarball limits


def _make_password_protected_pdf(out_path: Path) -> None:
    """Create a 1-page password-protected PDF.

    PyMuPDF's save() accepts `encryption=...` + `owner_pw=...` + `user_pw=...`.
    We use AES-256 (encryption=4 in PyMuPDF terms). The fixture's job is to
    return 422 from /v1/oa/upload because the PDF cannot be opened without
    a password.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_text(
        (72, 100),
        "This PDF is password protected. The test must reject it with 422.",
        fontsize=14,
    )
    # encryption=4 → AES-256; user_pw locks read access.
    # owner_pw is required for fitz.PDF_ENCRYPT_AES_256.
    doc.save(
        str(out_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=_PASSWORD,
        user_pw=_PASSWORD,
    )
    doc.close()


def _make_scan_only_pdf(out_path: Path) -> None:
    """Create a 2-page scan-only PDF (image-only, no text layer).

    A real "scanned" PDF would be a photo of paper. We simulate by rendering
    text to a PIL image, then embedding that image as a single page — there
    is no text layer, so PyMuPDF's `page.get_text()` returns empty, which
    is what triggers the Vision OCR fallback.
    """
    import fitz
    from PIL import Image, ImageDraw, ImageFont

    doc = fitz.open()
    for page_no, body in enumerate(
        [
            "Office Action page 1 (image-only).\nThis page has no text layer.\nVision OCR is required.",
            "Page 2: rejection details.\nClaims 1-3 rejected per 35 USC 103.\nCited: US10876543.",
        ],
        start=1,
    ):
        # Render a 8.5x11 inch image at SCAN_DPI dpi.
        w_px = int(8.5 * _SCAN_DPI)
        h_px = int(11 * _SCAN_DPI)
        img = Image.new("RGB", (w_px, h_px), "white")
        draw = ImageDraw.Draw(img)
        try:
            # Try a default TT font if available; fall back to PIL default.
            font = ImageFont.truetype("arial.ttf", 28)
        except OSError:
            font = ImageFont.load_default()
        draw.text((50, 50), body, fill="black", font=font)
        draw.text(
            (50, h_px - 60),
            f"-- Page {page_no} --",
            fill="black",
            font=font,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        page = doc.new_page(width=612, height=792)  # US Letter in points
        # Insert image full-page. NO insert_text() — that's the whole point.
        page.insert_image(page.rect, stream=img_bytes)

    doc.save(str(out_path))
    doc.close()


def _maybe_write(path: Path, builder, label: str) -> bool:
    """Run `builder(path)` only if `path` doesn't already exist. Returns
    True if the file is present afterwards (either pre-existing or newly
    written), False if generation failed."""
    if path.exists():
        size_kb = path.stat().st_size / 1024
        print(f"  [skip] {label}: {path.name} already exists ({size_kb:.1f} KB)")
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        builder(path)
        size_kb = path.stat().st_size / 1024
        print(f"  [ok]   {label}: {path.name} ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"  [FAIL] {label}: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def main() -> int:
    print(f"Regenerating adversarial PDF fixtures in {FIXTURES_DIR}:")
    ok = True
    ok &= _maybe_write(
        FIXTURES_DIR / "pdf_password_protected.pdf",
        _make_password_protected_pdf,
        "password-protected PDF",
    )
    ok &= _maybe_write(
        FIXTURES_DIR / "pdf_scan_only_no_text.pdf",
        _make_scan_only_pdf,
        "scan-only PDF (no text layer)",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
