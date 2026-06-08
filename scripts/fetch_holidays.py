"""Holiday-calendar producer (Q17).

The deadline engine (``backend/ai_engine/deadline.py``) CONSUMES versioned
holiday calendars at ``data/calendars/<jurisdiction>_<version>.json``. This
script is the PRODUCER: a pluggable per-jurisdiction fetcher that pulls official
holiday data (or computes it deterministically) and writes/refreshes those JSON
files in the EXACT schema the loader parses.

CLAUDE.md's Q17 stub says the real impl needs a "Cron job: pull from data.gov.tw
+ USPTO calendar". This is that cron job's body.

Output schema (a superset of what deadline.py reads — it reads jurisdiction /
version / holidays; the extra source / fetched_at keys are provenance):

    {
      "jurisdiction": "US",
      "version": "2025.1",
      "holidays": { "2025-01-01": "New Year's Day", ... },
      "source": "<where it came from>",
      "fetched_at": "2026-06-08T12:00:00+00:00"
    }

Jurisdictions:
  US — federal holidays (OPM). No clean official JSON API, so we COMPUTE the 11
       federal holidays from their statutory rules (fixed-date + Nth-weekday +
       the observed-shift rule). Deterministic, needs NO network.
  TW — Taiwan 行政院人事行政總處 government workday calendar, published as open
       data on data.gov.tw (CSV: a date column + an 是否放假 flag + a 備註
       description). We fetch + parse the holiday days. Needs network.
  JP — Japanese national holidays (内閣府 publishes syukujitsu.csv). Fetched +
       parsed; we additionally fold in the JPO year-end/new-year closure
       (12/29–1/3) since the JPO is shut then. Needs network.
  CN — China statutory holidays incl. the 春节/国庆 golden weeks. Lunar + an
       annual 国务院办公厅 调休 notice, so NOT computable; fetched from the public
       Nager.Date holiday API. Needs network. (Does not model 调休 make-up work
       Saturdays — irrelevant to roll-forward.)
  KR — South Korea public holidays incl. the 설날/추석 blocks + 대체공휴일, fetched
       from the public Nager.Date holiday API. Needs network.
  EP — EPO closure days. The EPO has NO clean machine-readable feed, so these
       are HAND-CURATED per year from its annual closure notice (approximate;
       Munich / The Hague public holidays). No network.

CLI:
  python scripts/fetch_holidays.py <JUR> <YEAR> [--version X] [--out DIR]
                                   [--dry-run] [--force]

  --dry-run   print the parsed calendar; write nothing.
  --force     overwrite an existing target whose content DIFFERS (otherwise a
              differing target is refused, with a diff summary, so a bad upstream
              pull can't silently corrupt a locked calendar).
  --version   calendar version label (default "<YEAR>.1", matching shipped files).
  --out       output directory (default data/calendars).

Network failures fail with a clear actionable message, never a raw stack trace.

Run with no args to print usage + supported jurisdictions.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "data" / "calendars"

HTTP_TIMEOUT = 30.0  # seconds

# data.gov.tw — 行政院人事行政總處 中華民國政府行政機關辦公日曆表 (open data).
# The dataset id is stable; the per-year CSV is served via the export endpoint.
# Documented here as a module constant (NOT in config.py) per Q17.
TW_DATASET_PAGE = "https://data.gov.tw/dataset/14718"
TW_CSV_URL = "https://data.gov.tw/api/v2/rest/datastore/A06000-001-CSV"
# Fallback direct-CSV host used by the dataset (DGPA). Some mirrors expose the
# raw CSV here keyed by year. Tried in order; the first that returns CSV wins.
TW_CSV_URLS = [
    "https://www.dgpa.gov.tw/FileConversion?filename=dgpa/files/{year}.csv",
]

# 内閣府 national-holiday CSV (Shift-JIS encoded). Covers many years in one file.
JP_CSV_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


class FetchError(RuntimeError):
    """Actionable, user-facing failure (printed without a stack trace)."""


# --------------------------------------------------------------------------- #
# US — deterministic federal-holiday computation (no network)                 #
# --------------------------------------------------------------------------- #

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The Nth `weekday` (Mon=0 .. Sun=6) of `month` in `year`. n is 1-based."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (n - 1) * 7
    return date(year, month, day)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last `weekday` of `month` in `year`."""
    last_dom = monthrange(year, month)[1]
    last = date(year, month, last_dom)
    offset = (last.weekday() - weekday) % 7
    return date(year, month, last_dom - offset)


