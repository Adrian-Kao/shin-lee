# zero_width_chars.txt

## What it tests
Zero-Width Space (U+200B) and Zero-Width Non-Joiner (U+200C) inserted
between digits of phone numbers, email addresses, and patent numbers.
Visually invisible; bytewise they break naive regex patterns like
`\b09\d{2}-\d{3}-\d{3}\b` because the regex engine sees `09<ZWSP>12`
which is not the literal regex match.

## Expected behavior (after Phase 2-D NFKC normalize + zero-width strip)
NFKC alone does NOT strip ZWSP/ZWNJ. The masking module needs an
explicit pre-pass: `re.sub(r'[​-‍﻿]', '', text)` BEFORE
NFKC + regex matching. With that pre-pass:
- `09<ZWSP>12-345-<ZWNJ>678` → `0912-345-678` → matched by `phone_tw`.
- `alice<ZWSP>@example-ip.com` → `alice@example-ip.com` → matched by `email`.

## Expected behavior (current state)
Phone and email patterns DO NOT fire, raw PII passes through. This is
the documented Phase 2-D gap.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_zero_width_chars_redacted_around`
  (marked `xfail` until Phase 2-D ships the zero-width strip + NFKC
  normalize fix)
