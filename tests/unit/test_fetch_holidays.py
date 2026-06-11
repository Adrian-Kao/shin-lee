"""Unit tests for scripts/fetch_holidays.py (Q17 calendar producer).

No network is hit: US is pure computation; TW/JP HTTP is monkeypatched.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

# Load the script as a module (it lives under scripts/, not an importable pkg).
_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "fetch_holidays", _ROOT / "scripts" / "fetch_holidays.py"
)
fetch_holidays = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetch_holidays)  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# US federal-holiday computation (exact, no network)                          #
# --------------------------------------------------------------------------- #


def test_us_2025_matches_shipped_calendar():
    """The computed US 2025 set must equal the shipped US_2025.1.json holidays."""
    shipped = json.loads(
        (_ROOT / "data" / "calendars" / "US_2025.1.json").read_text(encoding="utf-8")
    )["holidays"]
    computed = fetch_holidays.compute_us_federal_holidays(2025)
    assert computed == shipped


def test_us_2025_has_11_named_holidays():
    h = fetch_holidays.compute_us_federal_holidays(2025)
    assert len(h) == 11
    assert h["2025-01-20"] == "MLK Day"  # 3rd Mon Jan
    assert h["2025-05-26"] == "Memorial Day"  # last Mon May
    assert h["2025-11-27"] == "Thanksgiving"  # 4th Thu Nov


def test_us_observed_shift_saturday_to_friday():
    """Christmas 2027 falls on a Saturday -> observed Friday Dec 24."""
    assert date(2027, 12, 25).weekday() == 5  # sanity: Saturday
    h = fetch_holidays.compute_us_federal_holidays(2027)
    assert "2027-12-24" in h and h["2027-12-24"] == "Christmas"
    assert "2027-12-25" not in h


def test_us_observed_shift_sunday_to_monday():
    """Independence Day 2021 falls on a Sunday -> observed Monday Jul 5."""
    assert date(2021, 7, 4).weekday() == 6  # sanity: Sunday
    h = fetch_holidays.compute_us_federal_holidays(2021)
    assert "2021-07-05" in h and h["2021-07-05"] == "Independence Day"
    assert "2021-07-04" not in h


def test_us_new_year_saturday_observes_into_prior_year():
    """Jan 1 2022 is a Saturday: observed Dec 31 2021. So 2021's calendar gains a
    Dec 31 entry and 2022's calendar has NO Jan 1 entry."""
    assert date(2022, 1, 1).weekday() == 5  # Saturday
    y2021 = fetch_holidays.compute_us_federal_holidays(2021)
    y2022 = fetch_holidays.compute_us_federal_holidays(2022)
    assert "2021-12-31" in y2021
    assert "2022-01-01" not in y2022


# --------------------------------------------------------------------------- #
# TW CSV parsing (in-memory sample; HTTP monkeypatched -> no network)         #
# --------------------------------------------------------------------------- #

# data.gov.tw / DGPA shape: 西元日期,星期,是否放假,備註  (是否放假 == "2" => day off)
_TW_CSV_SAMPLE = (
    "西元日期,星期,是否放假,備註\n"
    "20250101,3,2,中華民國開國紀念日\n"
    "20250102,4,0,\n"  # working day -> ignored
    "20250127,1,2,農曆除夕的前一日（彈性放假）\n"
    "20250128,2,2,農曆除夕\n"
    "20250203,1,0,\n"  # working day -> ignored
    "20251231,3,0,\n"  # different year working day
)


def test_tw_parse_extracts_only_holidays_with_names():
    out = fetch_holidays.parse_tw_calendar_csv(_TW_CSV_SAMPLE, year=2025)
    assert out == {
        "2025-01-01": "中華民國開國紀念日",
        "2025-01-27": "農曆除夕的前一日（彈性放假）",
        "2025-01-28": "農曆除夕",
    }
    # Working days are not present.
    assert "2025-01-02" not in out
    assert "2025-02-03" not in out


