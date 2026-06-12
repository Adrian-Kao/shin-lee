"""Onboarding Gap #1 — bulk patent importer (scripts/import_patents.py).

The importer is a standalone script (no backend imports — it must run on an
operator laptop with only httpx installed), so we load it by path and exercise
the parser units + the batch runner against a mocked AI Engine transport.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "import_patents.py"

spec = importlib.util.spec_from_file_location("import_patents_cli", _SCRIPT)
cli = importlib.util.module_from_spec(spec)
# Must be registered BEFORE exec: the script's @dataclass resolves its own
# module via sys.modules during class processing (future-annotations quirk).
sys.modules["import_patents_cli"] = cli
spec.loader.exec_module(cli)


_TIPO_TXT = """[公開公報] TW202617461 A
公開編號：TW202617461 A
公開日：中華民國 115 年 5 月 1 日（西元 2026-05-01）

【名稱】電動車充電站之充電管理方法及系統

【摘要】
一種電動車充電站之充電管理方法及系統。

【實施方式】
請參閱第一圖，充電場域100包括複數電動車充電站。

【申請專利範圍】
請求項 1：一種電動車充電站之充電管理方法，包括由伺服器執行能源管理方案。
請求項 2：如請求項1所述之方法，其中該第一參考值包括上限電流值。
"""


# ---------------------------------------------------------------------------
# TIPO txt parser
# ---------------------------------------------------------------------------


def test_parse_tipo_txt_extracts_all_fields():
    payload, warnings = cli.parse_tipo_txt(_TIPO_TXT)
    assert payload["patent_no"] == "TW202617461"
    assert payload["title"] == "電動車充電站之充電管理方法及系統"
    assert payload["abstract"].startswith("一種電動車充電站")
    assert len(payload["claims"]) == 2
    assert payload["claims"][1].startswith("如請求項1")
    assert payload["publication_date"] == "2026-05-01"
    assert payload["jurisdiction"] == "TW"
    # spec_text keeps the description but not the claims section.
    assert "請參閱第一圖" in payload["spec_text"]
    assert "申請專利範圍" not in payload["spec_text"]
    assert warnings == []


def test_parse_tipo_txt_real_case_fixture():
    fixture = _REPO_ROOT / "data" / "cases" / "CASE-DEMO-001" / "patent.txt"
    if not fixture.exists():
        pytest.skip("demo case data not present")
    payload, _ = cli.parse_tipo_txt(fixture.read_text(encoding="utf-8"))
    assert payload["patent_no"] == "TW202617461"
    assert payload["claims"], "claims must be extracted from 【申請專利範圍】"
    assert payload["publication_date"] == "2026-05-01"


def test_parse_tipo_txt_missing_patent_no_raises():
    with pytest.raises(ValueError, match="patent number"):
        cli.parse_tipo_txt("【名稱】無編號專利\n【摘要】x\n")


def test_parse_tipo_txt_missing_date_warns_not_fails():
    txt = "公開編號：US1234567 A\n【名稱】Widget\n【摘要】A widget.\n"
    payload, warnings = cli.parse_tipo_txt(txt)
    assert payload["publication_date"] == "1970-01-01"
    assert payload["jurisdiction"] == "US"
    assert any("publication date" in w for w in warnings)


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------


def _json_record(**over):
    rec = {
        "patent_no": "US7654321",
        "title": "Cooling system",
        "abstract": "A cooling system.",
        "claims": ["A cooling system, comprising a base plate."],
        "publication_date": "2018-04-15T00:00:00+00:00",
        "jurisdiction": "US",
    }
    rec.update(over)
    return rec


def test_parse_json_single_object_and_array():
    assert len(cli.parse_json_records(json.dumps(_json_record()))) == 1
    assert len(cli.parse_json_records(json.dumps([_json_record(), _json_record()]))) == 2


def test_parse_json_missing_field_raises():
    bad = _json_record()
    del bad["claims"]
    with pytest.raises(ValueError, match="missing"):
        cli.parse_json_records(json.dumps(bad))


# ---------------------------------------------------------------------------
# Batch runner (mocked engine)
# ---------------------------------------------------------------------------


def _patched_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(**kw):
        kw["transport"] = transport
        return real_client(**kw)

    monkeypatch.setattr(cli.httpx, "Client", _factory)


def test_batch_continues_past_errors_and_reports(tmp_path, monkeypatch):
    (tmp_path / "good.txt").write_text(_TIPO_TXT, encoding="utf-8")
    (tmp_path / "good.json").write_text(json.dumps(_json_record()), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "no_number.txt").write_text("【名稱】沒有編號\n", encoding="utf-8")

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["patent_no"], request.headers.get("x-internal-token")))
        return httpx.Response(200, json={"chunks_indexed": 7, "tenant_id": body["tenant_id"]})

    _patched_client(monkeypatch, handler)
    result = cli.run_import(
        tenant="tenant_demo",
        src_dir=tmp_path,
        engine_url="http://engine:8011",
        internal_token="sekrit",
        dry_run=False,
        recursive=False,
        default_jurisdiction=None,
    )

    # Both good records indexed despite two bad files in the same batch.
    assert {r["patent_no"] for r in result.indexed} == {"US7654321", "TW202617461"}
    assert all(r["chunks"] == 7 for r in result.indexed)
    assert len(result.errors) == 2
    # Internal token forwarded on every request; tenant always overridden.
    assert all(tok == "sekrit" for _, tok in seen)


def test_http_failure_is_an_error_not_a_crash(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text(json.dumps(_json_record()), encoding="utf-8")
    (tmp_path / "b.json").write_text(
        json.dumps(_json_record(patent_no="US9999999")), encoding="utf-8"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["patent_no"] == "US9999999":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"chunks_indexed": 3})

    _patched_client(monkeypatch, handler)
    result = cli.run_import(
        tenant="t",
        src_dir=tmp_path,
        engine_url="http://engine:8011",
        internal_token="",
        dry_run=False,
        recursive=False,
        default_jurisdiction=None,
    )
    assert len(result.indexed) == 1
    assert len(result.errors) == 1
    assert "HTTP 500" in result.errors[0]["error"]


def test_dry_run_sends_nothing(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text(json.dumps(_json_record()), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("dry-run must not call the engine")

    _patched_client(monkeypatch, handler)
    result = cli.run_import(
        tenant="t",
        src_dir=tmp_path,
        engine_url="http://engine:8011",
        internal_token="",
        dry_run=True,
        recursive=False,
        default_jurisdiction=None,
    )
    assert len(result.indexed) == 1
    assert result.indexed[0]["chunks"] is None
    assert result.errors == []


def test_empty_dir_is_an_error(tmp_path):
    result = cli.run_import(
        tenant="t",
        src_dir=tmp_path,
        engine_url="http://engine:8011",
        internal_token="",
        dry_run=True,
        recursive=False,
        default_jurisdiction=None,
    )
    assert result.errors and "no .json or .txt" in result.errors[0]["error"]


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.json").write_text(json.dumps(_json_record()), encoding="utf-8")
    rc = cli.main(["--tenant", "t", "--dir", str(tmp_path), "--dry-run"])
    assert rc == 0

    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    rc = cli.main(["--tenant", "t", "--dir", str(tmp_path), "--dry-run"])
    assert rc == 1  # one record failed → non-zero, but the run completed

    rc = cli.main(["--tenant", "t", "--dir", str(tmp_path / "missing"), "--dry-run"])
    assert rc == 2  # usage error
    capsys.readouterr()


def test_main_writes_csv_report(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_json_record()), encoding="utf-8")
    csv_path = tmp_path / "report.csv"
    rc = cli.main(["--tenant", "t", "--dir", str(tmp_path), "--dry-run", "--csv", str(csv_path)])
    assert rc == 0
    content = csv_path.read_text(encoding="utf-8")
    assert "US7654321" in content


def test_cli_help_runs_as_subprocess():
    """Operator path: must start (and print help) without backend config/env."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0
    assert "--tenant" in proc.stdout and "--dry-run" in proc.stdout
