"""Deadline calculation (Q17).

Three core requirements:
    1. Per-jurisdiction rules (TW vs US vs JP start counting differently).
    2. Calendar-version locking — recompute uses the same holiday version
       so re-running 6 months later doesn't yield a different answer.
    3. Multi-timezone: mailing date in sender's TZ, deadline in case TZ.

Holiday calendars are CLIENT-UPDATABLE + VERSIONED. They live as
``data/calendars/<jurisdiction>_<version>.json`` (schema below) and are loaded
+ cached on first use. The hard-coded ``_FALLBACK_HOLIDAYS`` dict below is the
safety net: when no JSON file is present (fresh checkout / absent data dir / CI)
the loader degrades to it so nothing ever breaks. This mirrors how the masking
layer externalises per-tenant dictionaries (data/tenant_dicts/<id>.json with a
hard-coded TENANT_DICTIONARIES fallback).

Calendar JSON schema::

    {
      "jurisdiction": "TW",
      "version": "2025.1",
      "holidays": { "2025-01-01": "元旦", ... }
    }

Calendar-version locking invariant: the same ``(jurisdiction, version)`` ALWAYS
resolves to the same holiday set (the file is the authoritative source; the
hard-coded dict is a byte-for-byte mirror for the shipped 2025.1 versions). A
requested version with NO file AND no hard-coded entry resolves to an EMPTY
calendar plus a LOUD warning in the returned dict — never a silently-wrong date.

POC jurisdictions: TW, US, JP, EP, CN, KR (the EP/CN/KR rules are documented
approximations — see each rule's inline caveat). Anything else stubs out
(60-day default + warning).
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

from backend.shared.config import settings, DATA_DIR

logger = logging.getLogger(__name__)

# Where versioned calendars live. Override-able for tests.
CALENDARS_DIR: Path = DATA_DIR / "calendars"


# ---------- Hard-coded fallback holiday data (POC: 2025) ----------
#
# This is the SAFETY NET, not the primary source. The loader below prefers the
# JSON file at data/calendars/<jurisdiction>_<version>.json and only falls back
# here when the file is absent / unreadable. Keep this in sync with the shipped
# *_2025.1.json files (they are byte-for-byte mirrors) so version-locking holds
# regardless of whether the data dir is present.
#
# Format: {(jurisdiction, version): {date: name}}
_FALLBACK_HOLIDAYS: dict[tuple[str, str], dict[date, str]] = {
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
    # JP fallback — abbreviated mirror of JP_2025.1.json (key dates only). The
    # JSON file is authoritative; this guarantees JP still resolves on a fresh
    # checkout with no data dir.
    ("JP", "2025.1"): {
        date(2025, 1, 1): "元日",
        date(2025, 1, 2): "年始休 (JPO closed)",
        date(2025, 1, 3): "年始休 (JPO closed)",
        date(2025, 1, 13): "成人の日",
        date(2025, 2, 11): "建国記念の日",
        date(2025, 2, 23): "天皇誕生日",
        date(2025, 2, 24): "天皇誕生日 振替休日",
        date(2025, 3, 20): "春分の日",
        date(2025, 4, 29): "昭和の日",
        date(2025, 5, 3): "憲法記念日",
        date(2025, 5, 4): "みどりの日",
        date(2025, 5, 5): "こどもの日",
        date(2025, 5, 6): "こどもの日 振替休日",
        date(2025, 7, 21): "海の日",
        date(2025, 8, 11): "山の日",
        date(2025, 9, 15): "敬老の日",
        date(2025, 9, 23): "秋分の日",
        date(2025, 10, 13): "スポーツの日",
        date(2025, 11, 3): "文化の日",
        date(2025, 11, 23): "勤労感謝の日",
        date(2025, 11, 24): "勤労感謝の日 振替休日",
        date(2025, 12, 29): "年末休 (JPO closed)",
        date(2025, 12, 30): "年末休 (JPO closed)",
        date(2025, 12, 31): "年末休 (JPO closed)",
    },
    # EP fallback — byte-for-byte mirror of EP_2025.1.json. APPROXIMATE EPO
    # closure days (see the JSON's source note + the EP RULES caveat).
    ("EP", "2025.1"): {
        date(2025, 1, 1): "New Year's Day (EPO closed, approx.)",
        date(2025, 4, 18): "Good Friday (EPO closed, approx.)",
        date(2025, 4, 21): "Easter Monday (EPO closed, approx.)",
        date(2025, 5, 1): "Labour Day (EPO closed, approx.)",
        date(2025, 5, 8): "Liberation Day (NL, EPO closed, approx.)",
        date(2025, 5, 29): "Ascension Day (EPO closed, approx.)",
        date(2025, 6, 9): "Whit Monday (EPO closed, approx.)",
        date(2025, 10, 3): "German Unity Day (EPO closed, approx.)",
        date(2025, 12, 24): "Christmas Eve (EPO closed, approx.)",
        date(2025, 12, 25): "Christmas Day (EPO closed, approx.)",
        date(2025, 12, 26): "Boxing Day (EPO closed, approx.)",
        date(2025, 12, 31): "New Year's Eve (EPO closed, approx.)",
    },
    # CN fallback — byte-for-byte mirror of CN_2025.1.json. 国务院 statutory
    # public holidays incl. the 春节 + 国庆/中秋 golden weeks.
    ("CN", "2025.1"): {
        date(2025, 1, 1): "元旦",
        date(2025, 1, 28): "春节(除夕)",
        date(2025, 1, 29): "春节(初一)",
        date(2025, 1, 30): "春节(初二)",
        date(2025, 1, 31): "春节(初三)",
        date(2025, 2, 1): "春节",
        date(2025, 2, 2): "春节",
        date(2025, 2, 3): "春节",
        date(2025, 2, 4): "春节",
        date(2025, 4, 4): "清明节",
        date(2025, 5, 1): "劳动节",
        date(2025, 5, 2): "劳动节",
        date(2025, 5, 3): "劳动节",
        date(2025, 5, 4): "劳动节",
        date(2025, 5, 5): "劳动节",
        date(2025, 5, 31): "端午节",
        date(2025, 6, 1): "端午节",
        date(2025, 6, 2): "端午节",
        date(2025, 10, 1): "国庆节",
        date(2025, 10, 2): "国庆节",
        date(2025, 10, 3): "国庆节",
        date(2025, 10, 4): "国庆节",
        date(2025, 10, 5): "国庆节",
        date(2025, 10, 6): "中秋节",
        date(2025, 10, 7): "国庆节",
        date(2025, 10, 8): "国庆节",
    },
    # KR fallback — byte-for-byte mirror of KR_2025.1.json. 공휴일 incl. the
    # 설날 + 추석 three-day blocks and 대체공휴일 substitutions.
    ("KR", "2025.1"): {
        date(2025, 1, 1): "신정",
        date(2025, 1, 28): "설날 연휴",
        date(2025, 1, 29): "설날",
        date(2025, 1, 30): "설날 연휴",
        date(2025, 3, 1): "삼일절",
        date(2025, 3, 3): "삼일절 대체공휴일",
        date(2025, 5, 5): "어린이날 / 부처님오신날",
        date(2025, 5, 6): "대체공휴일",
        date(2025, 6, 6): "현충일",
        date(2025, 8, 15): "광복절",
        date(2025, 10, 3): "개천절",
        date(2025, 10, 6): "추석 연휴",
        date(2025, 10, 7): "추석",
        date(2025, 10, 8): "추석 연휴",
        date(2025, 10, 9): "한글날",
        date(2025, 12, 25): "성탄절",
    },
}


# ---------- Versioned-calendar loader (client-updatable + cached) ----------

# Cache keyed by (jurisdiction, version). A sentinel object distinguishes
# "loaded, resolved to empty" from "not yet loaded" so a genuinely-empty /
# missing calendar is cached (and warned about) exactly once rather than
# re-read on every request.
_calendar_cache: dict[tuple[str, str], dict[date, str]] = {}
_calendar_cache_lock = threading.Lock()
# Records which (jurisdiction, version) resolved with NO source at all, so
# calculate_deadline can surface the loud warning. Populated alongside the
# cache under the same lock.
_calendar_missing: set[tuple[str, str]] = set()


def _calendar_path(jurisdiction: str, version: str) -> Path:
    return CALENDARS_DIR / f"{jurisdiction}_{version}.json"


def _parse_calendar_doc(
    jurisdiction: str, version: str, doc: object
) -> Optional[dict[date, str]]:
    """Validate + parse a loaded calendar JSON document into {date: name}.

    Returns None (caller falls back) on any structural problem. A single bad
    date string is skipped + logged, but does NOT abort the whole calendar."""
    if not isinstance(doc, dict):
        logger.warning(
            "calendar %s_%s: top-level JSON is not an object; ignoring file.",
            jurisdiction, version,
        )
        return None
    # Soft-validate the self-describing fields (don't hard-fail on mismatch,
    # but warn — a mislabelled file is a real ops footgun).
    if doc.get("jurisdiction") not in (None, jurisdiction):
        logger.warning(
            "calendar %s_%s: file declares jurisdiction=%r (filename says %r).",
            jurisdiction, version, doc.get("jurisdiction"), jurisdiction,
        )
    if doc.get("version") not in (None, version):
        logger.warning(
            "calendar %s_%s: file declares version=%r (filename says %r).",
            jurisdiction, version, doc.get("version"), version,
        )
    raw = doc.get("holidays")
    if not isinstance(raw, dict):
        logger.warning(
            "calendar %s_%s: 'holidays' is not an object; ignoring file.",
            jurisdiction, version,
        )
        return None
    out: dict[date, str] = {}
    for k, name in raw.items():
        try:
            d = date.fromisoformat(k)
        except (TypeError, ValueError):
            logger.warning(
                "calendar %s_%s: skipping un-parseable date key %r.",
                jurisdiction, version, k,
            )
            continue
        out[d] = str(name)
    return out


def _read_calendar(jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
    """Resolve a calendar from disk, then hard-coded fallback.

    Returns ``(holidays, found)``. ``found`` is False ONLY when neither a usable
    JSON file NOR a hard-coded fallback exists — that's the "missing version"
    case the caller must warn about. Never raises."""
    path = _calendar_path(jurisdiction, version)
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "calendar %s: failed to read/parse (%s); falling back to "
                "hard-coded calendar.", path, exc,
            )
        else:
            parsed = _parse_calendar_doc(jurisdiction, version, doc)
            if parsed is not None:
                return parsed, True

    fallback = _FALLBACK_HOLIDAYS.get((jurisdiction, version))
    if fallback is not None:
        return dict(fallback), True

    # Neither file nor hard-coded fallback. This is NOT the same as an unknown
    # jurisdiction (handled earlier): it's a known jurisdiction asked for a
    # calendar VERSION we don't have. Empty set + found=False so the caller
    # emits a loud warning rather than silently returning a wrong date.
    return {}, False


def get_holidays(jurisdiction: str, version: str) -> dict[date, str]:
    """Public, cached accessor for a versioned holiday calendar.

    Thread-safe. Same ``(jurisdiction, version)`` ALWAYS returns the same set
    for the process lifetime (version-locking). Call ``reload_calendars()``
    after dropping a new/updated JSON file."""
    key = (jurisdiction, version)
    cached = _calendar_cache.get(key)
    if cached is not None:
        return cached
    with _calendar_cache_lock:
        cached = _calendar_cache.get(key)
        if cached is not None:
            return cached
        holidays, found = _read_calendar(jurisdiction, version)
        _calendar_cache[key] = holidays
        if not found:
            _calendar_missing.add(key)
            logger.warning(
                "calendar %s_%s: NO source (no JSON file, no hard-coded "
                "fallback). Using an EMPTY holiday set — deadline may be wrong. "
                "Load data/calendars/%s_%s.json before relying on this.",
                jurisdiction, version, jurisdiction, version,
            )
    return _calendar_cache[key]


def calendar_is_missing(jurisdiction: str, version: str) -> bool:
    """True iff the requested (jurisdiction, version) resolved with no source.

    Triggers a load (and the warning) if not yet cached."""
    get_holidays(jurisdiction, version)
    return (jurisdiction, version) in _calendar_missing


def deadline_year_is_covered(
    jurisdiction: str, calendar_version: str, deadline_date: date
) -> bool:
    """True iff the loaded calendar covers ``deadline_date``'s year.

    Out-of-band query so callers/tests can branch on the year-boundary
    condition without parsing the warnings list. Mirrors the inline check in
    ``calculate_deadline``: a year is "covered" iff the loaded calendar has at
    least one holiday in it."""
    holidays = get_holidays(jurisdiction, calendar_version)
    return any(h.year == deadline_date.year for h in holidays)


def reload_calendars() -> None:
    """Drop the calendar cache so freshly-dropped JSON files are picked up.

    The masking layer has the same per-upload reload story. Cheap; calendars
    are small."""
    with _calendar_cache_lock:
        _calendar_cache.clear()
        _calendar_missing.clear()


# Backwards-compatible alias. Older code / tests referenced the module-level
# ``HOLIDAYS`` dict directly. It now maps to the hard-coded fallback (the
# authoritative source is the JSON loader via get_holidays()).
HOLIDAYS = _FALLBACK_HOLIDAYS


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
    # JP (JPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a JPO office action (拒絶理由通知) gives a domestic applicant a
    # ~3-month response period; overseas applicants commonly get an extended
    # window. We model the common 3-month (90-day) figure counted from the
    # received/dispatch date in Asia/Tokyo. If the last day falls on a JPO
    # closure day (national holiday, 振替休日, or the 12/29–1/3 year-end break)
    # it rolls to the next business day under 特許法施行規則 practice. The exact
    # start event (dispatch vs deemed-receipt 発送日 +N) and overseas-extension
    # rules MUST be confirmed with a JP attorney before production use.
    "JP": JurisdictionRule(
        name="JPO 拒絶理由通知 応答期間 (POC approximation)",
        response_days=90,
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Tokyo",
        extension_days=90,
    ),
    # EP (EPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to an EPO examining-division communication under
    # Art. 94(3) EPC is set in the communication itself and is conventionally
    # ~4 months from the communication date. We model 4 months as 120 days
    # counted from the communication date in Europe/Berlin (the canonical IANA
    # zone covering the EPO's Munich seat — there is no separate "Europe/Munich"
    # zone). If the last day falls on a weekend or an EPO non-working day it
    # rolls to the next day the EPO is open (Rule 134(1) EPC).
    # CAVEAT 1: the period is a CALENDAR-MONTH count under Rule 131(4) EPC (e.g.
    #   a communication dated the 15th expires on the 15th four months later),
    #   NOT a fixed 120-day count; the 120-day figure is a POC simplification
    #   that the dataclass's day-based schema forces and can be off by 1-2 days.
    # CAVEAT 2: the old "10-day rule" (Rule 126(2) EPC, +10 days for notified
    #   deemed-delivery) was ABOLISHED for documents notified on/after
    #   2023-11-01, so we do NOT add it; pre-2023 communications would need it.
    # The exact start event and any further-processing/extension rights MUST be
    # confirmed with an EP attorney before production use.
    "EP": JurisdictionRule(
        name="EPO Art. 94(3) examination response (POC approximation)",
        response_days=120,            # ~4 months, simplified to fixed days
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Europe/Berlin",  # canonical IANA zone for Munich
        extension_days=60,            # further processing / extension, approx.
    ),
    # CN (CNIPA) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to the first Office Action (审查意见通知书) is due ~4
    # months from the 发文日 (issue/dispatch date printed on the notice). We
    # model 4 months as 120 days counted in Asia/Shanghai. Roll forward over
    # weekends + national holidays (incl. the multi-day 春节/国庆 golden weeks).
    # CAVEAT: under 专利法实施细则, the period actually runs from the date of
    #   RECEIPT, which the rules PRESUME to be the 发文日 + 15 days (送达推定).
    #   So a more faithful statutory deadline is closer to 发文日 + 15 + ~120
    #   days. This engine counts from whatever received_date the caller passes;
    #   if the caller passes the 发文日, add the +15-day presumption upstream (or
    #   pass the presumed receipt date). The 15-day presumption is NOT auto-added
    #   here to avoid double-counting when the caller already has the true
    #   receipt date. Confirm with a CN attorney before production use.
    "CN": JurisdictionRule(
        name="CNIPA 审查意见通知书 答复期限 (POC approximation)",
        response_days=120,            # ~4 months from 发文日, simplified
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Shanghai",
        extension_days=60,
    ),
    # KR (KIPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to a KIPO office action (의견제출통지서) is conventionally
    # ~2 months from notification for a domestic applicant, extendable on
    # request. We model 2 months as 60 days counted in Asia/Seoul, rolling
    # forward over weekends + national holidays (incl. the 설날/추석 blocks).
    # CAVEAT: the exact start event (notification vs deemed receipt) and the
    #   per-month extension scheme (KIPO grants extensions in monthly tranches)
    #   are simplified; confirm with a KR attorney before production use.
    "KR": JurisdictionRule(
        name="KIPO 의견제출통지서 응답기간 (POC approximation)",
        response_days=60,             # ~2 months, extendable
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Seoul",
        extension_days=30,
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
    # Load from the versioned, client-updatable calendar (cached). Falls back to
    # the hard-coded mirror; resolves to empty + a loud warning if the requested
    # version has no source at all (never a silently-wrong date).
    holidays = get_holidays(jurisdiction, calendar_version)
    calendar_missing = (jurisdiction, calendar_version) in _calendar_missing

    # Convert received date to case timezone, take the date part
    received_local = received_date.astimezone(case_tz)
    raw_deadline_date = received_local.date() + timedelta(days=rule.response_days)

    # Roll forward if last day is weekend/holiday
    final_deadline_date = _next_business_day(raw_deadline_date, holidays)
    rolled = final_deadline_date != raw_deadline_date

    # Year-boundary guard. The loaded calendar version is keyed to a year
    # (e.g. "2025.1" covers 2025). When the statutory deadline lands in — OR
    # ROLLS INTO — a year the calendar doesn't cover, the roll-forward can't see
    # that year's holidays (it could land on, say, 2026 元旦 and not know it).
    # We check BOTH the raw deadline year and the final (post-roll) year against
    # the loaded calendar: if EITHER falls in a year with no holidays loaded, we
    # surface a loud warning rather than silently computing against a partial
    # calendar. (Checking only the raw year missed the case where the roll
    # itself crosses the boundary — e.g. JP 12/31 rolling onto 1/1.)
    loaded_years = {h.year for h in holidays}
    deadline_year_covered = (
        raw_deadline_date.year in loaded_years
        and final_deadline_date.year in loaded_years
    )

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
    if calendar_missing:
        warnings.append(
            f"⛔ Holiday calendar {jurisdiction}_{calendar_version} could not be "
            f"loaded (no JSON file, no fallback). Computed against an EMPTY "
            f"holiday set — VERIFY this deadline manually; it may be wrong."
        )
    elif not deadline_year_covered:
        # Deadline lands in / rolled into a year the loaded calendar doesn't
        # cover. Name the uncovered year(s) explicitly.
        uncovered = sorted(
            {raw_deadline_date.year, final_deadline_date.year} - loaded_years
        )
        years_str = ", ".join(str(y) for y in uncovered)
        warnings.append(
            f"⚠️  Statutory deadline involves year(s) {years_str}, but the loaded "
            f"calendar {jurisdiction}_{calendar_version} does not cover them. "
            f"Those years' holidays were NOT considered — load the matching "
            f"calendar(s) and recompute."
        )
    if rolled:
        warnings.append(
            f"Statutory deadline rolled from {raw_deadline_date} (weekend/holiday) "
            f"to {final_deadline_date}."
        )
    if days_remaining < 14:
        warnings.append(f"⚠️  Only {days_remaining} days remaining — escalate immediately.")
    if days_remaining < 0:
        warnings.append(f"⛔ DEADLINE PASSED {abs(days_remaining)} days ago.")

    # NOTE: the returned dict's keys are constrained to the wire model
    # (backend.shared.models.DeadlineInfo, which forbids extras). The structured
    # flags (calendar_missing / deadline_year_covered) are surfaced via the
    # human-readable `warnings` list above, and are also queryable out-of-band
    # via calendar_is_missing() / deadline_year_is_covered() for callers/tests
    # that need to branch without string-matching.
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

    # Case 4: jurisdiction stub (still works for anything not in RULES)
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc), "DE", "2025.1")
    assert any("not yet implemented" in w for w in r["warnings"])

    # Case 5: CN — +120 days lands on the 国庆 golden week; must roll past it
    # and land on a business day, in +08:00 (Asia/Shanghai).
    r = calculate_deadline(datetime(2025, 6, 9, 9, 0, tzinfo=timezone.utc), "CN", "2025.1")
    assert r["statutory_deadline"].endswith("+08:00"), r["statutory_deadline"]
    cn_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert cn_sd.weekday() < 5 and cn_sd not in get_holidays("CN", "2025.1"), cn_sd

    # Case 6: KR — +60 days, Asia/Seoul (+09:00), rolls off weekends/holidays.
    r = calculate_deadline(datetime(2025, 8, 1, 9, 0, tzinfo=timezone.utc), "KR", "2025.1")
    assert r["statutory_deadline"].endswith("+09:00"), r["statutory_deadline"]
    kr_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert kr_sd.weekday() < 5 and kr_sd not in get_holidays("KR", "2025.1"), kr_sd

    # Case 7: EP — +120 days, Europe/Munich; business day.
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc), "EP", "2025.1")
    ep_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert ep_sd.weekday() < 5 and ep_sd not in get_holidays("EP", "2025.1"), ep_sd

    print("✓ deadline self-test passed")


if __name__ == "__main__":
    _self_test()
