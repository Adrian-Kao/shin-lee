"""Agent A — Day 12A redaction hardening tests.

Covers the production-grade hardening of the redaction / PII "crown jewel":

  1. Zero-width / invisible / bidi-control stripping BEFORE NFKC so PII split
     by U+200B / U+200C / U+2060 / U+FEFF (etc.) is still detected.
  2. Homoglyph / Unicode-confusable folding (Cyrillic + Greek look-alikes,
     confusable punctuation) so cross-script substitution can't bypass the
     ASCII-anchored PII regexes.
  3. Reversibility property: redact() -> unmask() reconstructs the (canonical)
     original for overlapping/adjacent entities, repeated entities, unicode
     text, and entities at string boundaries.
  4. Expanded PII_RULES coverage — TW national ID, ROC 統一編號 (company tax
     ID), passport, phone variants, email, IPv4/IPv6 — with focused TRUE
     POSITIVE *and* TRUE NEGATIVE (no over-redaction of patent prose) cases.

These tests are the load-bearing assertions for the Day 12A masking changes.
The mapping store is isolated per test (autouse fixture) so global on-disk
state never leaks between tests.
"""
from __future__ import annotations

import re
import unicodedata

import pytest

from backend.gateway import masking
from backend.gateway.masking import (
    MaskingStore,
    fold_confusables,
    normalize_for_detection,
    redact,
    strip_zero_width,
    unmask,
)

_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")


@pytest.fixture(autouse=True)
def isolated_module_store(tmp_path, monkeypatch):
    """Point the module-level ``_store`` at a fresh per-test DB so redact/unmask
    never share global on-disk state across tests/runs."""
    fresh = MaskingStore(path=tmp_path / "module_mapping.db")
    monkeypatch.setattr(masking, "_store", fresh)
    return fresh


def _rules(text: str, tenant_id: str = "tenant_a") -> list[str]:
    _redacted, triggered = redact(text, tenant_id)
    return triggered


# ===========================================================================
# 1. Zero-width / invisible character stripping
# ===========================================================================

# (codepoint name, char) pairs — each is interleaved INSIDE a PII token.
_ZW_CHARS = [
    ("ZWSP", "​"),
    ("ZWNJ", "‌"),
    ("ZWJ", "‍"),
    ("WORD_JOINER", "⁠"),
    ("BOM_ZWNBSP", "﻿"),
    ("SOFT_HYPHEN", "­"),
    ("LRM", "‎"),
]


@pytest.mark.parametrize("name,zw", _ZW_CHARS)
def test_zero_width_split_phone_still_redacted(name, zw):
    """A TW mobile number split by an invisible char must still be redacted."""
    raw = f"call 09{zw}12{zw}-345{zw}-678 today"
    masked, triggered = redact(raw, "tenant_a")
    assert "phone_tw" in triggered, (name, masked)
    # The original digit run must NOT survive in any form.
    assert "0912" not in masked, (name, masked)
    assert zw not in masked, f"{name}: zero-width char survived into output"


@pytest.mark.parametrize("name,zw", _ZW_CHARS)
def test_zero_width_split_email_still_redacted(name, zw):
    raw = f"mail alice{zw}@example{zw}-ip.com please"
    masked, triggered = redact(raw, "tenant_a")
    assert "email" in triggered, (name, masked)
    assert "@example-ip.com" not in masked, (name, masked)


def test_strip_zero_width_is_pure_and_removes_all():
    raw = "a​b‌c‍d⁠e﻿f­g‎h‮i"
    out = strip_zero_width(raw)
    assert out == "abcdefghi", repr(out)


def test_zero_width_only_text_is_emptyish():
    """Text that is ONLY invisibles collapses to empty after the strip."""
    raw = "​‌‍⁠﻿"
    assert strip_zero_width(raw) == ""


def test_zero_width_does_not_remove_legitimate_whitespace():
    """Ordinary spaces / newlines / tabs are NOT zero-width and must survive."""
    raw = "line one\n\tline two   end"
    assert strip_zero_width(raw) == raw


# ===========================================================================
# 2. Homoglyph / confusable folding
# ===========================================================================

def test_cyrillic_homoglyph_email_redacted():
    """jоhn@apex-ip.com with a Cyrillic 'о' (U+043E) must be fully redacted."""
    raw = "applicant email: jоhn@apex-ip.com"  # о = Cyrillic
    masked, triggered = redact(raw, "tenant_a")
    assert "email" in triggered, masked
    # The whole local part is folded to ASCII and replaced — neither the
    # Cyrillic nor the ASCII fragment should remain attached to the domain.
    assert "@apex-ip.com" not in masked, masked


