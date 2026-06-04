# pdf_scan_only_no_text.pdf

## What it tests
A 2-page PDF where each page is a single embedded image (rendered
text-as-image). `fitz.Page.get_text()` returns an empty string for
both pages because there is no text layer.

This is the "scanned paper OA" case — PyMuPDF cannot extract anything,
so the gateway must fall back to the Vision OCR path
(`MockLLM.vision_ocr` in mock mode; `AnthropicLLM.vision_ocr` in real
mode).

## Expected behavior
- POST `/v1/oa/upload` returns **200**.
- `response.ocr_pages_used == [0, 1]` (0-indexed in current backend) —
  both pages went through OCR.
- `response.extracted_text` contains the mock OCR placeholder
  (`[MOCK OCR — N bytes input — would extract patent OA text here]`)
  joined with the `--- page break ---` separator.
- `response.cost_meta.estimated_cost_usd > 0` (mock OCR reports
  $0.0015 per page).

## Regeneration
This is a binary fixture; regenerate via `python scripts/generate_test_data.py`.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_scan_only_pdf_triggers_vision_ocr_mock`
