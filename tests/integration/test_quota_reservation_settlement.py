"""P1-1 regression — the 13I atomic-reserve contract must be SETTLED on every
analyze exit path (review finding, Day 14).

``rate_limit.check_quotas()`` *increments* the counters as an atomic
reservation; ``record_usage(reserved_tokens=...)`` reconciles to true spend.
The original ``main.py`` integration discarded the reservation handle, so:

  * success      — counted reservation + actual (~1.9x burn per analyze)
  * cache hit    — reservation never released (free requests drained quota)
  * error        — reservation stranded (failed requests drained quota)

Each test reads the user-daily counter via ``GET /v1/quota`` before/after and
asserts the counter moved by exactly the expected amount, not estimate+actual.
"""

from __future__ import annotations

_CASE = "CASE-2025-001"  # alice has ACL


def _daily_used(client, token) -> int:
    resp = client.get("/v1/quota", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_daily_used"]


def _analyze(client, token, oa_text, **overrides):
    payload = {
        "oa_text": oa_text,
        "case_id": _CASE,
        "target_patent_no": "US17000050",
        **overrides,
    }
    return client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def test_success_counts_actual_not_reservation_plus_actual(
    gateway_client, alice_token, patched_ai_engine
):
    """After one successful analyze the counter delta equals the ACTUAL token
    usage reported in cost_meta — not actual + the pre-call estimate."""
    oa_text = "Quota settlement success-path OA text, unique per run aaa."
    before = _daily_used(gateway_client, alice_token)

    resp = _analyze(gateway_client, alice_token, oa_text)
    assert resp.status_code == 200, resp.text
    cost = resp.json()["cost_meta"]
    actual = cost["prompt_tokens"] + cost["completion_tokens"]

    delta = _daily_used(gateway_client, alice_token) - before
    # The estimate is len(oa_text)//3 ≈ 19; if the reservation leaked the
    # delta would be actual + estimate. Exact equality is the contract.
    assert delta == actual, f"counter moved {delta}, actual spend {actual} — reservation leaked"


def test_cache_hit_consumes_zero_quota(gateway_client, alice_token, patched_ai_engine):
    """A cache hit does no LLM work; its reservation must be released in full
    so the second identical request costs 0 tokens."""
    oa_text = "Quota settlement cache-path OA text, identical both calls bbb."
    r1 = _analyze(gateway_client, alice_token, oa_text)
    assert r1.status_code == 200, r1.text

    before = _daily_used(gateway_client, alice_token)
    r2 = _analyze(gateway_client, alice_token, oa_text)
    assert r2.status_code == 200, r2.text

    delta = _daily_used(gateway_client, alice_token) - before
    assert delta == 0, f"cache hit burned {delta} quota tokens"


def test_error_path_releases_reservation(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    """If orchestration explodes after the reserve, the reservation must be
    released — failed requests must not drain the day's quota."""
    from backend.gateway import main as gateway_main

    async def _boom(*args, **kwargs):
        raise RuntimeError("orchestrator down (injected)")

    monkeypatch.setattr(gateway_main, "orchestrate_analysis", _boom)

    oa_text = "Quota settlement error-path OA text, unique per run ccc."
    before = _daily_used(gateway_client, alice_token)

    # TestClient re-raises unhandled server exceptions (it does not wrap them
    # in a 500 response) — the request still ran the full except/finally path.
    import pytest

    with pytest.raises(RuntimeError, match="orchestrator down"):
        _analyze(gateway_client, alice_token, oa_text)

    delta = _daily_used(gateway_client, alice_token) - before
    assert delta == 0, f"failed request stranded {delta} reserved tokens"
