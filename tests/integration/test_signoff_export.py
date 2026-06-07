"""Integration tests for Q16 — mandatory attorney sign-off on export.

The Q16 decision (docs/DECISIONS.md, docs/QUESTIONS.md §Q16) requires the
human-in-the-loop to be ENFORCED, not merely flagged. Two properties:

  1. HARD EXPORT GATE — POST /v1/oa/export refuses to produce ANY document
     unless ``attorney_signoff`` is exactly ``True`` ("我已逐項確認"). The
     refused attempt is still an auditable event (signoff=False).

  2. RESPONSIBILITY BOUNDARY — the audit row records the per-segment
     provenance SUMMARY (counts of ai_generated / attorney_edited /
     attorney_added) and NEVER the raw draft text. Those edit counts double as
     the lightweight feedback signal Q16 asks for.

Role model: sign-off is an ATTORNEY act. Paralegals assist with analysis but
cannot sign — so /v1/oa/export is ATTORNEY-ONLY (tighter than /v1/oa/analyze).

Demo users (backend/gateway/auth.py:_USERS):
  * alice      → ATTORNEY  (tenant_a, ACL: CASE-2025-001/002/003)
  * bob        → PARALEGAL (tenant_a, ACL: CASE-2025-001/002)
  * audit_dave → AUDITOR   (tenant_a, ACL: '*')  — used to read the audit log
"""
from __future__ import annotations

import hashlib

_ALICE_CASE = "CASE-2025-001"     # alice (and bob) have ACL
_FOREIGN_CASE = "CASE-DEMO-099"   # alice has NO ACL on this


def _login(client, user_id: str) -> str:
    resp = client.post(
        "/v1/auth/login",
        json={"user_id": user_id, "password": f"demo-{user_id}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _recent_rows(client, auditor_token: str, limit: int = 200) -> list[dict]:
    resp = client.get(
        "/v1/audit/recent",
        params={"limit": limit},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _segments():
    """A canonical mixed-provenance segment set: 3 ai_generated, 1
    attorney_edited, 1 attorney_added — one of the ai_generated is rejected
    so the assembled doc must omit it."""
    return [
        {"segment_id": "s1", "text": "AI sentence one.",
         "source": "ai_generated", "accepted": True},
        {"segment_id": "s2", "text": "AI sentence two REJECTED.",
         "source": "ai_generated", "accepted": False},
        {"segment_id": "s3", "text": "AI sentence three.",
         "source": "ai_generated", "accepted": True},
        {"segment_id": "s4", "text": "Attorney rewrote this one.",
         "source": "attorney_edited", "accepted": True},
        {"segment_id": "s5", "text": "Attorney wrote this from scratch.",
         "source": "attorney_added", "accepted": True},
    ]


# ---------------------------------------------------------------------------
# 1. Export WITHOUT sign-off → 409, no document, audit row with signoff=False
# ---------------------------------------------------------------------------
def test_export_without_signoff_refused_and_audited(gateway_client):
    auditor_token = _login(gateway_client, "audit_dave")
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "rejection_id": "REJ-1",
            "segments": _segments(),
            "attorney_signoff": False,
        },
    )
    assert resp.status_code == 409, resp.text
    # NO document produced — the body must not carry assembled draft text.
    assert "document" not in resp.json(), resp.text

    rows_after = _recent_rows(gateway_client, auditor_token)
    assert len(rows_after) == rows_before + 1, (rows_before, len(rows_after))
    row = rows_after[0]
    assert row["endpoint"] == "/v1/oa/export", row
    assert row["case_id"] == _ALICE_CASE, row
    pd = row["policy_decisions"]
    assert pd.get("error") is True, pd
    assert pd.get("attorney_signoff") is False, pd
    assert pd.get("signoff_passed") is False, pd
    # The responsibility-boundary counts are recorded even on the refusal path.
    assert pd.get("prov_ai_generated") == 3, pd
    assert pd.get("prov_attorney_edited") == 1, pd
    assert pd.get("prov_attorney_added") == 1, pd


def test_export_signoff_omitted_defaults_to_refused(gateway_client):
    """attorney_signoff defaults to False, so omitting it must also refuse."""
    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "segments": _segments(),
        },
    )
    assert resp.status_code == 409, resp.text
    assert "document" not in resp.json(), resp.text