def _observed(d: date) -> date:
    """OPM observed-shift rule: a holiday on Saturday is observed the preceding
    Friday; on Sunday, the following Monday. Uses timedelta so month/year
    boundaries (e.g. New Year's Day on a Saturday -> Dec 31 prior year) are
    handled correctly."""
    if d.weekday() == 5:        # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:        # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def compute_us_federal_holidays(year: int) -> dict[str, str]:
    """Compute the 11 US federal holidays for `year` with observed shifts.

    Names match the shipped US_2025.1.json. Deterministic; no network.

    Fixed-date holidays get the observed-shift rule (the date attorneys see as
    the actual office-closed day). Nth-weekday holidays already fall on a
    weekday and are never shifted.
    """
    fixed: list[tuple[date, str]] = [
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (date(year, 11, 11), "Veterans Day"),
        (date(year, 12, 25), "Christmas"),
    ]
    floating: list[tuple[date, str]] = [
        (_nth_weekday(year, 1, 0, 3), "MLK Day"),            # 3rd Mon Jan
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),    # 3rd Mon Feb
        (_last_weekday(year, 5, 0), "Memorial Day"),         # last Mon May
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),          # 1st Mon Sep
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"),      # 2nd Mon Oct
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),      # 4th Thu Nov
    ]
    # Next year's New Year's Day observes BACK into Dec 31 of THIS year when
    # Jan 1 of year+1 lands on a Saturday — the office is closed this Dec 31.
    fixed.append((date(year + 1, 1, 1), "New Year's Day (observed)"))

    out: dict[str, str] = {}
    for d, name in fixed:
        obs = _observed(d)
        # A federal holiday belongs to the calendar of the YEAR the office is
        # actually closed (the observed date), not the nominal date. This drops
        # a Jan-1-on-Saturday (observed Dec 31 prior year) out of THIS year and
        # pulls next-year's Jan-1-on-Saturday observance into Dec 31 of this year.
        if obs.year != year:
            continue
        out[obs.isoformat()] = name
    for d, name in floating:
        out[d.isoformat()] = name
    # Sort by date for stable, human-diffable output.
    return {k: out[k] for k in sorted(out)}


# --------------------------------------------------------------------------- #
# TW — data.gov.tw government workday calendar CSV parsing                     #
# --------------------------------------------------------------------------- #

# The DGPA calendar CSV uses Big5/UTF-8 headers like:
#   西元日期,星期,是否放假,備註
#   20250101,3,2,開國紀念日
# where 是否放假 == "2" means a day off (放假) and "0"/"" means a working day.
# Column names vary slightly across years/mirrors, so we match flexibly.

_TW_DATE_KEYS = ("西元日期", "date", "Date", "日期")
_TW_ISHOLIDAY_KEYS = ("是否放假", "isHoliday", "假日", "放假")
_TW_NAME_KEYS = ("備註", "note", "假別", "description", "Description")
# Value of the is-holiday column that means "day off". DGPA uses "2".
_TW_HOLIDAY_TRUE = {"2", "是", "true", "True", "1", "y", "Y"}