def test_tw_parse_filters_by_year():
    csv_text = _TW_CSV_SAMPLE + "20260101,4,2,跨年度元旦\n"
    out_2025 = fetch_holidays.parse_tw_calendar_csv(csv_text, year=2025)
    assert "2026-01-01" not in out_2025
    out_2026 = fetch_holidays.parse_tw_calendar_csv(csv_text, year=2026)
    assert out_2026 == {"2026-01-01": "跨年度元旦"}


def test_tw_parse_bad_shape_raises_fetcherror():
    with pytest.raises(fetch_holidays.FetchError):
        fetch_holidays.parse_tw_calendar_csv("foo,bar\n1,2\n", year=2025)


def test_tw_fetch_monkeypatched_no_network(monkeypatch):
    """fetch_tw_holidays must hit NO network: patch the HTTP helper."""
    calls = {"n": 0}

    def fake_get(url, encodings=("utf-8",)):
        calls["n"] += 1
        return _TW_CSV_SAMPLE

    monkeypatch.setattr(fetch_holidays, "_http_get_text", fake_get)
    holidays, source = fetch_holidays.fetch_tw_holidays(2025)
    assert calls["n"] >= 1
    assert holidays["2025-01-28"] == "農曆除夕"
    assert source  # a URL string


def test_http_get_is_monkeypatchable_at_httpx(monkeypatch):
    """Guard: ensure the real httpx.get is reachable for patching, proving the
    fetch path uses httpx (we never let a real request through here)."""
    import httpx

    class _Resp:
        status_code = 200
        content = _TW_CSV_SAMPLE.encode("utf-8")
        text = _TW_CSV_SAMPLE

        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    text = fetch_holidays._http_get_text("https://example.invalid/x")
    assert "農曆除夕" in text


# --------------------------------------------------------------------------- #
# JP CSV parsing (in-memory; 内閣府 shape)                                     #
# --------------------------------------------------------------------------- #

_JP_CSV_SAMPLE = (
    "国民の祝日・休日月日,国民の祝日・休日名称\n"
    "2025/1/1,元日\n"
    "2025/1/13,成人の日\n"
    "2024/12/31,大みそか\n"  # different year -> ignored
)


def test_jp_parse_keeps_year_and_adds_jpo_closure():
    out = fetch_holidays.parse_jp_calendar_csv(_JP_CSV_SAMPLE, 2025)
    assert out["2025-01-01"] == "元日"
    assert out["2025-01-13"] == "成人の日"
    assert "2024-12-31" not in out
    # JPO year-end/new-year closure folded in.
    assert out["2025-12-29"].startswith("年末休")
    assert out["2025-01-03"].startswith("年始休")


# --------------------------------------------------------------------------- #
# CN / KR Nager.Date JSON parsing (in-memory; HTTP monkeypatched -> no network)#
# --------------------------------------------------------------------------- #

_NAGER_CN_SAMPLE = json.dumps(
    [
        {"date": "2025-01-01", "localName": "元旦", "name": "New Year's Day"},
        {"date": "2025-01-29", "localName": "春节", "name": "Chinese New Year"},
        {"date": "2025-10-01", "localName": "国庆节", "name": "National Day"},
        {"date": "2024-12-31", "localName": "旧年", "name": "Prev year"},  # filtered
    ]
)

_NAGER_KR_SAMPLE = json.dumps(
    [
        {"date": "2025-01-01", "localName": "신정", "name": "New Year's Day"},
        {"date": "2025-01-29", "localName": "설날", "name": "Korean New Year"},
        {"date": "2025-10-07", "localName": "추석", "name": "Chuseok"},
        {"date": "2026-01-01", "localName": "신정", "name": "Next year"},  # filtered
    ]
)


def test_nager_parse_keeps_localname_and_filters_year():
    out = fetch_holidays._parse_nager_holidays(_NAGER_CN_SAMPLE, 2025)
    assert out["2025-01-01"] == "元旦"
    assert out["2025-01-29"] == "春节"
    assert out["2025-10-01"] == "国庆节"
    assert "2024-12-31" not in out  # different year dropped


