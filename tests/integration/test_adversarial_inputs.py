"""Integration tests for adversarial inputs.

These tests load fixtures from ``data/cases/fixtures_adversarial/`` and
exercise the gateway with realistic attacker inputs:
  - Unicode bypass (fullwidth digits, NFD decomposition, zero-width chars)
  - Mixed-script PII
  - Prompt injection (direct + indirect)
  - Oversized OA (5MB / 6MB boundary)
  - Cyrillic homoglyph attack
  - Confidential case marker (-CONF routing)
  - Malformed PDFs (password-protected, scan-only)

Some tests target functionality that is documented in
``docs/SECURITY_AUDIT.md`` as a Phase 2-D Chunk D deliverable (NFKC
normalize, zero-width strip, Unicode-aware regex). For those, the test
is marked ``xfail`` so it surfaces the gap without breaking CI; once
Phase 2-D ships and `unicodedata.normalize` appears in
``backend/gateway/masking.py``, remove the xfail marker.

The fixture directory layout is documented in
``data/cases/README.md``. Binary fixtures (PDFs) are regenerated via
``python scripts/generate_test_data.py`` — see that script's docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "cases" / "fixtures_adversarial"
_ALICE_CASE = "CASE-2025-001"
_PDF_MIME = "application/pdf"


def _masking_src() -> str:
    """Snapshot of backend/gateway/masking.py source.

    Used to drive xfail/skip decisions without hard-coding a branch name.
    Read-only: never imports masking, so import order is unaffected.
    """
    mask_path = Path(__file__).resolve().parents[2] / "backend" / "gateway" / "masking.py"
    try:
        return mask_path.read_text(encoding="utf-8")
    except OSError:
        return ""


_MASKING_SRC = _masking_src()
_NFKC_LANDED = ("unicodedata.normalize" in _MASKING_SRC) or ("NFKC" in _MASKING_SRC)
# Zero-width strip is a SEPARATE pre-pass that has to be added on top of
# NFKC (NFKC does NOT fold U+200B). We probe for the explicit codepoints
# or the canonical regex character class for zero-width invisibles.
_ZW_STRIP_LANDED = (
    "200B" in _MASKING_SRC
    or "200b" in _MASKING_SRC
    or "zero_width" in _MASKING_SRC.lower()
    or "​" in _MASKING_SRC
)
_NFKC_REASON = (
    "Phase 2-D Chunk D NFKC normalize not yet in main HEAD — "
    "see docs/SECURITY_AUDIT.md M-6. Remove xfail once "
    "unicodedata.normalize appears in backend/gateway/masking.py."
)
_ZW_REASON = (
    "Zero-width strip pre-pass not yet in main HEAD. NFKC alone does "
    "not fold U+200B / U+200C; the redactor needs an explicit "
    "re.sub(r'[\\u200B-\\u200D\\uFEFF]', '', text) step BEFORE NFKC."
)


def _load_fixture(name: str) -> str:
    """Read a UTF-8 text fixture."""
    path = _FIXTURES_DIR / name
    return path.read_text(encoding="utf-8")


def _load_fixture_bytes(name: str) -> bytes:
    """Read a binary fixture (PDF)."""
    path = _FIXTURES_DIR / name
    return path.read_bytes()


# ---------------------------------------------------------------------------
# 1. Fullwidth phone digits — M-6 bypass
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    not _NFKC_LANDED,
    reason=_NFKC_REASON,
    strict=False,
)
def test_fullwidth_phone_redacted(gateway_client, alice_token):
    """Fullwidth digits ０９１２-345-678 must be redacted after NFKC.

    With NFKC normalize in masking.py, the fullwidth digits get composed
    to ASCII 0912-345-678 before regex matching, so the phone_tw rule
    fires. Without that fix, the raw fullwidth digits pass through and
    the assertion below fails — hence the xfail.
    """
    text = _load_fixture("unicode_bypass_phone_fullwidth.txt")
    resp = gateway_client.post(
        "/v1/redact",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": text},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    redacted = body["redacted"]
    # Original fullwidth digits must NOT survive after the redactor runs.
    assert "０９１２" not in redacted, (
        "fullwidth phone digits survived redaction — NFKC normalize missing"
    )
    assert "０９８７" not in redacted
    # phone_tw rule should fire at least once.
    assert "phone_tw" in body["rules_triggered"], body


# ---------------------------------------------------------------------------
# 2. Prompt injection — basic (system tag) does not leak
# ---------------------------------------------------------------------------
def test_prompt_injection_basic_does_not_leak_system_prompt(
    gateway_client, alice_token, patched_ai_engine
):
    """Direct injection via [SYSTEM] tag must not survive into the draft.

    Mock LLM path: the parser ignores the injection (keyword-based)
    and the drafts use a canned response. The injection strings should
    never appear in `response.drafts[*].draft_text`.
    """
    oa_text = _load_fixture("prompt_injection_basic.txt")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": oa_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "TW202617461",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    drafts = body.get("drafts", [])
    assert len(drafts) >= 1, "expected at least one draft"
    for d in drafts:
        text = d.get("draft_text", "")
        assert "[SYSTEM]" not in text, "system tag leaked into draft"
        assert "maintenance mode" not in text.lower(), "injection phrase leaked"
        assert "PWNED" not in text, "injection sentinel leaked"
        # Defensive: model name + system prompt key phrases.
        assert "system prompt" not in text.lower(), "model leaked the meta phrase"


# ---------------------------------------------------------------------------
# 3. Oversized OA (5MB) — at the limit, must be accepted
# ---------------------------------------------------------------------------
def test_oversized_oa_5mb_accepted(gateway_client, alice_token, patched_ai_engine):
    """Exactly _MAX_OA_TEXT_CHARS (5 MiB) must pass Pydantic validation.

    This is the boundary case for the per-field cap. The body MUST pass
    the Pydantic ``max_length`` check (no 422). Downstream the orchestrator
    has a separate prompt-too-large rule (32 K chars by default) which is
    what protects the LLM tokeniser, and that can legitimately reject the
    5 MiB blob with 413 — that's NOT what this test gates.

    What we assert: the body-level cap is exactly 5 MiB, not 4 MiB.
    """
    oa_text = _load_fixture("oversized_oa_5mb.txt")
    assert len(oa_text) == 5 * 1024 * 1024, f"fixture size drift: {len(oa_text)}"
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": oa_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "TW202617461",
        },
    )
    # 422 here = Pydantic Field rejected the input → cap is < 5 MiB,
    # which contradicts _MAX_OA_TEXT_CHARS. That's the regression we
    # care about. 200 (full pipeline ran) or 413 (downstream
    # prompt-too-large) are both acceptable — the input validator did
    # its job.
    assert resp.status_code != 422, f"5 MiB OA rejected by Pydantic Field cap: {resp.text[:300]}"
    assert resp.status_code in (200, 413), resp.text


# ---------------------------------------------------------------------------
# 4. Oversized OA (6MB) — over the limit, must 422
# ---------------------------------------------------------------------------
def test_oversized_oa_6mb_rejected_422(gateway_client, alice_token):
    """6 MiB OA must be rejected with Pydantic 422 string_too_long."""
    oa_text = _load_fixture("oversized_oa_6mb.txt")
    assert len(oa_text) == 6 * 1024 * 1024, f"fixture size drift: {len(oa_text)}"
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": oa_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "TW202617461",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.text.lower()
    assert "string_too_long" in detail or "oa_text" in detail


# ---------------------------------------------------------------------------
# 5. Cyrillic homoglyph attack — must not crash
# ---------------------------------------------------------------------------
def test_cyrillic_homoglyph_classified_safely(gateway_client, alice_token, patched_ai_engine):
    """Сlaims with Cyrillic С should classify safely (graceful degradation).

    Either:
      (a) the mock parser falls back to its default rejection (acceptable),
      (b) the parser returns 0 rejections (also acceptable),
      (c) the redactor refuses with a 4xx (also acceptable).
    The ONLY unacceptable outcome is a 500 server error or a Python
    exception leaking into the response body.
    """
    oa_text = _load_fixture("cyrillic_homoglyph_attack.txt")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={
            "oa_text": oa_text,
            "case_id": _ALICE_CASE,
            "target_patent_no": "TW202617461",
        },
    )
    assert resp.status_code < 500, (
        f"Cyrillic homoglyph caused server error: {resp.status_code} {resp.text[:300]}"
    )
    # If it succeeded, the response shape should be valid (well-formed JSON).
    if resp.status_code == 200:
        body = resp.json()
        assert "oa" in body, body
        assert "rejections" in body["oa"], body


# ---------------------------------------------------------------------------
# 6. Zero-width chars — phone/email should still get caught after pre-strip
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    not _ZW_STRIP_LANDED,
    reason=_ZW_REASON,
    strict=False,
)
def test_zero_width_chars_redacted_around(gateway_client, alice_token):
    """Phone/email with U+200B/U+200C interleaved must still be redacted.

    Defense requires masking.py to strip zero-width chars BEFORE applying
    NFKC normalize + regex match. Without the strip the regex sees a
    broken-up digit sequence and the phone_tw rule does not fire.
    """
    text = _load_fixture("zero_width_chars.txt")
    resp = gateway_client.post(
        "/v1/redact",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": text},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At least one PII-class rule must fire. (The fixture contains both
    # an email and a TW phone, so both rule ids should be present.)
    triggered = body["rules_triggered"]
    assert "phone_tw" in triggered or "email" in triggered, body


# ---------------------------------------------------------------------------
# 7. Confidential case marker — upload must 403
# ---------------------------------------------------------------------------
def test_confidential_case_upload_rejected_403(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """Uploading to a -CONF case must be refused at the gateway edge.

    The gate is independent of the file contents: the X-Case-Id suffix
    `-CONF` alone is enough to trigger 403. We grant alice access to a
    -CONF case_id via the monkeypatched ACL so the rejection is the
    EDGE rule (not the ACL rule) — otherwise the two failure modes would
    overlap and we couldn't tell which check fired.
    """
    from backend.gateway import auth as auth_mod

    conf_case_id = "CASE-2025-001-CONF"
    monkeypatch.setitem(
        auth_mod._CASE_ACL,
        "alice",
        auth_mod._CASE_ACL["alice"] | {conf_case_id},
    )

    pdf_bytes = _load_fixture_bytes("pdf_scan_only_no_text.pdf")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": conf_case_id,
        },
        files={"file": ("conf.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 403, resp.text
    detail = resp.text.lower()
    assert "confidential" in detail


# ---------------------------------------------------------------------------
# 8. Password-protected PDF — 422
# ---------------------------------------------------------------------------
def test_password_protected_pdf_returns_422(gateway_client, alice_token, patched_ai_engine):
    """An AES-encrypted PDF cannot be opened; gateway should 422, not 500."""
    pdf_bytes = _load_fixture_bytes("pdf_password_protected.pdf")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("encrypted.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.text.lower()
    assert "password" in detail


# ---------------------------------------------------------------------------
# 9. Scan-only PDF — Vision OCR mock fallback
# ---------------------------------------------------------------------------
def test_scan_only_pdf_triggers_vision_ocr_mock(gateway_client, alice_token, patched_ai_engine):
    """A PDF with no text layer must trigger Vision OCR for every page."""
    pdf_bytes = _load_fixture_bytes("pdf_scan_only_no_text.pdf")
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        files={"file": ("scan.pdf", pdf_bytes, _PDF_MIME)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Both pages must have gone through OCR (the fixture has no text layer).
    # NB: ocr_pages_used is 0-indexed in the current implementation.
    assert body["page_count"] == 2, body
    assert sorted(body["ocr_pages_used"]) == [0, 1], body
    # Mock OCR placeholder must be present in the joined text.
    assert "MOCK OCR" in body["extracted_text"], body["extracted_text"][:200]


# ---------------------------------------------------------------------------
# 10. Mixed-script PII — all expected rules fire
# ---------------------------------------------------------------------------
def test_mixed_script_pii_multiple_rules_fire(gateway_client, alice_token):
    """A single OA containing zh+en+ja PII should trigger multiple rules.

    We assert a SUBSET match (at least email + phone + apex_case_no) so
    the test is robust to additional rules being added later. Note this
    test does NOT depend on Phase 2-D since the PII is in ASCII form
    even though it's surrounded by mixed scripts.
    """
    text = _load_fixture("mixed_script_pii.txt")
    resp = gateway_client.post(
        "/v1/redact",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Case-Id": _ALICE_CASE,
        },
        json={"text": text},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    triggered = set(body["rules_triggered"])
    # These rules MUST fire — they each match ASCII PII patterns
    # explicitly present in the fixture, no Unicode tricks involved.
    assert "email" in triggered, body
    assert "phone_tw" in triggered, body
    assert "apex_case_no" in triggered, body
    # Redaction should have removed the literal email + phone strings.
    redacted = body["redacted"]
    assert "john.smith@apex-ip.com" not in redacted
    assert "0912-345-678" not in redacted
    assert "APEX-2025-12345" not in redacted
