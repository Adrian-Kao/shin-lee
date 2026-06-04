# oversized_oa_5mb.txt

## What it tests
An OA text of EXACTLY `_MAX_OA_TEXT_CHARS = 5 * 1024 * 1024` characters
(5,242,880). This is the documented Pydantic `max_length` on
`AnalysisRequest.oa_text`.

## Expected behavior
- POST `/v1/oa/analyze` with this OA in the body should return **200**.
- The Pydantic Field validator allows `max_length` inclusive, so
  exactly-at-limit must be accepted.
- The `max_body_size_middleware` Content-Length cap is 100MB by default,
  far above 5MB, so the middleware does not interfere.

This is the upper bound — anything larger must 422 (see
`oversized_oa_6mb.txt`).

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_oversized_oa_5mb_accepted`
