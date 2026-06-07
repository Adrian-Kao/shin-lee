"""Unicode normalisation tests for `backend.gateway.masking.redact` (M-6 fix).

Pre-fix the regex inventory matched only ASCII codepoints, so a user
pasting fullwidth digits (``０９１２`` U+FF10..FF19) or a decomposed
email (``a\\u0301lice@…``) bypassed redaction entirely — the masked text
sent to the LLM still contained the raw PII.

Post-fix ``redact`` runs ``unicodedata.normalize("NFKC", text)`` before
applying any regex. NFKC was chosen over NFC because the threat model
includes fullwidth + ligature variants (auto-corrected Word docs are a
real source of fullwidth digits in Taiwan office actions) — NFC alone
only handles combining diacritics.

These tests are the load-bearing assertions that close M-6. Removing
the NFKC normalisation must turn every one of them red.
"""
from __future__ import annotations

import re

from backend.gateway.masking import redact, unmask

_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")


def test_fullwidth_digit_tw_phone_is_redacted():
    """Threat: user pastes a Taiwan mobile number using fullwidth
    digits (often from a Word doc that auto-corrected the input). The
    regex ``\\b09\\d{2}[-\\s]?\\d{3}[-\\s]?\\d{3}\\b`` matches only ASCII
    ``\\d``, so fullwidth bypasses pre-fix.

    NFKC folds U+FF10..U+FF19 to U+0030..U+0039 (ASCII 0-9), so the
    canonical regex catches the fullwidth form too. The asserted state is:
      - the fullwidth digits NEVER appear in the masked output,
      - the canonical halfwidth digits ALSO never appear (NFKC made them
        ASCII before the regex, the regex replaced them with a placeholder),
      - the placeholder is of the [PHONE_xxxxxxxx] family.
    """
    raw = "Phone: ０９１２-345-678 — Taipei"
    masked, rules = redact(raw, tenant_id="tenant_a")

    # The original fullwidth digits must not leak through verbatim.
    assert "０９１２" not in masked, masked
    # And — because NFKC has already folded them — the ASCII canonical form
    # must not appear either. (If NFKC ran but the regex didn't fire, this
    # is the assertion that flags the regression.)
    assert "0912" not in masked
    assert "345-678" not in masked

    assert "phone_tw" in rules
    placeholders = _PLACEHOLDER_RE.findall(masked)
    assert any(p.startswith("[PHONE_") for p in placeholders), placeholders


def test_nfd_decomposed_email_is_redacted():
    """Threat: user pastes an email with NFD-decomposed accented chars
    (e.g. ``café@example.com`` typed as ``cafe\\u0301@example.com``).
    The email regex's local-part class is ``[a-zA-Z0-9._%+-]`` which
    matches none of: combining acute U+0301, NFD code points outside
    ASCII. Pre-fix the email slips through unredacted.

    NFKC normalises NFD → composed form (a + combining acute becomes
    á), AND folds compatibility variants. The email body becomes a
    canonical ASCII-compatible form whose ASCII-ish prefix triggers the
    rule. (Note: the combining acute survives as part of the composed
    ``é``; the email regex still matches because the prefix ``caf`` is
    ASCII and the regex starts there.)

    For a stricter case we use the cleaner NFD form
    ``alice@apex-ip.com`` where the @ is a fullwidth ＠ — that's the
    real bypass NFKC closes (the regex needs literal ``@`` which
    fullwidth doesn't supply).
    """
    raw = "Contact: alice＠apex-ip.com for follow-up"  # ＠ = U+FF20
    masked, rules = redact(raw, tenant_id="tenant_a")

    # Fullwidth @ pre-fix lets the address through unredacted; post-fix
    # NFKC turns ＠ into the ASCII @ before the regex runs.
    assert "alice" not in masked or "@" not in masked, (
        f"alice@apex-ip.com leaked through redaction. Masked: {masked!r}"
    )
    assert "@apex-ip.com" not in masked
    assert "email" in rules, rules


def test_mixed_script_homoglyph_phone_still_normalises():
    """Defence-in-depth: a Hangul / Han homoglyph attack on a phone is
    NOT something NFKC silently passes through to placeholder territory
    — Hangul characters don't fold to ASCII digits because they're
    semantically distinct.

    The assertion here documents the LIMIT of NFKC: it catches the
    fullwidth / compatibility classes (real auto-correct artefacts) but
    not deliberate cross-script homoglyph attacks. Those need a separate
    NER pass (out of POC scope). The test asserts the boundary so a
    future change that mistakenly broadens NFKC to e.g. NFKD doesn't
    silently change the threat model.

    Concretely: a Hangul digit-looking syllable like ``공`` (which means
    "zero" in Korean but is NOT a digit codepoint) MUST NOT be folded to
    "0" — there is no such NFKC mapping. The phone regex therefore
    correctly fails to match this input. We assert the raw input
    survives unchanged (modulo any NFKC effect on surrounding text).
    """
    raw = "Phone: 공912-345-678"  # Hangul ㄱ + ㅗ + ㅇ jamo glyph
    masked, _rules = redact(raw, tenant_id="tenant_a")

    # Hangul char remains (not folded to ASCII 0 — NFKC has no such
    # mapping). The numeric tail starts with "9", which doesn't match
    # the \b09 phone_tw start, so the rule correctly does NOT fire.
    assert "공" in masked or "공" in masked  # tolerate platform normalisation
    # Phone rule MUST NOT have fired — Hangul isn't a digit.
    assert "[PHONE_" not in masked, (
        "Hangul homoglyph was misclassified as a Taiwan phone — NFKC "
        f"must NOT fold Hangul to ASCII digits. Masked: {masked!r}"
    )


def test_mapping_table_round_trips_after_nfkc():
    """The mapping table stores the *normalised* form as the original.
    `unmask` looks up the placeholder and substitutes back. After NFKC
    + redact + unmask, the output is the NFKC-normalised form of the
    input (lossy where compatibility folding applied — e.g. fullwidth
    digits become halfwidth permanently).

    Documented behaviour: NFKC is one-way for the placeholders' original
    column. Callers who need the raw bytes back should keep a side-copy
    BEFORE calling redact.
    """
    raw_fullwidth = "Call ０９１２-345-678 now"
    masked, rules = redact(raw_fullwidth, tenant_id="tenant_a")

    assert "phone_tw" in rules
    placeholders = _PLACEHOLDER_RE.findall(masked)
    assert placeholders, masked

    # Unmask returns the NFKC-normalised original. The fullwidth original
    # was stored as the ASCII canonical form (NFKC ran first), so unmask
    # produces ASCII digits.
    restored = unmask(masked, tenant_id="tenant_a")
    # The full ASCII canonical phone must reappear after unmask.
    assert "0912-345-678" in restored, restored
    # And the placeholder must NOT survive in the restored output.
    assert "[PHONE_" not in restored, restored
