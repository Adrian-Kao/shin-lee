# oversized_oa_6mb.txt

## What it tests
6,291,456 characters of OA text — exactly 1 MiB over the 5 MiB cap.

## Expected behavior
- POST `/v1/oa/analyze` with this body should return **422** with a
  Pydantic `string_too_long` error referencing `oa_text`.
- The body-size middleware (default 100MB) does not trigger.
- No audit row should be written for a 422 (request never reaches the
  handler — Pydantic short-circuits at validation time).

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_oversized_oa_6mb_rejected_422`
