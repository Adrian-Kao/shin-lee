# unicode_bypass_phone_fullwidth.txt

## What it tests
Fullwidth (East Asian) digit bypass of the `phone_tw` redaction rule.
The `MaskRule.pattern` for phone_tw is `\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b`
which matches ASCII digits only. Fullwidth digits `０-９` (U+FF10–U+FF19)
are visually identical phone numbers but do NOT match the pattern.

## Expected behavior (after Phase 2-D NFKC normalize ships)
The redactor should NFKC-normalize the input before regex matching, at
which point `０９１２-345-678` becomes `0912-345-678` and IS redacted.

## Expected behavior (current state — no NFKC normalize)
The fullwidth phone numbers will NOT be redacted (rule does not fire),
and the raw digits will be present in the redacted output. This is a
documented gap (security audit finding M-6).

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_fullwidth_phone_redacted`
  (marked `xfail` until Phase 2-D NFKC normalize lands in
  `backend/gateway/masking.py`)
