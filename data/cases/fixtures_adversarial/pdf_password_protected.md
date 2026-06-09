# pdf_password_protected.pdf

## What it tests
A 1-page PDF encrypted with AES-256 (PyMuPDF `encryption=4`) and
locked with both an owner and user password. Without the password
PyMuPDF's `fitz.open()` raises before any text can be extracted.

## Expected behavior
- POST `/v1/oa/upload` with this PDF + correct `Authorization` +
  `X-Case-Id: CASE-2025-001` should return **422**
  ("PDF is password protected" or similar). The gateway's upload
  handler must catch PyMuPDF's `RuntimeError`/`fz.RuntimeException`
  and translate it to a friendly 422 — NOT 500.
- No partial extracted text should appear in the response.

## Regeneration
This is a binary fixture; regenerate via `python scripts/generate_test_data.py`.
The password is `test-password-do-not-use-in-prod`.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_password_protected_pdf_returns_422`