def _first_present(row: dict, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k in row and row[k] is not None:
            return k
    return None


def _normalise_tw_date(raw: str) -> Optional[str]:
    """Accept YYYYMMDD or YYYY/MM/DD or YYYY-MM-DD -> ISO YYYY-MM-DD."""
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("/", "-")
    digits = s.replace("-", "")
    try:
        if len(digits) == 8 and digits.isdigit():
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
        # Handle non-zero-padded YYYY-M-D (e.g. the 内閣府 CSV uses 2025/1/1),
        # which date.fromisoformat rejects on Python < 3.11.
        parts = s.split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def parse_tw_calendar_csv(text: str, year: Optional[int] = None) -> dict[str, str]:
    """Parse the DGPA government workday CSV into {ISO-date: name}.

    Keeps only rows flagged as a day off (是否放假). Working days are dropped.
    If `year` is given, rows outside that year are ignored. Raises FetchError if
    the CSV shape is unrecognisable (no detectable date/holiday columns).
    """
    text = text.lstrip("﻿")  # strip BOM
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise FetchError(
            "TW calendar CSV had no header row — upstream format may have "
            "changed. Inspect the dataset at " + TW_DATASET_PAGE
        )
    # Resolve columns from the first row's keys.
    fields = reader.fieldnames
    date_key = next((k for k in _TW_DATE_KEYS if k in fields), None)
    flag_key = next((k for k in _TW_ISHOLIDAY_KEYS if k in fields), None)
    name_key = next((k for k in _TW_NAME_KEYS if k in fields), None)
    if date_key is None or flag_key is None:
        raise FetchError(
            "TW calendar CSV is missing an expected date or 是否放假 column "
            f"(saw columns: {fields}). Upstream format may have changed; "
            "inspect " + TW_DATASET_PAGE
        )

    out: dict[str, str] = {}
    for row in reader:
        flag = (row.get(flag_key) or "").strip()
        if flag not in _TW_HOLIDAY_TRUE:
            continue
        iso = _normalise_tw_date(row.get(date_key, ""))
        if iso is None:
            continue
        if year is not None and not iso.startswith(f"{year:04d}-"):
            continue
        name = (row.get(name_key) or "").strip() if name_key else ""
        out[iso] = name or "放假日"
    if not out:
        raise FetchError(
            "TW calendar CSV parsed but yielded ZERO holidays for year "
            f"{year}. Either the year isn't in this file or the 是否放假 flag "
            "encoding changed. Inspect " + TW_DATASET_PAGE
        )
    return {k: out[k] for k in sorted(out)}


def fetch_tw_holidays(year: int) -> tuple[dict[str, str], str]:
    """Fetch + parse the TW government calendar for `year`. Needs network."""
    candidates = [TW_CSV_URL] + [u.format(year=year) for u in TW_CSV_URLS]
    last_err: Optional[str] = None
    for url in candidates:
        try:
            text = _http_get_text(url)
        except FetchError as exc:
            last_err = str(exc)
            continue
        try:
            holidays = parse_tw_calendar_csv(text, year=year)
        except FetchError as exc:
            last_err = str(exc)
            continue
        return holidays, url
    raise FetchError(
        "Could not fetch a usable TW government calendar from any known URL.\n"
        f"  Tried: {candidates}\n"
        f"  Last error: {last_err}\n"
        "  Action: the DGPA / data.gov.tw export endpoint may have moved. "
        "Download the year's CSV manually from " + TW_DATASET_PAGE + " and "
        "parse it offline, or update TW_CSV_URLS in this script."
    )


# --------------------------------------------------------------------------- #
# JP — 内閣府 national-holiday CSV (optional)                                  #
# --------------------------------------------------------------------------- #

# JPO is closed for the year-end/new-year break in addition to national days.
_JP_JPO_CLOSURE = {
    "12-29": "年末休 (JPO closed)",
    "12-30": "年末休 (JPO closed)",
    "12-31": "年末休 (JPO closed)",
    "01-02": "年始休 (JPO closed)",
    "01-03": "年始休 (JPO closed)",
}


def parse_jp_calendar_csv(text: str, year: int) -> dict[str, str]:
    """Parse 内閣府 syukujitsu.csv (国民の祝日,名称) into {ISO-date: name}.

    The file spans many years; we keep `year` only. Dates are YYYY/M/D.
    """
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise FetchError("JP holiday CSV was empty.")
    out: dict[str, str] = {}
    for row in rows[1:]:  # skip header (国民の祝日・休日月日,国民の祝日・休日名称)
        if len(row) < 2:
            continue
        iso = _normalise_tw_date(row[0])  # same YYYY/M/D normaliser works
        if iso is None or not iso.startswith(f"{year:04d}-"):
            continue
        out[iso] = (row[1] or "").strip() or "祝日"
    if not out:
        raise FetchError(
            f"JP holiday CSV parsed but had no rows for {year}. The 内閣府 file "
            "may not yet publish that year."
        )
    # Fold in JPO year-end/new-year office closure.
    for md, name in _JP_JPO_CLOSURE.items():
        out.setdefault(f"{year:04d}-{md}", name)
    return {k: out[k] for k in sorted(out)}


def fetch_jp_holidays(year: int) -> tuple[dict[str, str], str]:
    """Fetch + parse the 内閣府 national-holiday CSV for `year`. Needs network."""
    text = _http_get_text(JP_CSV_URL, encodings=("shift_jis", "cp932", "utf-8"))
    return parse_jp_calendar_csv(text, year), JP_CSV_URL


# --------------------------------------------------------------------------- #
# CN — 国务院办公厅 annual holiday-arrangement notice (Nager.Date public API)   #
# --------------------------------------------------------------------------- #

# China's statutory holidays (esp. the 春节 / 国庆 golden weeks) follow the lunar
# calendar AND an annual 国务院办公厅 调休 notice, so they are NOT computable from
# fixed rules. There is no official machine-readable government endpoint, but the
# widely-used public Nager.Date API exposes the State-Council-aligned public
# holidays per country/year. We fetch from there and tag the source.
NAGER_PUBLIC_HOLIDAYS_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{cc}"


def _parse_nager_holidays(text: str, year: int, *, local_name: bool = True) -> dict[str, str]:
    """Parse a Nager.Date /PublicHolidays JSON array into {ISO-date: name}.

    Nager returns objects like {"date":"2025-01-01","localName":"元旦",
    "name":"New Year's Day", ...}. We keep `localName` (the native-language name)
    by default, falling back to `name`. Rows outside `year` are ignored.
    """
    try:
        rows = json.loads(text)
    except ValueError as exc:
        raise FetchError(f"Holiday API returned non-JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise FetchError(
            "Holiday API JSON was not a list of holidays — upstream format may "
            "have changed."
        )
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        iso = _normalise_tw_date(str(row.get("date", "")))
        if iso is None or not iso.startswith(f"{year:04d}-"):
            continue
        name = (row.get("localName") if local_name else None) or row.get("name") or ""
        out[iso] = str(name).strip() or "holiday"
    if not out:
        raise FetchError(
            f"Holiday API returned no holidays for {year}. The year may not be "
            "published yet."
        )
    return {k: out[k] for k in sorted(out)}


def fetch_cn_holidays(year: int) -> tuple[dict[str, str], str]:
    """Fetch CN public holidays for `year` from the Nager.Date public API.

    Needs network. CAVEAT: this returns the legally OFF days (incl. the golden
    weeks); it does NOT model the 调休 make-up WORK Saturdays, which the deadline
    engine does not need (an extra working day can only delay, never advance, a
    roll-forward). Cross-check against the year's 国务院办公厅 notice for prod.
    """
    url = NAGER_PUBLIC_HOLIDAYS_URL.format(year=year, cc="CN")
    text = _http_get_text(url)
    return _parse_nager_holidays(text, year), url


# --------------------------------------------------------------------------- #
# KR — public holidays incl. 설날/추석 + 대체공휴일 (Nager.Date public API)      #
# --------------------------------------------------------------------------- #

def fetch_kr_holidays(year: int) -> tuple[dict[str, str], str]:
    """Fetch KR public holidays for `year` from the Nager.Date public API.

    Needs network. The Nager feed includes the lunar 설날/추석 blocks and the
    대체공휴일 (substitute) days. CAVEAT: substitute-holiday designations are set
    annually by 인사혁신처 notice; cross-check the official 관공서 공휴일 list for
    production.
    """
    url = NAGER_PUBLIC_HOLIDAYS_URL.format(year=year, cc="KR")
    text = _http_get_text(url)
    return _parse_nager_holidays(text, year), url


# --------------------------------------------------------------------------- #
# EP — EPO closure days: hand-curated, no clean machine-readable upstream      #
# --------------------------------------------------------------------------- #

# The EPO publishes its annual list of days on which its filing offices are
# closed as a PDF / web notice (not a stable JSON/CSV API), and that list does
# NOT equal any single country's public-holiday set. So EP is HAND-CURATED here:
# a per-year table, approximated from the public holidays at the EPO's main
# locations (Munich / The Hague). To add a year, drop its entry below after
# reading the EPO's official "days on which the EPO is closed" notice.
_EP_HOLIDAYS_BY_YEAR: dict[int, dict[str, str]] = {
    2025: {
        "2025-01-01": "New Year's Day (EPO closed, approx.)",
        "2025-04-18": "Good Friday (EPO closed, approx.)",
        "2025-04-21": "Easter Monday (EPO closed, approx.)",
        "2025-05-01": "Labour Day (EPO closed, approx.)",
        "2025-05-08": "Liberation Day (NL, EPO closed, approx.)",
        "2025-05-29": "Ascension Day (EPO closed, approx.)",
        "2025-06-09": "Whit Monday (EPO closed, approx.)",
        "2025-10-03": "German Unity Day (EPO closed, approx.)",
        "2025-12-24": "Christmas Eve (EPO closed, approx.)",
        "2025-12-25": "Christmas Day (EPO closed, approx.)",
        "2025-12-26": "Boxing Day (EPO closed, approx.)",
        "2025-12-31": "New Year's Eve (EPO closed, approx.)",
    },
}


def fetch_ep_holidays(year: int) -> tuple[dict[str, str], str]:
    """Return EP (EPO) closure days for `year` from the hand-curated table.

    NO network: the EPO has no clean machine-readable upstream, so years are
    hand-curated from its annual closure notice. Raises FetchError for a year
    not yet curated, with an actionable message.
    """
    table = _EP_HOLIDAYS_BY_YEAR.get(year)
    if table is None:
        raise FetchError(
            f"EP {year} is not hand-curated. The EPO has no clean "
            "machine-readable holiday feed; add the year to "
            "_EP_HOLIDAYS_BY_YEAR after reading the EPO's official 'days on "
            "which the EPO is closed' notice for that year."
        )
    return dict(sorted(table.items())), (
        "Hand-curated from EPO annual closure notice (APPROXIMATE; Munich / "
        "The Hague public holidays). No clean upstream — no network."
    )


# --------------------------------------------------------------------------- #
# HTTP helper (httpx, with timeout + actionable errors)                       #
# --------------------------------------------------------------------------- #

def _http_get_text(url: str, encodings: tuple[str, ...] = ("utf-8",)) -> str:
    """GET `url` and return decoded text. Raises FetchError (no stack trace)."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx is a declared dep
        raise FetchError(
            "httpx is not installed but is required for network fetches. "
            "Run: pip install httpx"
        ) from exc
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Timed out after {HTTP_TIMEOUT:.0f}s fetching {url}. "
            "Check connectivity / proxy, or retry later."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise FetchError(
            f"Server returned HTTP {exc.response.status_code} for {url}. "
            "The dataset URL may have moved or requires auth."
        ) from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc
    data = resp.content
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort: let httpx guess.
    return resp.text


# --------------------------------------------------------------------------- #
# Fetcher registry                                                             #
# --------------------------------------------------------------------------- #

# Each fetcher: (year) -> (holidays {iso: name}, source-description).
FETCHERS: dict[str, Callable[[int], tuple[dict[str, str], str]]] = {
    "US": lambda year: (
        compute_us_federal_holidays(year),
        "Computed from OPM federal-holiday rules (fixed-date + Nth-weekday + "
        "observed-shift). No network.",
    ),
    "TW": fetch_tw_holidays,
    "JP": fetch_jp_holidays,
    "CN": fetch_cn_holidays,
    "KR": fetch_kr_holidays,
    "EP": fetch_ep_holidays,
}

SUPPORTED = sorted(FETCHERS)


def build_calendar(jurisdiction: str, year: int, version: str) -> dict:
    """Produce the full calendar document for one (jurisdiction, year)."""
    jur = jurisdiction.upper()
    if jur not in FETCHERS:
        raise FetchError(
            f"Unsupported jurisdiction {jur!r}. Supported: {', '.join(SUPPORTED)}."
        )
    holidays, source = FETCHERS[jur](year)
    return {
        "jurisdiction": jur,
        "version": version,
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "holidays": holidays,
    }


# --------------------------------------------------------------------------- #
# Write path: overwrite-guard + atomic write                                  #
# --------------------------------------------------------------------------- #

def _holidays_of(doc: dict) -> dict[str, str]:
    h = doc.get("holidays")
    return h if isinstance(h, dict) else {}


def diff_holidays(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (added, removed, changed) ISO-date lists between two calendar docs.

    `changed` = same date, different name. Ignores provenance keys
    (source / fetched_at) so a re-fetch that only bumps the timestamp counts as
    identical content.
    """
    o, n = _holidays_of(old), _holidays_of(new)
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(d for d in (set(o) & set(n)) if o[d] != n[d])
    return added, removed, changed


def _content_equal(old: dict, new: dict) -> bool:
    """True iff the deadline-relevant content (jurisdiction/version/holidays) is
    identical. Provenance keys are intentionally ignored."""
    return (
        old.get("jurisdiction") == new.get("jurisdiction")
        and old.get("version") == new.get("version")
        and _holidays_of(old) == _holidays_of(new)
    )


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)  # atomic on POSIX + Windows
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_calendar(
    doc: dict, out_dir: Path, *, force: bool = False
) -> tuple[str, list[str]]:
    """Write `doc` to <out_dir>/<jur>_<version>.json with the overwrite guard.

    Returns (status, messages) where status is one of:
      "written"   — new file created.
      "unchanged" — identical content already on disk; no write.
      "overwritten" — content differed and --force was given; written.
      "refused"   — content differed and --force was NOT given; NOT written.
    Never silently clobbers a differing locked calendar.
    """
    jur = doc["jurisdiction"]
    version = doc["version"]
    path = out_dir / f"{jur}_{version}.json"
    msgs: list[str] = []

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict):
            if _content_equal(existing, doc):
                return "unchanged", [f"{path} already up to date (no change)."]
            added, removed, changed = diff_holidays(existing, doc)
            msgs.append(f"Calendar {jur}_{version} at {path} DIFFERS from upstream:")
            msgs.append(f"  + {len(added)} added: {added or '—'}")
            msgs.append(f"  - {len(removed)} removed: {removed or '—'}")
            msgs.append(f"  ~ {len(changed)} renamed: {changed or '—'}")
            if not force:
                msgs.append(
                    "REFUSING to overwrite a locked calendar that deadlines may "
                    "have been computed against. Re-run with --force to apply."
                )
                return "refused", msgs
            _atomic_write_json(path, doc)
            msgs.append(f"--force: overwrote {path}.")
            return "overwritten", msgs

    _atomic_write_json(path, doc)
    msgs.append(f"Wrote {path} ({len(_holidays_of(doc))} holidays).")
    return "written", msgs


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def _print_calendar(doc: dict) -> None:
    print(f"jurisdiction : {doc['jurisdiction']}")
    print(f"version      : {doc['version']}")
    print(f"source       : {doc['source']}")
    print(f"fetched_at   : {doc['fetched_at']}")
    holidays = _holidays_of(doc)
    print(f"holidays     : {len(holidays)}")
    for d in sorted(holidays):
        print(f"  {d}  {holidays[d]}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fetch_holidays.py",
        description="Produce versioned holiday calendars for the deadline engine "
        "(Q17). Pulls official data (TW/JP) or computes deterministically (US).",
    )
    p.add_argument("jurisdiction", help=f"one of: {', '.join(SUPPORTED)}")
    p.add_argument("year", type=int, help="calendar year, e.g. 2025")
    p.add_argument(
        "--version", default=None,
        help="version label (default '<YEAR>.1', matching shipped files).",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUT_DIR),
        help="output directory (default data/calendars).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="print the parsed calendar; write nothing.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing target whose content differs.",
    )
    return p


