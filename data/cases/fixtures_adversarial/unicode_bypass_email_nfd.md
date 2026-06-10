# unicode_bypass_email_nfd.txt

## What it tests
NFD-decomposed accent characters in an email address that should still
be redacted post-normalization. The fixture intentionally writes the
accented character as a base letter + combining acute accent (U+0301)
so a regex like `[a-zA-Z0-9._%+-]+@...` mis-skips the email entirely.

The fixture is intentionally distributed as a Python-escaped form
(`ale&#769;xis-patent@...`) so the bytes on disk are exactly what an
attacker would craft; the test reads the raw bytes and passes them
through the redactor.

## Expected behavior (after Phase 2-D NFKC normalize ships)
NFKC composes the base+combining mark into U+00E9 (é). The email regex
upgrade in Phase 2-D should then either (a) recognize Unicode word
chars or (b) treat any string matching the `<local>@<domain>` shape as
sensitive. Either way the email should be redacted.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_nfd_email_redacted`
  (marked `xfail` until Phase 2-D NFKC + Unicode-aware email regex ship)