def test_nager_parse_empty_for_year_raises():
    with pytest.raises(fetch_holidays.FetchError):
        fetch_holidays._parse_nager_holidays("[]", 2025)


def test_nager_parse_non_list_raises():
    with pytest.raises(fetch_holidays.FetchError):
        fetch_holidays._parse_nager_holidays('{"date":"2025-01-01"}', 2025)


def test_cn_fetch_monkeypatched_no_network(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, encodings=("utf-8",)):
        calls["n"] += 1
        assert "CN" in url
        return _NAGER_CN_SAMPLE

    monkeypatch.setattr(fetch_holidays, "_http_get_text", fake_get)
    holidays, source = fetch_holidays.fetch_cn_holidays(2025)
    assert calls["n"] == 1
    assert holidays["2025-10-01"] == "国庆节"
    assert source  # a URL string


def test_kr_fetch_monkeypatched_no_network(monkeypatch):
    def fake_get(url, encodings=("utf-8",)):
        assert "KR" in url
        return _NAGER_KR_SAMPLE

    monkeypatch.setattr(fetch_holidays, "_http_get_text", fake_get)
    holidays, source = fetch_holidays.fetch_kr_holidays(2025)
    assert holidays["2025-10-07"] == "추석"
    assert "2026-01-01" not in holidays


# --------------------------------------------------------------------------- #
# EP — hand-curated, no network                                               #
# --------------------------------------------------------------------------- #


def test_ep_fetch_returns_curated_year_no_network(monkeypatch):
    """EP must NOT hit the network: if _http_get_text is called the test fails."""

    def boom(*a, **k):
        raise AssertionError("EP fetch must not touch the network")

    monkeypatch.setattr(fetch_holidays, "_http_get_text", boom)
    holidays, source = fetch_holidays.fetch_ep_holidays(2025)
    assert holidays["2025-12-25"].startswith("Christmas Day")
    assert "approx" in source.lower() or "no network" in source.lower()


def test_ep_fetch_uncurated_year_raises():
    with pytest.raises(fetch_holidays.FetchError):
        fetch_holidays.fetch_ep_holidays(2099)


def test_ep_fetch_matches_shipped_calendar():
    """The curated EP 2025 set must equal the shipped EP_2025.1.json holidays."""
    shipped = json.loads(
        (_ROOT / "data" / "calendars" / "EP_2025.1.json").read_text(encoding="utf-8")
    )["holidays"]
    curated, _ = fetch_holidays.fetch_ep_holidays(2025)
    assert curated == shipped


@pytest.mark.parametrize("jur", ["CN", "KR", "EP"])
def test_new_jurisdictions_registered(jur):
    assert jur in fetch_holidays.FETCHERS
    assert jur in fetch_holidays.SUPPORTED


# --------------------------------------------------------------------------- #
# build_calendar / write_calendar: schema + overwrite-guard + atomicity       #
# --------------------------------------------------------------------------- #


def test_build_calendar_schema_has_required_keys():
    doc = fetch_holidays.build_calendar("US", 2025, "2025.1")
    for key in ("jurisdiction", "version", "holidays"):
        assert key in doc
    assert doc["jurisdiction"] == "US"
    assert doc["version"] == "2025.1"
    assert isinstance(doc["holidays"], dict)
    # provenance extras
    assert "source" in doc and "fetched_at" in doc


def test_build_calendar_rejects_unknown_jurisdiction():
    with pytest.raises(fetch_holidays.FetchError):
        fetch_holidays.build_calendar("DE", 2025, "2025.1")


