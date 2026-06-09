# cyrillic_homoglyph_attack.txt

## What it tests
Cyrillic homoglyphs (С / М / о / с) interleaved with Latin letters in
words that look like "Claims", "U.S.C.", "Main", "john". This breaks:

1. **Keyword-based rejection parsers** — `oa_analyzer.py` and
   `MockLLM._mock_parse` search for literal `Claims` / `35 U.S.C.`
   bytes; the Cyrillic variant skips.
2. **Email redaction** — `jоhn@apex-ip.com` (with Cyrillic о) has a
   letter outside `[a-zA-Z]+`, so the regex does not match.

## Expected behavior
- The endpoint should **not crash**. A graceful degradation (treats
  the text as unparseable Chinese OA or empty rejection list) is fine.
- The redactor SHOULD still flag the email pattern after Phase 2-D
  NFKC normalize is in place + a Unicode-aware [\w] class is used
  (NFKC does NOT fold Cyrillic homoglyphs to Latin — they're distinct
  codepoints — so the email rule needs explicit Unicode-confusables
  handling beyond plain NFKC).

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_cyrillic_homoglyph_classified_safely`
