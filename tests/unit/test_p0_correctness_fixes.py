"""Unit tests for the Day 10 P0 correctness fixes (code-review follow-up).

Covers:
  #1 deadline recommended-internal date must be strictly BEFORE the statutory
     date and itself a business day (deadline._prev_business_day backward roll).
  #2 jurisdiction derived from the patent-number prefix, not hardcoded "TW"
     (orchestrator._jurisdiction_for_patent).
  #3 cost-circuit degrade: the draft model drops to the cheap tier when the
     breaker is open (route_model + oa_analyzer.draft_response forwarding).
  #4 confidential routing: parse_oa / draft_response route to the local model,
     and oa_analyzer.parse_oa actually forwards security_level to the LLM.
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.ai_engine import deadline as dl
from backend.ai_engine import llm_client, oa_analyzer
from backend.gateway import orchestrator
from backend.shared.config import settings
from backend.shared.models import Rejection, RejectionType


def _iso_date(s: str):
    return datetime.fromisoformat(s).date()


# ---------- #1 deadline: recommended strictly before statutory ----------


@pytest.mark.parametrize("offset_days", list(range(0, 40)))
def test_recommended_internal_is_strictly_before_statutory(offset_days):
    received = datetime(2024, 12, 1, 9, 0, tzinfo=UTC) + timedelta(days=offset_days)
    r = dl.calculate_deadline(received, "TW", "2025.1")
    stat = _iso_date(r["statutory_deadline"])
    rec = _iso_date(r["recommended_internal_deadline"])
    assert rec < stat, f"recommended {rec} not before statutory {stat} (received +{offset_days}d)"
    holidays = dl.HOLIDAYS[("TW", "2025.1")]
    assert rec.weekday() < 5 and rec not in holidays, f"recommended {rec} is not a business day"


def test_prev_business_day_rolls_backward_over_holiday_block():
    holidays = dl.HOLIDAYS[("TW", "2025.1")]
    # 2025-01-29..01-31 are 春節; 2025-02-01 is a Saturday. Rolling back from
    # 2025-02-01 must land on 2025-01-28 (除夕 is a holiday too) → actually the
    # nearest business day before the LNY block is 2025-01-24 (Fri).
    got = dl._prev_business_day(dl.date(2025, 2, 1), holidays)
    assert got.weekday() < 5 and got not in holidays
    assert got < dl.date(2025, 1, 27)


# ---------- #2 jurisdiction derivation ----------


@pytest.mark.parametrize(
    "patent_no,expected",
    [
        ("US7654321", "US"),
        ("TW202617461", "TW"),
        ("EP3210987", "EP"),
        ("JP2020123456", "JP"),
        ("CN123456789", "CN"),
        ("us7654321", "US"),  # case-insensitive
        ("", "TW"),  # missing → home office
        ("12345", "TW"),  # no recognizable prefix → home office
    ],
)
def test_jurisdiction_for_patent(patent_no, expected):
    assert orchestrator._jurisdiction_for_patent(patent_no) == expected


# ---------- #3 + #4 routing decisions ----------


@pytest.mark.parametrize("intent", ["parse_oa", "draft_response"])
def test_confidential_routes_to_local(intent):
    m = llm_client.route_model(intent=intent, security_level="confidential", circuit_open=False)
    assert m == settings.LLM_MODEL_LOCAL


def test_circuit_open_degrades_draft_model():
    strong = llm_client.route_model(
        intent="draft_response", security_level="public", circuit_open=False
    )
    degraded = llm_client.route_model(
        intent="draft_response", security_level="public", circuit_open=True
    )
    assert strong == settings.LLM_MODEL_REASONING
    assert degraded == settings.LLM_MODEL_CHEAP
    assert degraded != strong


# ---------- #4 wiring: oa_analyzer forwards the flags to the LLM ----------


def _fake_response():
    return llm_client.LLMResponse(
        text="{}", model="stub", prompt_tokens=1, completion_tokens=1, latency_ms=1
    )


def test_parse_oa_forwards_security_level(monkeypatch):
    captured = {}

    def _fake_chat(*, system, user, intent, security_level, circuit_open=False):
        captured.update(intent=intent, security_level=security_level)
        return _fake_response()

    monkeypatch.setattr(oa_analyzer.llm_client, "chat", _fake_chat)
    oa_analyzer.parse_oa("some OA text", "TW202617461", security_level="confidential")
    assert captured == {"intent": "parse_oa", "security_level": "confidential"}


def test_draft_response_forwards_circuit_open(monkeypatch):
    captured = {}

    def _fake_chat(*, system, user, intent, security_level, circuit_open=False):
        captured["circuit_open"] = circuit_open
        return _fake_response()

    monkeypatch.setattr(oa_analyzer.llm_client, "chat", _fake_chat)
    rej = Rejection(
        rejection_id="R1",
        rejection_type=RejectionType("103_obviousness"),
        affected_claims=[1],
        cited_prior_art=["US7654321"],
        examiner_argument="obvious over the combination",
        confidence=0.9,
    )
    oa_analyzer.draft_response(rej, [], None, "public", circuit_open=True)
    assert captured["circuit_open"] is True