def test_write_then_unchanged_is_noop(tmp_path):
    doc = fetch_holidays.build_calendar("US", 2025, "2025.1")
    status, _ = fetch_holidays.write_calendar(doc, tmp_path)
    assert status == "written"
    path = tmp_path / "US_2025.1.json"
    assert path.exists()
    mtime = path.stat().st_mtime_ns

    # Re-fetch bumps fetched_at but content is identical -> no write.
    doc2 = fetch_holidays.build_calendar("US", 2025, "2025.1")
    assert doc2["fetched_at"] >= doc["fetched_at"]
    status2, _ = fetch_holidays.write_calendar(doc2, tmp_path)
    assert status2 == "unchanged"
    assert path.stat().st_mtime_ns == mtime  # truly untouched


def test_write_differing_without_force_refuses(tmp_path):
    doc = fetch_holidays.build_calendar("US", 2025, "2025.1")
    fetch_holidays.write_calendar(doc, tmp_path)
    path = tmp_path / "US_2025.1.json"
    before = path.read_text(encoding="utf-8")

    # Corrupt one holiday name -> differing content.
    tampered = dict(doc)
    tampered["holidays"] = dict(doc["holidays"])
    tampered["holidays"]["2025-12-25"] = "Xmas (renamed upstream)"
    status, msgs = fetch_holidays.write_calendar(tampered, tmp_path, force=False)
    assert status == "refused"
    assert path.read_text(encoding="utf-8") == before  # NOT overwritten
    assert any("REFUSING" in m for m in msgs)


def test_write_differing_with_force_overwrites(tmp_path):
    doc = fetch_holidays.build_calendar("US", 2025, "2025.1")
    fetch_holidays.write_calendar(doc, tmp_path)
    path = tmp_path / "US_2025.1.json"

    tampered = dict(doc)
    tampered["holidays"] = dict(doc["holidays"])
    tampered["holidays"]["2025-12-26"] = "Bonus day"
    status, _ = fetch_holidays.write_calendar(tampered, tmp_path, force=True)
    assert status == "overwritten"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "2025-12-26" in written["holidays"]


def test_diff_holidays_added_removed_changed():
    old = {"holidays": {"2025-01-01": "A", "2025-02-02": "B"}}
    new = {"holidays": {"2025-01-01": "A2", "2025-03-03": "C"}}
    added, removed, changed = fetch_holidays.diff_holidays(old, new)
    assert added == ["2025-03-03"]
    assert removed == ["2025-02-02"]
    assert changed == ["2025-01-01"]


# --------------------------------------------------------------------------- #
# Round-trip: a written calendar is consumable by deadline.py's loader        #
# --------------------------------------------------------------------------- #


def test_written_calendar_round_trips_through_deadline_loader(tmp_path, monkeypatch):
    """Write a US calendar via the fetcher, point deadline.py's loader at it,
    and assert calculate_deadline uses those holidays (rolls a deadline that
    lands on a holiday)."""
    pytest.importorskip("backend.ai_engine.deadline")
    from backend.ai_engine import deadline

    fetch_holidays.write_calendar(fetch_holidays.build_calendar("US", 2025, "rt"), tmp_path)

    # Repoint the loader at our tmp dir and clear its cache.
    monkeypatch.setattr(deadline, "CALENDARS_DIR", tmp_path)
    deadline.reload_calendars()

    loaded = deadline.get_holidays("US", "rt")
    assert date(2025, 7, 4) in loaded  # Independence Day present
    assert loaded[date(2025, 12, 25)] == "Christmas"

    # And the deadline engine actually consumes it: a US deadline landing on
    # July 4 (Friday holiday) must roll forward off it.
    # received + 90 days == 2025-07-04 -> received == 2025-04-05.
    received = datetime(2025, 4, 5, 9, 0, tzinfo=UTC)
    res = deadline.calculate_deadline(received, "US", "rt")
    assert not res["statutory_deadline"].startswith("2025-07-04")
    assert not deadline.calendar_is_missing("US", "rt")


def test_atomic_write_leaves_no_temp_files(tmp_path):
    doc = fetch_holidays.build_calendar("US", 2025, "2025.1")
    fetch_holidays.write_calendar(doc, tmp_path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
    assert leftovers == []