def test_greek_homoglyph_email_redacted():
    """An email whose letters are Greek look-alikes folds + redacts."""
    # 'support' with Greek ο/ρ, then real ASCII domain.
    raw = "reach suppοt@Εxample.com"  # ο, Ε homoglyphs
    masked, triggered = redact(raw, "tenant_a")
    assert "email" in triggered, masked


def test_confusable_at_sign_folds():
    """Small commercial at ﹫ (U+FE6B) folds to @ so the email regex fires."""
    raw = "alice﹫apex-ip.com"
    masked, triggered = redact(raw, "tenant_a")
    assert "email" in triggered, masked


def test_fold_confusables_is_scoped_does_not_touch_cjk():
    """CJK and ordinary ASCII must be untouched by the confusable fold."""
    raw = "經濟部智慧財產局 Claim 1 normal ascii"
    assert fold_confusables(raw) == raw


def test_fold_confusables_maps_cyrillic_to_latin():
    # Cyrillic А В С Е Н О Р Т Х → Latin
    raw = "АВСЕНОРТХ"
    assert fold_confusables(raw) == "ABCEHOPTX"


def test_homoglyph_does_not_fabricate_pii_in_clean_text():
    """Folding must not turn benign patent prose into a false PII hit."""
    raw = "The Claims recite a method (see US10876543)."
    assert _rules(raw) == []


# ===========================================================================
# 3. normalize_for_detection ordering
# ===========================================================================

def test_normalize_pipeline_order():
    """strip → fold → NFKC composes: fullwidth digits AND a zero-width split
    AND a homoglyph all collapse to the canonical ASCII form."""
    # fullwidth 0 (U+FF10) + ZWSP + Cyrillic homoglyphs in a word
    raw = "０​9 cаll"  # '09' (fullwidth 0 + zwsp + 9) + 'call'
    out = normalize_for_detection(raw)
    assert out == "09 call", repr(out)


def test_normalize_is_idempotent():
    raw = "Phone ０９１２-345-678 e‌mail aоlice@x.com"
    once = normalize_for_detection(raw)
    twice = normalize_for_detection(once)
    assert once == twice


# ===========================================================================
# 4. Reversibility property: redact -> unmask reconstructs the canonical form
# ===========================================================================
#
# Invariant: unmask(redact(x)) == normalize_for_detection(x) for any input x.
# The mapping store holds the CANONICAL (normalised) original, so the round-trip
# returns the canonical spelling (documented lossy behaviour for fullwidth /
# homoglyph / zero-width inputs). For already-canonical ASCII input it is the
# identity.

_ROUND_TRIP_CASES = [
    # plain, already-canonical
    "Contact john.doe@example.com or 0912-345-678 re APEX-2024-00123.",
    # adjacent entities (email immediately followed by phone, no separator)
    "john.doe@example.com0912-345-678",
    # overlapping-ish: case ref touching a client code
    "APEX-2025-0314CL-EVCO12",
    # repeated identical entity (stable placeholder reused)
    "mail a@b.com then again a@b.com and a@b.com",
    # entity at the very start of the string
    "john.doe@example.com is the contact",
    # entity at the very end of the string
    "the contact is john.doe@example.com",
    # entity is the entire string
    "0912-345-678",
    # unicode prose surrounding ASCII PII
    "聯絡 john.doe@example.com 電話 0912-345-678 謝謝",
    # multiple distinct rule families interleaved
    "ID A123456789, SSN 123-45-6789, IP 10.0.0.1, mail x@y.io",
    # empty string
    "",
    # no PII at all (identity for canonical ASCII)
    "Claim 1 is rejected under 35 U.S.C. 103 over US10876543.",
]


@pytest.mark.parametrize("raw", _ROUND_TRIP_CASES)
def test_redact_unmask_reconstructs_canonical(raw):
    masked, _triggered = redact(raw, "tenant_a")
    restored = unmask(masked, "tenant_a")
    expected = normalize_for_detection(raw)
    assert restored == expected, (
        f"round-trip mismatch\n raw={raw!r}\n masked={masked!r}\n "
        f"restored={restored!r}\n expected={expected!r}"
    )
    # No placeholder may survive the un-redaction.
    assert not _PLACEHOLDER_RE.search(restored), restored


def test_round_trip_for_unicode_input_is_canonical():
    """A fullwidth + zero-width + homoglyph input reconstructs to its
    NFKC-canonical, stripped, folded form (intended lossy contract)."""
    # 'аlice' has a Cyrillic leading 'а' (U+0430) → folds to ASCII 'alice'.
    raw = "Call ０９１2​-345-678 mail аlice@x.com"
    masked, _ = redact(raw, "tenant_a")
    restored = unmask(masked, "tenant_a")
    assert restored == normalize_for_detection(raw)
    assert restored == "Call 0912-345-678 mail alice@x.com"


