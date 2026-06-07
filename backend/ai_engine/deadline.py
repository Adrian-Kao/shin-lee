"""Deadline calculation (Q17).

Three core requirements:
    1. Per-jurisdiction rules (TW vs US start counting differently).
    2. Calendar-version locking — recompute uses the same holiday version
       so re-running 6 months later doesn't yield a different answer.
    3. Multi-timezone: mailing date in sender's TZ, deadline in case TZ.

POC: TW + US.  Other jurisdictions stub-out.

Real holiday calendars (loaded from data/calendars/<jurisdiction>_<version>.json
in production).  POC ships hard-coded 2025 lists for demo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from backend.shared.config import settings


# ---------- Holiday data (POC: 2025) ----------

# Format: {(jurisdiction, version): {date: name}}
HOLIDAYS: dict[tuple[str, str], dict[date, str]] = {
    ("TW", "2025.1"): {
        date(2025, 1, 1): "元旦",
        date(2025, 1, 27): "農曆除夕（補假）",
        date(2025, 1, 28): "農曆除夕",
        date(2025, 1, 29): "春節初一",
        date(2025, 1, 30): "春節初二",
        date(2025, 1, 31): "春節初三",
        date(2025, 2, 28): "和平紀念日",
        date(2025, 4, 3): "兒童節（補假）",
        date(2025, 4, 4): "兒童節 / 清明",
        date(2025, 5, 1): "勞動節",
        date(2025, 5, 30): "端午節（補假）",
        date(2025, 5, 31): "端午節",
        date(2025, 9, 29): "中秋節（補假）",
        date(2025, 10, 6): "中秋節",
        date(2025, 10, 10): "國慶日",
    },
    ("US", "2025.1"): {
        date(2025, 1, 1): "New Year's Day",
        date(2025, 1, 20): "MLK Day",
        date(2025, 2, 17): "Presidents' Day",
        date(2025, 5, 26): "Memorial Day",
        date(2025, 6, 19): "Juneteenth",
        date(2025, 7, 4): "Independence Day",
        date(2025, 9, 1): "Labor Day",
        date(2025, 10, 13): "Columbus Day",
        date(2025, 11, 11): "Veterans Day",
        date(2025, 11, 27): "Thanksgiving",
        date(2025, 12, 25): "Christmas",
    },
}


# ---------- Rule specs ----------

@dataclass(frozen=True)
class JurisdictionRule:
    name: str
    response_days: int           # statutory days from start_date
    excludes_weekends: bool
    excludes_holidays: bool
    timezone_name: str
    extension_days: Optional[int]  # e.g. US +3 month; TW one-off extension


RULES: dict[str, JurisdictionRule] = {
    "TW": JurisdictionRule(
        name="台灣 TIPO 答辯期間",
        response_days=60,             # 兩個月（簡化）
        excludes_weekends=False,      # 週末算入；只有最後一日為假日才順延
        excludes_holidays=False,
        timezone_name="Asia/Taipei",
        extension_days=30,
    ),
    "US": JurisdictionRule(
        name="USPTO Office Action shortened response",
        response_days=90,             # 3 months shortened
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="America/New_York",
        extension_days=90,
    ),
}


_MAX_ROLL_DAYS = 30  # termination guard against a malformed holiday calendar


def _next_business_day(d: date, holidays: dict[date, str]) -> date:
    for _ in range(_MAX_ROLL_DAYS):
        if d.weekday() < 5 and d not in holidays:
            return d
        d += timedelta(days=1)
    raise ValueError(f"no business day within {_MAX_ROLL_DAYS} days — bad holiday calendar")


def _prev_business_day(d: date, holidays: dict[date, str]) -> date:
    """Roll BACKWARD to the nearest business day (for the internal-warning
    date, which must never land on/after the statutory deadline)."""
    for _ in range(_MAX_ROLL_DAYS):
        if d.weekday() < 5 and d not in holidays:
            return d
        d -= timedelta(days=1)
    raise ValueError(f"no business day within {_MAX_ROLL_DAYS} days — bad holiday calendar")


def calculate_deadline(
    received_date: datetime,
    jurisdiction: str = "TW",
    calendar_version: str = "2025.1",
) -> dict:
    """Returns dict with deadline info.

    Q17 invariants:
      - Compute in case_tz, returns ISO with explicit offset.
      - If statutory deadline lands on weekend/holiday, roll forward to next biz day.
      - Same calendar_version → same answer; bumping version requires explicit re-confirmation.
    """
    if jurisdiction not in RULES:
        # Stub for unsupported jurisdictions
        return {
            "received_date": received_date.isoformat(),
            "statutory_deadline": (received_date + timedelta(days=60)).isoformat(),
            "recommended_internal_deadline": (received_date + timedelta(days=53)).isoformat(),
            "days_remaining": 60,
            "holiday_calendar_version": calendar_version,
            "warnings": [f"Jurisdiction {jurisdiction} not yet implemented; using 60-day default."],
        }

    rule = RULES[jurisdiction]
    case_tz = ZoneInfo(rule.timezone_name)
    holidays = HOLIDAYS.get((jurisdiction, calendar_version), {})

    # Convert received date to case timezone, take the date part
    received_local = received_date.astimezone(case_tz)
    raw_deadline_date = received_local.date() + timedelta(days=rule.response_days)

    # Roll forward if last day is weekend/holiday
    final_deadline_date = _next_business_day(raw_deadline_date, holidays)
    rolled = final_deadline_date != raw_deadline_date

    # Recommended internal deadline = ~7 days earlier. Roll BACKWARD to the
    # previous business day — rolling forward (the old behaviour) could land
    # the "earlier" internal warning ON or AFTER the statutory date whenever
    # those 7 days span a long weekend/holiday block. Then hard-guarantee it
    # is strictly before the statutory deadline.
    recommended_raw = final_deadline_date - timedelta(days=7)
    recommended = _prev_business_day(recommended_raw, holidays)
    while recommended >= final_deadline_date:
        recommended = _prev_business_day(recommended - timedelta(days=1), holidays)

    # Express deadlines as 23:59 case-local time
    statutory_dt = datetime.combine(final_deadline_date, time(23, 59), tzinfo=case_tz)
    recommended_dt = datetime.combine(recommended, time(23, 59), tzinfo=case_tz)

    days_remaining = (final_deadline_date - datetime.now(case_tz).date()).days

    warnings = []
    if rolled:
        warnings.append(
            f"Statutory deadline rolled from {raw_deadline_date} (weekend/holiday) "
            f"to {final_deadline_date}."
        )
    if days_remaining < 14:
        warnings.append(f"⚠️  Only {days_remaining} days remaining — escalate immediately.")
    if days_remaining < 0:
        warnings.append(f"⛔ DEADLINE PASSED {abs(days_remaining)} days ago.")

    return {
        "received_date": received_local.isoformat(),
        "statutory_deadline": statutory_dt.isoformat(),
        "recommended_internal_deadline": recommended_dt.isoformat(),
        "days_remaining": days_remaining,
        "holiday_calendar_version": calendar_version,
        "warnings": warnings,
    }


# ---------- Self-tests (run with: python -m backend.ai_engine.deadline) ----------

def _self_test():
    """Run common edge cases.  Production replaces with pytest."""
    # Case 1: TW received 2025-01-15 → statutory 60 days → 2025-03-16 → Sunday → roll to 2025-03-17
    r = calculate_deadline(datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc), "TW", "2025.1")
    assert r["statutory_deadline"].startswith("2025-03-17"), r["statutory_deadline"]

    # Case 2: TW received 2024-12-01 → 60 days → 2025-01-30 → 春節 → roll to next biz day
    r = calculate_deadline(datetime(2024, 12, 1, 9, 0, tzinfo=timezone.utc), "TW", "2025.1")
    assert "2025-02" in r["statutory_deadline"], r["statutory_deadline"]

    # Case 3: US received 2025-04-01 → 90 days → 2025-06-30 → biz day → keep
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc), "US", "2025.1")
    assert r["statutory_deadline"].startswith("2025-06-30"), r["statutory_deadline"]

    # Case 4: jurisdiction stub
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc), "DE", "2025.1")
    assert any("not yet implemented" in w for w in r["warnings"])

    print("✓ deadline self-test passed")


if __name__ == "__main__":
    _self_test()
