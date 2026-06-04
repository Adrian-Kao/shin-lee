# mixed_script_pii.txt

## What it tests
A single OA block that mixes:
- Traditional Chinese (zh-TW)
- English (en)
- Japanese (ja, hiragana + katakana + kanji)
- PII in multiple forms: TW mobile phone, US phone, two emails,
  Chinese name, romanized name, katakana name, two TW case numbers,
  fullwidth case number, US client code.

The point: a redactor that splits text by language before processing
will leak whichever script it doesn't classify. The PII rules must
fire regardless of surrounding script.

## Expected behavior
- `emai` rule fires twice (john.smith@apex-ip.com + examiner@uspto.gov)
- `phone_tw` rule fires once (0912-345-678)
- `phone_us` rule fires twice ((415) 555-2381 + (02)23766050 — phone_us
  is a "loose" regex that catches the TW landline format too)
- `apex_case_no` (tenant_a dict) fires for `APEX-2025-12345`
- `apex_client_code` (tenant_a dict) fires for `CL-AIX2024`

Total: at least 7 rule hits in the redaction `rules_triggered` list.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_mixed_script_pii_all_rules_fire`