def run(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    version = args.version or f"{args.year}.1"
    jur = args.jurisdiction.upper()
    try:
        doc = build_calendar(jur, args.year, version)
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("--dry-run (nothing written):")
        _print_calendar(doc)
        return 0

    try:
        status, msgs = write_calendar(doc, Path(args.out), force=args.force)
    except OSError as exc:
        print(f"ERROR: could not write calendar: {exc}", file=sys.stderr)
        return 2
    for m in msgs:
        print(m)
    # "refused" is a non-fatal but actionable outcome -> non-zero exit so a cron
    # job surfaces it.
    return 1 if status == "refused" else 0


def _usage() -> None:
    print(__doc__.strip().splitlines()[0])
    print()
    print("Supported jurisdictions:")
    print("  US — federal holidays, computed deterministically (no network).")
    print("  TW — 行政院人事行政總處 calendar from data.gov.tw (network).")
    print("  JP — 内閣府 national holidays + JPO closure (network).")
    print("  CN — 国务院 statutory holidays via Nager.Date API (network).")
    print("  KR — 공휴일 incl. 설날/추석 + 대체공휴일 via Nager.Date API (network).")
    print("  EP — EPO closure days, hand-curated per year (no network).")
    print()
    print("Usage:")
    print("  python scripts/fetch_holidays.py <JUR> <YEAR> "
          "[--version X] [--out DIR] [--dry-run] [--force]")
    print()
    print("Examples:")
    print("  python scripts/fetch_holidays.py US 2025 --dry-run")
    print("  python scripts/fetch_holidays.py TW 2026 --out data/calendars")
    print(f"\nDefault output dir: {DEFAULT_OUT_DIR}")


if __name__ == "__main__":
    # Windows consoles default to cp1252 and choke on CJK / box chars.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) == 1:
        _usage()
        sys.exit(0)
    sys.exit(run(sys.argv[1:]))
