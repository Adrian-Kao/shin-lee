"""Invariant #7 (CLAUDE.md §4): confidential cases auto-route to the local LLM.

End-to-end through the gateway → orchestrator → AI Engine (all in-process via
the patched_ai_engine fixture). With LLM_MODE=mock the MockLLM tags its
response model as ``<routed-model>-mock``, so the analyze response's
``cost_meta.model`` reveals which tier every call was routed to — letting us
assert the routing decision end-to-end rather than just at the unit level.

Companion unit coverage of the router decision table lives in
tests/unit/test_p0_correctness_fixes.py.
"""

from backend.shared.config import settings

_OA = "Claims 1-3 are rejected under 35 U.S.C. § 103 as obvious over US7654321."


def _analyze(client, token, case_id, patent="US7654321"):
    return client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {token}", "X-Case-Id": case_id},
        json={
            "oa_text": _OA,
            "case_id": case_id,
            "target_patent_no": patent,
            "user_hint": None,
        },
    )


def test_public_case_uses_cloud_reasoning_model(gateway_client, alice_token, patched_ai_engine):
    r = _analyze(gateway_client, alice_token, "CASE-2025-001")
    assert r.status_code == 200, r.text
    model = r.json()["cost_meta"]["model"]
    assert settings.LLM_MODEL_REASONING in model, model
    assert settings.LLM_MODEL_LOCAL not in model, model


def test_confidential_case_routes_to_local_model(
    gateway_client, alice_token, patched_ai_engine, monkeypatch
):
    # No -CONF case ships in the demo ACL; grant alice one for this test. The
    # -CONF suffix is the convention _security_level_for_case keys on.
    from backend.gateway import auth

    conf_case = "CASE-2025-003-CONF"
    monkeypatch.setitem(auth._CASE_ACL, "alice", set(auth._CASE_ACL["alice"]) | {conf_case})

    r = _analyze(gateway_client, alice_token, conf_case)
    assert r.status_code == 200, r.text
    model = r.json()["cost_meta"]["model"]
    # The parse step (which sees the OA text) must have routed to the local
    # model — this is the hole fixed in Day 10 (#4).
    assert settings.LLM_MODEL_LOCAL in model, f"confidential case hit non-local model: {model}"
    assert settings.LLM_MODEL_REASONING not in model, model
