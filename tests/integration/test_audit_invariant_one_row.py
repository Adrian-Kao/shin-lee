"""Invariant #4 — *exactly one* audit row per gateway request (Q13).

CLAUDE.md §4 invariant #4:

  > Every gateway request writes exactly one audit row. Even cache hits.
  > Even errors.

``test_audit_error_path.py`` proves the *error* half (403/429/5xx/413 each
write one row). This file proves the other two halves that the error file's
docstring asserts but does NOT directly test:

  * **Cache hit writes exactly one row** — a repeated identical analyze request
    is served from cache on the 2nd call, but STILL writes its own audit row
    tagged ``cache_hit=True``. The 1st (miss) writes ``cache_hit=False``.
    Net: two requests → exactly two rows, never one, never three.
  * **Success path writes exactly one row** — a single successful analyze
    writes exactly one row (no double-write from a stray finally).

These are the load-bearing counters: a regression that double-writes on cache
hits (or skips the row entirely) silently corrupts the auditor's request count,
which is the data used to detect abuse.
"""
from __future__ import annotations

_ALICE_CASE = "CASE-2025-001"  # alice has ACL


def _login_auditor(client) -> str:
    return client.post(
        "/v1/auth/login",
        json={"user_id": "audit_dave", "password": "demo-audit_dave"},
    ).json()["token"]


def _recent(client, token, limit=300) -> list[dict]:
    resp = client.get(
        "/v1/audit/recent",
        params={"limit": limit},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _analyze_rows(rows: list[dict], case_id: str) -> list[dict]:
    return [
        r
        for r in rows
        if r["endpoint"] == "/v1/oa/analyze" and r["case_id"] == case_id
    ]


def test_single_success_writes_exactly_one_row(
    gateway_client, alice_token, patched_ai_engine
):
    auditor = _login_auditor(gateway_client)
    case = "CASE-2025-001"
    before = len(_analyze_rows(_recent(gateway_client, auditor), case))

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "oa_text": "Unique OA text for the single-success invariant test.",
            "case_id": case,
            "target_patent_no": "US17000050",
        },
    )
    assert resp.status_code == 200, resp.text

    after = len(_analyze_rows(_recent(gateway_client, auditor), case))
    assert after == before + 1, (before, after)


def test_cache_hit_writes_exactly_one_row_tagged_cache_hit(
    gateway_client, alice_token, patched_ai_engine
):
    """Two byte-identical analyze requests → second is a cache hit → exactly
    TWO audit rows total, the second tagged cache_hit=True."""
    auditor = _login_auditor(gateway_client)
    case = "CASE-2025-001"
    payload = {
        "oa_text": "Cache-invariant OA text — identical across both calls.",
        "case_id": case,
        "target_patent_no": "US17000051",
    }

    before = len(_analyze_rows(_recent(gateway_client, auditor), case))

    r1 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    assert r1.status_code == 200, r1.text

    r2 = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    assert r2.status_code == 200, r2.text

    rows = _analyze_rows(_recent(gateway_client, auditor), case)
    after = len(rows)
    # Exactly two new rows — one per request. Never one (skipped cache row),
    # never three (double-write).
    assert after == before + 2, (before, after)

    # Most-recent-first: row[0] is the cache hit, row[1] is the miss.
    hit_row, miss_row = rows[0], rows[1]
    assert hit_row["policy_decisions"].get("cache_hit") is True, hit_row
    assert miss_row["policy_decisions"].get("cache_hit") is False, miss_row


def test_cache_hit_row_has_no_error_flag(
    gateway_client, alice_token, patched_ai_engine
):
    """A cache hit is a SUCCESS, not an error — its audit row must not carry
    policy_decisions.error (which the auditor uses to filter failures)."""
    auditor = _login_auditor(gateway_client)
    case = "CASE-2025-001"
    payload = {
        "oa_text": "Cache-hit-not-error OA text.",
        "case_id": case,
        "target_patent_no": "US17000052",
    }
    gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=payload,
    )
    rows = _analyze_rows(_recent(gateway_client, auditor), case)
    hit_row = rows[0]
    assert hit_row["policy_decisions"].get("cache_hit") is True, hit_row
    assert hit_row["policy_decisions"].get("error") is not True, hit_row
