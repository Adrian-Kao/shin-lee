"""Integration tests for scripts/eval_compare.py.

Strategy: synthesise minimal per-case JSON + summary.json fixtures on the
fly in tmp dirs, then exercise the comparator's pure-Python entry points
(run_compare + build_per_case_delta + project_cost_per_month). This keeps
the tests hermetic — no backend imports, no real eval run, no Anthropic
network calls.

The fixtures intentionally mirror the on-disk shape eval_cases.py writes
so any future schema change to summary.json breaks these tests and forces
us to update both producer + consumer in the same PR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable. tests/conftest.py adds the repo root to
# sys.path; scripts/ is one level deeper so we add it explicitly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import eval_compare  # noqa: E402  (sys.path adjusted above)


# ---------------------------------------------------------------------------
# Fixture builders — tiny per-case + summary JSON that look like what
# eval_cases.py emits.
# ---------------------------------------------------------------------------
def _make_case(
    case_id: str,
    *,
    rejection_type: str = "103_obviousness",
    pred_claims: list[int] | None = None,
    exp_claims: list[int] | None = None,
    rejection_types_match: bool = True,
    received_date_match: bool = True,
    deadline_within_range: bool = True,
    claims_matches: int = 1,
    claims_total: int = 1,
    latency_sec: float = 0.05,
    cost_usd: float = 0.02,
    model: str = "claude-sonnet-4-6",
    prompt_tokens: int = 4000,
    completion_tokens: int = 600,
    status: str = "ok",
) -> dict:
    """Build a single per-case JSON in the shape eval_cases.py writes."""
    pred_claims = pred_claims or [1, 2, 3]
    exp_claims = exp_claims or [1, 2, 3]
    return {
        "case_id": case_id,
        "status": status,
        "latency_sec": latency_sec,
        "model_used": model,
        "cost_meta": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": cost_usd,
            "model": model,
        },
        "predicted": {
            "rejections": [{
                "rejection_type": rejection_type,
                "affected_claims": pred_claims,
                "cited_prior_art": ["US7654321"],
                "confidence": 0.9,
                "examiner_argument_preview": "...",
            }],
            "rejection_types": [rejection_type],
            "received_date": "2025-06-15",
            "statutory_deadline": "2025-08-14",
            "recommended_internal_deadline": "2025-08-07",
            "days_remaining": 60,
            "deadline_warnings": [],
        },
        "expected": {
            "rejections": [{
                "rejection_type": rejection_type,
                "affected_claims": exp_claims,
                "cited_prior_art": ["US7654321"],
                "statute": "35 USC 103",
            }],
            "rejection_types": [rejection_type],
            "received_date": "2025-06-15",
            "deadline_candidates": ["2025-08-14"],
            "response_months": 2,
        },
        "comparison": {
            "rejection_types_match": rejection_types_match,
            "affected_claims_matches": claims_matches,
            "affected_claims_total": claims_total,
            "received_date_match": received_date_match,
            "deadline_within_range": deadline_within_range,
        },
        "drafts": [],
        "retrieval_top_hits": [],
    }


def _make_summary(
    cases: list[dict],
    *,
    mode: str = "mock",
    timestamp: str = "20260605-120000",
    wall_time_sec: float = 0.3,
    cost_provenance: str = "mock",
) -> dict:
    """Build summary.json matching the shape build_summary() produces."""
    ok = [c for c in cases if c.get("status") == "ok"]
    rt_pass = sum(1 for r in ok if r["comparison"]["rejection_types_match"])
    ac_pass = sum(r["comparison"]["affected_claims_matches"] for r in ok)
    ac_total = sum(r["comparison"]["affected_claims_total"] for r in ok)
    rd_pass = sum(1 for r in ok if r["comparison"]["received_date_match"])
    dl_pass = sum(1 for r in ok if r["comparison"]["deadline_within_range"])
    total_input = sum(r["cost_meta"]["prompt_tokens"] for r in ok)
    total_output = sum(r["cost_meta"]["completion_tokens"] for r in ok)
    total_cost = sum(r["cost_meta"]["estimated_cost_usd"] for r in ok)
    by_type: dict[str, dict] = {}
    for r in ok:
        for er in r["expected"]["rejections"]:
            t = er["rejection_type"]
            st = by_type.setdefault(t, {"count": 0, "pass": 0,
                                        "mean_confidence": 0.9,
                                        "mean_latency_ms": 50.0,
                                        "total_input_tokens": 0,
                                        "total_output_tokens": 0,
                                        "total_cost_usd": 0.0})
            st["count"] += 1
            if any(pr["rejection_type"] == t
                   and set(pr["affected_claims"]) == set(er["affected_claims"])
                   for pr in r["predicted"]["rejections"]):
                st["pass"] += 1
            st["total_input_tokens"] += r["cost_meta"]["prompt_tokens"]
            st["total_output_tokens"] += r["cost_meta"]["completion_tokens"]
            st["total_cost_usd"] += r["cost_meta"]["estimated_cost_usd"]
    return {
        "timestamp": timestamp,
        "mode": mode,
        "n_cases": len(cases),
        "n_completed": len(ok),
        "n_errors": len(cases) - len(ok),
        "wall_time_sec": wall_time_sec,
        "rejection_type_correct": rt_pass,
        "rejection_type_total": len(ok),
        "affected_claims_correct": ac_pass,
        "affected_claims_total": ac_total,
        "received_date_correct": rd_pass,
        "received_date_total": len(ok),
        "deadline_correct": dl_pass,
        "deadline_total": len(ok),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": total_cost,
        "by_type": by_type,
        "case_ids": sorted(c["case_id"] for c in cases),
        "cost_provenance": cost_provenance,
        "schema_version": 1,
        "mean_latency_ms": 50.0,
        "p95_latency_ms": 60.0,
    }


def _write_eval_dir(tmp: Path, cases: list[dict], summary: dict | None = None) -> Path:
    """Write the per-case JSON + summary.json files into tmp/eval_*. Return the dir."""
    tmp.mkdir(parents=True, exist_ok=True)
    for c in cases:
        (tmp / f"{c['case_id']}.json").write_text(
            json.dumps(c, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    if summary is not None:
        (tmp / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    # REPORT.md isn't strictly required by the comparator, but eval_cases
    # always writes it, so we add a stub to mirror reality.
    (tmp / "REPORT.md").write_text("# test eval dir\n", encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_compare_identical_runs_reports_zero_delta(tmp_path: Path):
    """Comparing a run to itself: every delta is zero, no improvements, no regressions."""
    cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness"),
        _make_case("CASE-DEMO-002", rejection_type="102_novelty",
                   pred_claims=[1], exp_claims=[1]),
    ]
    summary = _make_summary(cases)
    baseline = _write_eval_dir(tmp_path / "baseline", cases, summary)
    candidate = _write_eval_dir(tmp_path / "candidate", cases, summary)

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))

    # Every case overlaps, no improvements, no regressions.
    assert set(payload["delta"]["overlap"]) == {"CASE-DEMO-001", "CASE-DEMO-002"}
    assert payload["delta"]["baseline_only"] == []
    assert payload["delta"]["candidate_only"] == []
    for cid, entry in payload["delta"]["cases"].items():
        assert entry["deltas"]["rejection_types_changed"] is False, cid
        assert entry["deltas"]["claims_match_delta"] == 0, cid
        assert entry["deltas"]["latency_delta_sec"] == 0.0, cid
        assert entry["deltas"]["cost_delta_usd"] == 0.0, cid
        assert entry["deltas"]["regressed"] is False, cid
        assert entry["deltas"]["improved"] is False, cid

    # COMPARE.md should not surface any improvements / regressions.
    md = (out / "COMPARE.md").read_text(encoding="utf-8")
    # The two list sections both fall back to "(none)" when empty.
    improved_section = md.split("## Most improved cases")[1].split("##")[0]
    regressed_section = md.split("## Regressions")[1].split("##")[0]
    assert "(none)" in improved_section
    assert "(none)" in regressed_section


def test_compare_detects_classification_regression(tmp_path: Path):
    """Candidate predicts wrong type on one case → that case is flagged as regression."""
    baseline_cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness",
                   rejection_types_match=True),
        _make_case("CASE-DEMO-002", rejection_type="102_novelty",
                   rejection_types_match=True, pred_claims=[1, 2],
                   exp_claims=[1, 2], claims_matches=1, claims_total=1),
    ]
    # Candidate gets CASE-DEMO-001 wrong: predicts other but expected 103.
    candidate_cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness",
                   rejection_types_match=False, claims_matches=0,
                   claims_total=1),
        _make_case("CASE-DEMO-002", rejection_type="102_novelty",
                   rejection_types_match=True, pred_claims=[1, 2],
                   exp_claims=[1, 2], claims_matches=1, claims_total=1),
    ]
    baseline = _write_eval_dir(tmp_path / "baseline", baseline_cases,
                               _make_summary(baseline_cases))
    candidate = _write_eval_dir(tmp_path / "candidate", candidate_cases,
                                _make_summary(candidate_cases))

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))

    # CASE-DEMO-001 must be flagged as regression (rej_types_match dropped + claims_match dropped).
    case1 = payload["delta"]["cases"]["CASE-DEMO-001"]
    assert case1["deltas"]["regressed"] is True
    assert case1["deltas"]["improved"] is False
    assert case1["deltas"]["claims_match_delta"] == -1

    # CASE-DEMO-002 unchanged.
    case2 = payload["delta"]["cases"]["CASE-DEMO-002"]
    assert case2["deltas"]["regressed"] is False
    assert case2["deltas"]["improved"] is False

    # COMPARE.md should list CASE-DEMO-001 in the regressions section.
    md = (out / "COMPARE.md").read_text(encoding="utf-8")
    regressed_section = md.split("## Regressions")[1].split("##")[0]
    assert "CASE-DEMO-001" in regressed_section
    # And NOT in the most-improved section.
    improved_section = md.split("## Most improved cases")[1].split("##")[0]
    assert "CASE-DEMO-001" not in improved_section


def test_compare_handles_disjoint_case_sets(tmp_path: Path):
    """Baseline + candidate cover different cases → warn + compare overlap only."""
    baseline_cases = [
        _make_case("CASE-DEMO-001"),
        _make_case("CASE-DEMO-002"),
        _make_case("CASE-DEMO-003"),
    ]
    # Candidate dropped 002 + added 004.
    candidate_cases = [
        _make_case("CASE-DEMO-001"),
        _make_case("CASE-DEMO-003"),
        _make_case("CASE-DEMO-004"),
    ]
    baseline = _write_eval_dir(tmp_path / "baseline", baseline_cases,
                               _make_summary(baseline_cases))
    candidate = _write_eval_dir(tmp_path / "candidate", candidate_cases,
                                _make_summary(candidate_cases))

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))

    # Only the intersection is compared.
    assert sorted(payload["delta"]["overlap"]) == ["CASE-DEMO-001", "CASE-DEMO-003"]
    assert payload["delta"]["baseline_only"] == ["CASE-DEMO-002"]
    assert payload["delta"]["candidate_only"] == ["CASE-DEMO-004"]

    md = (out / "COMPARE.md").read_text(encoding="utf-8")
    # COMPARE.md must call out the mismatch explicitly so a reviewer can't
    # miss it.
    assert "WARNING" in md
    assert "CASE-DEMO-002" in md
    assert "CASE-DEMO-004" in md
    # The per-case table only lists the overlap.
    assert "| CASE-DEMO-001 |" in md
    assert "| CASE-DEMO-003 |" in md
    # CASE-DEMO-002 / 004 must appear in the warning blurb but NOT as a
    # per-case table row. The per-case table rows start with '| CASE-' and
    # have rejection-type cells; the warning blurb mentions them in prose.
    table_rows = [line for line in md.splitlines()
                  if line.startswith("| CASE-DEMO-")
                  and " | y |" in line or " | n |" in line]
    assert all("CASE-DEMO-002" not in row for row in table_rows)
    assert all("CASE-DEMO-004" not in row for row in table_rows)


def test_compare_cost_projection_math(tmp_path: Path):
    """Cost projection multiplies per-case cost × monthly volume × 12 for annual."""
    # 4 cases at $0.05 each → $0.20 total, $0.05/case → 1000 OAs = $50/month.
    cases = [_make_case(f"CASE-DEMO-00{i+1}", cost_usd=0.05) for i in range(4)]
    summary = _make_summary(cases, mode="anthropic", cost_provenance="exact")
    # Tweak provenance to exact so the projection note doesn't carry the
    # mock-mode WARNING (which would still pass this test but obscure intent).
    baseline = _write_eval_dir(tmp_path / "baseline", cases, summary)
    candidate = _write_eval_dir(tmp_path / "candidate", cases, summary)

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))

    proj = payload["projection"]
    assert proj["per_case_cost_usd"] == pytest.approx(0.05, abs=1e-6)
    assert proj["monthly_volume"] == 1000
    assert proj["projected_monthly_usd"] == pytest.approx(50.0, abs=1e-3)
    assert proj["annual_usd"] == pytest.approx(600.0, abs=1e-3)
    assert "exact" in proj["note"]
    # Crucially: when provenance is exact, the mock-mode WARNING must NOT
    # appear — otherwise it would be a stale signal for a real run.
    assert "WARNING" not in proj["note"]

    # Direct call to project_cost_per_month — sanity-check the math via a
    # different code path so the test isn't tautological.
    direct = eval_compare.project_cost_per_month(summary, n_completed_for_cost=4,
                                                 monthly_volume=2000)
    assert direct["per_case_cost_usd"] == pytest.approx(0.05, abs=1e-6)
    assert direct["projected_monthly_usd"] == pytest.approx(100.0, abs=1e-3)
    assert direct["annual_usd"] == pytest.approx(1200.0, abs=1e-3)


def test_summary_json_round_trip(tmp_path: Path):
    """Summary written by build_summary deserialises back into the comparator unchanged."""
    cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness",
                   claims_matches=1, claims_total=1),
        _make_case("CASE-DEMO-002", rejection_type="102_novelty",
                   pred_claims=[1, 2], exp_claims=[1, 2],
                   claims_matches=1, claims_total=1),
        _make_case("CASE-DEMO-003", rejection_type="antecedent_basis",
                   pred_claims=[5], exp_claims=[5],
                   claims_matches=1, claims_total=1),
    ]
    summary = _make_summary(cases, mode="anthropic", cost_provenance="exact",
                            timestamp="20260605-120000")
    eval_dir = _write_eval_dir(tmp_path / "round_trip", cases, summary)

    # Load via the comparator's loader and assert key fields survive intact.
    reloaded = eval_compare._load_summary(eval_dir)
    assert reloaded["mode"] == "anthropic"
    assert reloaded["cost_provenance"] == "exact"
    assert reloaded["n_cases"] == 3
    assert reloaded["n_completed"] == 3
    assert reloaded["rejection_type_correct"] == 3
    assert reloaded["affected_claims_correct"] == 3
    assert reloaded["affected_claims_total"] == 3
    # by_type breakdown survives.
    assert set(reloaded["by_type"].keys()) == {
        "103_obviousness", "102_novelty", "antecedent_basis"
    }
    assert reloaded["schema_version"] == 1

    # Also test the per-case loader — case_id key matches the field, not the
    # filename.
    per_case = eval_compare._load_per_case(eval_dir)
    assert set(per_case.keys()) == {"CASE-DEMO-001", "CASE-DEMO-002", "CASE-DEMO-003"}
    assert per_case["CASE-DEMO-001"]["comparison"]["rejection_types_match"] is True


def test_compare_fallback_when_summary_json_missing(tmp_path: Path):
    """Old eval dirs (no summary.json) still compare — the loader synthesises one."""
    cases = [_make_case("CASE-DEMO-001"), _make_case("CASE-DEMO-002")]
    # Write WITHOUT summary.json.
    baseline = _write_eval_dir(tmp_path / "baseline", cases, summary=None)
    candidate = _write_eval_dir(tmp_path / "candidate", cases, summary=None)

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))

    # Synthesised summary should still report n_cases correctly.
    assert payload["baseline_summary"]["n_cases"] == 2
    assert payload["baseline_summary"]["mode"] == "unknown"
    assert payload["candidate_summary"]["cost_provenance"] == "unknown"
    # Schema version 0 signals the synthesised fallback.
    assert payload["baseline_summary"]["schema_version"] == 0


def test_compare_improvement_detection(tmp_path: Path):
    """Candidate gets a previously-failed case right → improved, not regressed."""
    baseline_cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness",
                   rejection_types_match=False, claims_matches=0, claims_total=1),
    ]
    candidate_cases = [
        _make_case("CASE-DEMO-001", rejection_type="103_obviousness",
                   rejection_types_match=True, claims_matches=1, claims_total=1),
    ]
    baseline = _write_eval_dir(tmp_path / "baseline", baseline_cases,
                               _make_summary(baseline_cases))
    candidate = _write_eval_dir(tmp_path / "candidate", candidate_cases,
                                _make_summary(candidate_cases))

    out = eval_compare.run_compare(baseline, candidate, output_root=tmp_path / "out")
    payload = json.loads((out / "per_case_delta.json").read_text(encoding="utf-8"))
    case1 = payload["delta"]["cases"]["CASE-DEMO-001"]
    assert case1["deltas"]["improved"] is True
    assert case1["deltas"]["regressed"] is False
    assert case1["deltas"]["claims_match_delta"] == 1

    md = (out / "COMPARE.md").read_text(encoding="utf-8")
    improved_section = md.split("## Most improved cases")[1].split("##")[0]
    assert "CASE-DEMO-001" in improved_section