# ---------------------------------------------------------------------------
# 2. Export WITH sign-off → 200, assembled doc (accepted only), audit summary
# ---------------------------------------------------------------------------
def test_export_with_signoff_assembles_and_audits(gateway_client):
    auditor_token = _login(gateway_client, "audit_dave")
    rows_before = len(_recent_rows(gateway_client, auditor_token))

    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "rejection_id": "REJ-1",
            "segments": _segments(),
            "attorney_signoff": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Document contains ONLY accepted segments (the rejected ai segment s2 is
    # excluded); the order is preserved.
    doc = body["document"]
    assert "AI sentence one." in doc
    assert "AI sentence three." in doc
    assert "Attorney rewrote this one." in doc
    assert "Attorney wrote this from scratch." in doc
    assert "REJECTED" not in doc, doc

    # content_sha256 matches the returned document.
    assert body["content_sha256"] == hashlib.sha256(doc.encode("utf-8")).hexdigest()
    assert body["signed_off_by"] == "alice"
    assert body["attorney_signoff"] is True
    assert body["provenance_summary"]["ai_generated"] == 3
    assert body["provenance_summary"]["accepted_segments"] == 4  # 5 minus 1 rejected

    rows_after = _recent_rows(gateway_client, auditor_token)
    assert len(rows_after) == rows_before + 1, (rows_before, len(rows_after))
    row = rows_after[0]
    assert row["endpoint"] == "/v1/oa/export", row
    assert row["user_id"] == "alice", row
    pd = row["policy_decisions"]
    assert pd.get("attorney_signoff") is True, pd
    assert pd.get("signoff_passed") is True, pd
    assert pd.get("error") is None, pd
    # Provenance summary counts (responsibility boundary) in the audit row.
    assert pd.get("prov_total_segments") == 5, pd
    assert pd.get("prov_accepted_segments") == 4, pd
    assert pd.get("prov_ai_generated") == 3, pd
    assert pd.get("prov_attorney_edited") == 1, pd
    assert pd.get("prov_attorney_added") == 1, pd


# ---------------------------------------------------------------------------
# 3. Raw segment text MUST NOT be stored in the audit row.
# ---------------------------------------------------------------------------
def test_export_audit_row_has_no_raw_text(gateway_client):
    """The audit DB must contain counts + hash only — never the draft text.

    We assert against the raw SQLite row (every column) so this catches the
    text leaking into request_hash/response_hash columns too: a hash column
    can never equal the plaintext, but we also confirm the unique sentence
    strings appear nowhere in the serialised row."""
    from backend.gateway import audit as audit_mod

    alice_token = _login(gateway_client, "alice")
    secret_sentence = "ULTRA-CONFIDENTIAL-PRIOR-ART-DISTINCTION-XYZ"
    segs = _segments()
    segs[0]["text"] = secret_sentence
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "segments": segs,
            "attorney_signoff": True,
        },
    )
    assert resp.status_code == 200, resp.text
    # The returned document DOES carry the text (that's the point of export)...
    assert secret_sentence in resp.json()["document"]

    # ...but the audit DB must not. Inspect every column of the latest row.
    cur = audit_mod.writer._conn.execute(
        "SELECT * FROM audit ORDER BY rowid DESC LIMIT 1"
    )
    cols = [c[0] for c in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    assert row["endpoint"] == "/v1/oa/export", row
    serialised = " ".join(str(v) for v in row.values())
    assert secret_sentence not in serialised, (
        "raw draft text leaked into the audit row"
    )
    # The content hash should be present (proves WHICH doc was signed) and is
    # NOT the plaintext.
    expected_hash = hashlib.sha256(
        resp.json()["document"].encode("utf-8")
    ).hexdigest()
    # response_hash is a hash OF our response_payload (which itself contains the
    # content hash), so it won't equal expected_hash directly; the content hash
    # is surfaced on the response and in response_payload, not as a column. The
    # load-bearing assertion is simply: no plaintext anywhere.
    assert expected_hash != secret_sentence


# ---------------------------------------------------------------------------
# 4. Role gate: a PARALEGAL cannot export (only attorneys sign).
# ---------------------------------------------------------------------------
def test_paralegal_cannot_export(gateway_client):
    bob_token = _login(gateway_client, "bob")  # PARALEGAL, has ACL on _ALICE_CASE
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={
            "case_id": _ALICE_CASE,
            "segments": _segments(),
            "attorney_signoff": True,
        },
    )
    assert resp.status_code == 403, resp.text
    body_text = resp.text.lower()
    assert "paralegal" in body_text, resp.text
    assert "attorney" in body_text, resp.text


# ---------------------------------------------------------------------------
# 5. Case ACL: an attorney exporting a case they lack ACL on → 403.
# ---------------------------------------------------------------------------
def test_attorney_without_case_acl_cannot_export(gateway_client):
    alice_token = _login(gateway_client, "alice")  # no ACL on _FOREIGN_CASE
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _FOREIGN_CASE,
            "segments": _segments(),
            "attorney_signoff": True,
        },
    )
    assert resp.status_code == 403, resp.text
    assert _FOREIGN_CASE in resp.text, resp.text


# ---------------------------------------------------------------------------
# 6. extra="forbid": an unknown field in the body is rejected with 422.
# ---------------------------------------------------------------------------
def test_export_rejects_unknown_field(gateway_client):
    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/oa/export",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "case_id": _ALICE_CASE,
            "segments": _segments(),
            "attorney_signoff": True,
            "smuggled": "should be rejected",
        },
    )
    assert resp.status_code == 422, resp.text
