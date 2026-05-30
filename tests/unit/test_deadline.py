"""Unit tests for `backend.ai_engine.deadline.calculate_deadline`.

The real signature is:
    calculate_deadline(received_date: datetime,
                       jurisdiction: str = "TW",
                       calendar_version: str = "2025.1") -> dict

The implementation hard-codes the statutory window (TW=60 days, US=90 days)
and rolls forward over weekends + holidays from the 2025.1 calendar.

These tests anchor on the two most demo-visible behaviours:
    1. TW happy path lands on a normal business day (no rollover).
    2. US rollover when the raw statutory deadline lands on a holiday that
       is itself adjacent to a weekend (Independence Day 2025-07-04 is a
       Friday — the next biz day is Monday 2025-07-07).
"""
from __future__ import annotations

from datetime import UTC, datetime

from backend.ai_engine.deadline import calculate_deadline


def test_tw_two_month_window_lands_on_business_day():
    # TW received Thu 2025-05-29 (UTC 09:00) -> +60 days = 2025-07-28 (Mon).
    # No weekend/holiday rollover expected.
    received = datetime(2025, 5, 29, 9, 0, tzinfo=UTC)
    result = calculate_deadline(received, jurisdiction="TW", calendar_version="2025.1")

    assert result["statutory_deadline"].startswith("2025-07-28"), result["statutory_deadline"]
    assert result["holiday_calendar_version"] == "2025.1"
    # No "rolled" warning when the deadline is already a business day.
    assert not any("rolled" in w for w in result["warnings"]), result["warnings"]


def test_us_deadline_rolls_forward_over_holiday_weekend():
    # US received Sat 2025-04-05 -> +90 days = 2025-07-04 (Independence Day, Fri)
    # followed by Sat 7/5 and Sun 7/6, so the next business day is Mon 7/7.
    received = datetime(2025, 4, 5, 9, 0, tzinfo=UTC)
    result = calculate_deadline(received, jurisdiction="US", calendar_version="2025.1")

    assert result["statutory_deadline"].startswith("2025-07-07"), result["statutory_deadline"]
    assert any("rolled" in w for w in result["warnings"]), result["warnings"]