def test_repeated_entity_reuses_single_placeholder():
    raw = "a@b.com / a@b.com / a@b.com"
    masked, _ = redact(raw, "tenant_a")
    placeholders = set(re.findall(r"\[EMAIL_[0-9A-F]{8}\]", masked))
    assert len(placeholders) == 1, masked
    assert unmask(masked, "tenant_a") == raw


def test_adjacent_entities_both_reversible():
    raw = "john.doe@example.com0912-345-678"
    masked, triggered = redact(raw, "tenant_a")
    # both rule families fired
    assert "email" in triggered
    restored = unmask(masked, "tenant_a")
    assert restored == raw


def test_round_trip_cross_tenant_does_not_reconstruct():
    """A placeholder minted for tenant_a must NOT unmask under tenant_b
    (tenant isolation of the reversible map)."""
    raw = "mail alice@example.com"
    masked_a, _ = redact(raw, "tenant_a")
    # tenant_b has no mapping row for tenant_a's placeholder -> placeholder kept.
    restored_b = unmask(masked_a, "tenant_b")
    assert restored_b == masked_a, restored_b
    assert "alice@example.com" not in restored_b


# ===========================================================================
# 5. Expanded PII coverage — TRUE POSITIVES
# ===========================================================================

@pytest.mark.parametrize(
    "text,expected_rule",
    [
        ("email me at jane.doe@example.com", "email"),
        ("mobile 0912-345-678", "phone_tw"),
        ("mobile 0912345678", "phone_tw"),
        ("(02)23766050", "phone_tw_landline"),
        ("02-2376-6050", "phone_tw_landline"),
        ("(07)123-4567", "phone_tw_landline"),
        ("call (415) 555-2381", "phone_us"),
        ("call +886 912 345 678", "phone_intl"),
        ("身分證 A123456789", "tw_id"),
        ("統一編號：23766050", "tw_company_tax_id"),
        ("統編 12345678", "tw_company_tax_id"),
        ("Tax ID: 04595257", "tw_company_tax_id"),
        ("護照號碼：123456789", "passport"),
        ("Passport No: AB1234567", "passport"),
        ("SSN 123-45-6789", "ssn"),
        ("host 192.168.1.100", "ipv4"),
        ("gw 10.0.0.1 here", "ipv4"),
        ("v6 2001:0db8:85a3:0000:0000:8a2e:0370:7334", "ipv6"),
        ("compressed 2001:db8::8a2e:370:7334", "ipv6"),
    ],
)
def test_pii_true_positives(text, expected_rule):
    assert expected_rule in _rules(text), (text, _rules(text))


def test_company_tax_id_redacts_the_digits():
    masked, _ = redact("公司統一編號：23766050 已登記", "tenant_a")
    assert "23766050" not in masked


# ===========================================================================
# 6. Expanded PII coverage — TRUE NEGATIVES (no over-redaction of patent prose)
# ===========================================================================

_PROSE_NO_REDACT = [
    "Claim 1 is rejected under 35 U.S.C. § 103.",
    "Claims 1-3 are unpatentable.",
    "See FIG. 3 and FIG. 12 for the embodiment.",
    "Cited art: US10876543, TW201912345, JP2020112233, EP3654321.",
    "本案請求項 1 有不符 專利法第22條第2項 之情形。",
    "The reference number 23766050 appears in paragraph [0042].",  # bare 8-digit
    "Publication US 2024/0123456 A1 discloses a widget.",
    "Application No. 17/123,456 filed 2024-05-29.",
    "Section 102(a)(1) and 35 USC 112.",
    "Figure 4, element 402, connects to element 404.",
    "The value ranges from 0.5 to 10.0 in increments.",
    "claim 20 depends from claim 1",
]


@pytest.mark.parametrize("prose", _PROSE_NO_REDACT)
def test_patent_prose_not_over_redacted(prose):
    triggered = _rules(prose)
    assert triggered == [], (prose, triggered)


def test_bare_eight_digit_number_not_tax_id():
    """An 8-digit number WITHOUT a tax-id marker must NOT be redacted."""
    assert "tw_company_tax_id" not in _rules("serial 23766050 ships tomorrow")


def test_patent_number_not_passport():
    """Patent / publication numbers must not trip the passport rule."""
    assert "passport" not in _rules("US10876543 and TW201912345")


def test_claim_range_not_phone():
    assert _rules("claims 1-3 and 5-9 are rejected") == []
