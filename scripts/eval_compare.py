"""Side-by-side comparison harness for two eval_cases.py output directories.

CLI:
    python scripts/eval_compare.py <baseline_dir> <candidate_dir> [--output DIR]
                                   [--projection-volume N]

Reads `summary.json` + per-case `CASE-DEMO-NN.json` from each input dir,
emits:
    <out>/COMPARE.md          — human-facing delta report
    <out>/per_case_delta.json — machine-facing diff for downstream tooling

Typical use:
    # baseline: mock run; candidate: real Anthropic run
    python scripts/eval_compare.py \\
        data/eval_results/20260605-100000-aaa111 \\
        data/eval_results/20260605-120000-bbb222

The comparison is tolerant of:
    - Disjoint case sets (warns; compares only overlapping case_ids).
    - Missing summary.json (falls back to recomputing aggregate from per-case
      JSON; emits a warning since summary.json is the contract).
    - Mixed cost provenance (mock vs anthropic vs fallback) — the projection
      cell prints a warning and disables the extrapolation when the candidate
      is mock-priced.

Design intent: this script is the SECOND artefact the user looks at when
their Anthropic key arrives (the FIRST being scripts/anthropic_smoke.py).
It must explain — in 30 seconds — whether real Anthropic is worth the cost
delta over the mock harness.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("eval_compare")

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Cost projection volume default (per-month OA estimate). Configurable via
# --projection-volume; chosen as 1000 to match the docstring guidance in
# docs/EVAL_PLAYBOOK.md ("cost projection to 1k OAs/month").
_DEFAULT_PROJECTION_VOLUME = 1000


# ---------------------------------------------------------------------------
# 1. Load helpers — both summary.json AND per-case JSON.
# ---------------------------------------------------------------------------
def _load_summary(eval_dir: Path) -> dict:
    """Read summary.json; if missing, synthesize a minimal one from per-case JSON.

    The synthesis path exists so old eval outputs (pre-summary.json) still
    compare cleanly — but we log a warning so the user knows the cost figures
    are recomputed rather than canonical.
    """
    summary_path = eval_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    logger.warning(
        "summary.json missing from %s — falling back to per-case JSON. "
        "Re-run eval_cases.py to populate summary.json for stricter diffs.",
        eval_dir,
    )
    cases = _load_per_case(eval_dir)
    return _synthesize_summary_from_cases(cases, eval_dir.name)


def _synthesize_summary_from_cases(cases: dict[str, dict], timestamp_hint: str) -> dict:
    """Best-effort reconstruct summary when summary.json is absent.

    Does NOT compute by_type breakdown (that's only useful for diffing
    summaries against each other, and we already warned the user). Keeps
    every key the COMPARE.md renderer reads.
    """
    ok = [c for c in cases.values() if c.get("status") == "ok"]
    rt_pass = sum(1 for r in ok if r["comparison"]["rejection_types_match"])
    ac_pass = sum(r["comparison"]["affected_claims_matches"] for r in ok)
    ac_total = sum(r["comparison"]["affected_claims_total"] for r in ok)
    rd_pass = sum(1 for r in ok if r["comparison"]["received_date_match"])
    dl_pass = sum(1 for r in ok if r["comparison"]["deadline_within_range"])
    total_input = sum(r["cost_meta"]["prompt_tokens"] for r in ok)
    total_output = sum(r["cost_meta"]["completion_tokens"] for r in ok)
    total_cost = sum(r["cost_meta"]["estimated_cost_usd"] for r in ok)
    return {
        "timestamp": timestamp_hint,
        "mode": "unknown",
        "n_cases": len(cases),
        "n_completed": len(ok),
        "n_errors": len(cases) - len(ok),
        "wall_time_sec": 0.0,
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
        "by_type": {},
        "case_ids": sorted(cases.keys()),
        "cost_provenance": "unknown",
        "schema_version": 0,
    }


def _load_per_case(eval_dir: Path) -> dict[str, dict]:
    """Load every `CASE-*.json` (or any *.json that has a 'case_id' key).

    REPORT.md / summary.json are skipped by extension + presence-of-case_id.
    """
    out: dict[str, dict] = {}
    if not eval_dir.exists() or not eval_dir.is_dir():
        raise FileNotFoundError(f"eval dir not found: {eval_dir}")
    for p in sorted(eval_dir.glob("*.json")):
        if p.name in ("summary.json", "per_case_delta.json"):
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("Skipping %s (invalid JSON: %s)", p, e)
            continue
        cid = payload.get("case_id") or p.stem
        out[cid] = payload
    return out


# ---------------------------------------------------------------------------
# 2. Per-case delta — small struct, easy to JSON-dump.
# ---------------------------------------------------------------------------
def build_per_case_delta(
    baseline: dict[str, dict],
    candidate: dict[str, dict],
) -> dict:
    """Diff each overlapping case across baseline/candidate.

    Output shape:
        {
          "overlap": [case_id, ...],
          "baseline_only": [case_id, ...],
          "candidate_only": [case_id, ...],
          "cases": {
            case_id: {
              "baseline": {rejection_types, claims_match, latency_sec, cost_usd, ...},
              "candidate": {...same shape...},
              "deltas": {
                "rejection_types_changed": bool,
                "claims_match_delta": int,           # candidate - baseline
                "latency_delta_sec": float,          # candidate - baseline
                "cost_delta_usd": float,             # candidate - baseline
                "regressed": bool,                   # candidate did strictly worse
                "improved": bool,                    # candidate did strictly better
              }
            }, ...
          }
        }

    `regressed` triggers when candidate failed classification that baseline
    passed, OR when candidate's claims-match count dropped. `improved` is
    the symmetric case. Both can be False (no change).
    """
    b_keys = set(baseline.keys())
    c_keys = set(candidate.keys())
    overlap = sorted(b_keys & c_keys)
    baseline_only = sorted(b_keys - c_keys)
    candidate_only = sorted(c_keys - b_keys)

    cases_out: dict[str, dict] = {}
    for cid in overlap:
        b = baseline[cid]
        c = candidate[cid]
        b_snap = _case_snapshot(b)
        c_snap = _case_snapshot(c)

        rejection_types_changed = b_snap["rejection_types"] != c_snap["rejection_types"]
        claims_match_delta = (
            c_snap["claims_match"] - b_snap["claims_match"]
        )
        latency_delta_sec = round(
            c_snap["latency_sec"] - b_snap["latency_sec"], 4
        )
        cost_delta_usd = round(
            c_snap["cost_usd"] - b_snap["cost_usd"], 6
        )

        # "Regressed" = candidate did materially worse on classification quality.
        # We DON'T count higher cost/latency as a regression here — those are
        # expected when moving mock → real and are surfaced in the aggregate
        # cells. The regression list is only about answer quality.
        b_rt_ok = b_snap["rejection_types_match"]
        c_rt_ok = c_snap["rejection_types_match"]
        regressed = bool(
            (b_rt_ok and not c_rt_ok)
            or (claims_match_delta < 0)
            or (b_snap["received_date_match"] and not c_snap["received_date_match"])
            or (b_snap["deadline_within_range"] and not c_snap["deadline_within_range"])
        )
        improved = bool(
            (not b_rt_ok and c_rt_ok)
            or (claims_match_delta > 0)
            or (not b_snap["received_date_match"] and c_snap["received_date_match"])
            or (not b_snap["deadline_within_range"] and c_snap["deadline_within_range"])
        )

        cases_out[cid] = {
            "baseline": b_snap,
            "candidate": c_snap,
            "deltas": {
                "rejection_types_changed": rejection_types_changed,
                "claims_match_delta": claims_match_delta,
                "latency_delta_sec": latency_delta_sec,
                "cost_delta_usd": cost_delta_usd,
                "regressed": regressed,
                "improved": improved,
            },
        }
    return {
        "overlap": overlap,
        "baseline_only": baseline_only,
        "candidate_only": candidate_only,
        "cases": cases_out,
    }


def _case_snapshot(case: dict) -> dict:
    """Project a per-case JSON down to the fields the comparator cares about.

    Tolerates `status == "error"` cases by returning sentinel zeros so the
    diff math doesn't blow up; the COMPARE.md renderer prints "ERROR" for
    those slots.
    """
    if case.get("status") != "ok":
        return {
            "status": case.get("status", "unknown"),
            "rejection_types": [],
            "rejection_types_match": False,
            "claims_match": 0,
            "claims_total": 0,
            "received_date_match": False,
            "deadline_within_range": False,
            "latency_sec": case.get("latency_sec", 0.0),
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": "",
        }
    return {
        "status": "ok",
        "rejection_types": sorted(case["predicted"]["rejection_types"]),
        "rejection_types_match": case["comparison"]["rejection_types_match"],
        "claims_match": case["comparison"]["affected_claims_matches"],
        "claims_total": case["comparison"]["affected_claims_total"],
        "received_date_match": case["comparison"]["received_date_match"],
        "deadline_within_range": case["comparison"]["deadline_within_range"],
        "latency_sec": case.get("latency_sec", 0.0),
        "cost_usd": case["cost_meta"]["estimated_cost_usd"],
        "input_tokens": case["cost_meta"]["prompt_tokens"],
        "output_tokens": case["cost_meta"]["completion_tokens"],
        "model": case["cost_meta"].get("model", ""),
    }


# ---------------------------------------------------------------------------
# 3. Cost projection — uses the canonical pricing table from rate_limit.
# ---------------------------------------------------------------------------
def project_cost_per_month(
    candidate_summary: dict,
    n_completed_for_cost: int,
    monthly_volume: int = _DEFAULT_PROJECTION_VOLUME,
) -> dict:
    """Linear extrapolation: per-case cost × monthly_volume.

    Returns:
        {
          "per_case_cost_usd": float,
          "monthly_volume": int,
          "projected_monthly_usd": float,
          "annual_usd": float,
          "note": str   # provenance + caveats
        }

    `n_completed_for_cost` is the divisor — usually summary.n_completed. We
    take it as an argument so the caller can override (e.g. for a partial
    eval that errored out halfway).
    """
    total_cost = float(candidate_summary.get("total_cost_usd", 0.0))
    if n_completed_for_cost <= 0:
        return {
            "per_case_cost_usd": 0.0,
            "monthly_volume": monthly_volume,
            "projected_monthly_usd": 0.0,
            "annual_usd": 0.0,
            "note": "no completed cases; projection skipped",
        }
    per_case = total_cost / n_completed_for_cost
    monthly = per_case * monthly_volume
    annual = monthly * 12.0
    provenance = candidate_summary.get("cost_provenance", "unknown")
    note = f"provenance={provenance}"
    if provenance == "mock":
        note += (
            "; WARNING — candidate ran in mock mode. Projected cost is "
            "synthesised from a fallback pricing table, NOT real Anthropic "
            "billing. Re-run with --mode anthropic for an accurate figure."
        )
    elif provenance == "fallback":
        note += (
            "; WARNING — at least one model used the fallback pricing row "
            "(unrecognised model name). Per-case cost may be ±20%."
        )
    return {
        "per_case_cost_usd": round(per_case, 6),
        "monthly_volume": monthly_volume,
        "projected_monthly_usd": round(monthly, 2),
        "annual_usd": round(annual, 2),
        "note": note,
    }


# ---------------------------------------------------------------------------
# 4. Markdown rendering.
# ---------------------------------------------------------------------------
def _pct_delta(b: int, b_total: int, c: int, c_total: int) -> str:
    """Format a 'baseline → candidate (Δ%)' string for accuracy cells.

    Both b_total and c_total can differ when the two runs covered different
    case counts; we compute the rate independently and show the absolute
    percentage-point delta. Returns '—' if either total is zero.
    """
    if b_total == 0 or c_total == 0:
        return "—"
    b_rate = b / b_total * 100
    c_rate = c / c_total * 100
    sign = "+" if c_rate >= b_rate else ""
    return f"{b_rate:.1f}% → {c_rate:.1f}% ({sign}{c_rate - b_rate:.1f}pp)"


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def build_compare_report(
    baseline_summary: dict,
    candidate_summary: dict,
    delta: dict,
    projection: dict,
    timestamp: str,
    baseline_dir: Path,
    candidate_dir: Path,
) -> str:
    """Render COMPARE.md from the diff payloads.

    Layout matches the brief: top-line aggregate → per-case table → per-type
    breakdown → "most improved" / "regressions" → cost projection.
    """
    L: list[str] = []
    L.append(f"# PatentMind eval comparison — {timestamp}")
    L.append("")
    L.append(f"- Baseline: `{baseline_dir}` (mode={baseline_summary.get('mode')}, "
             f"timestamp={baseline_summary.get('timestamp')})")
    L.append(f"- Candidate: `{candidate_dir}` (mode={candidate_summary.get('mode')}, "
             f"timestamp={candidate_summary.get('timestamp')})")
    L.append("")

    overlap = delta["overlap"]
    baseline_only = delta["baseline_only"]
    candidate_only = delta["candidate_only"]
    if baseline_only or candidate_only:
        L.append("> WARNING — case sets do not match.")
        if baseline_only:
            L.append(f"> - Only in baseline ({len(baseline_only)}): "
                     f"{', '.join(baseline_only[:10])}"
                     f"{' …' if len(baseline_only) > 10 else ''}")
        if candidate_only:
            L.append(f"> - Only in candidate ({len(candidate_only)}): "
                     f"{', '.join(candidate_only[:10])}"
                     f"{' …' if len(candidate_only) > 10 else ''}")
        L.append(f"> - Comparing the {len(overlap)} overlapping case_ids only.")
        L.append("")

    # ---- Aggregate metrics table ----
    L.append("## Aggregate metrics")
    L.append("")
    L.append("| Metric | Baseline | Candidate | Delta |")
    L.append("|--------|----------|-----------|-------|")
    L.append(_aggregate_row(
        "rejection_type accuracy",
        baseline_summary.get("rejection_type_correct", 0),
        baseline_summary.get("rejection_type_total", 0),
        candidate_summary.get("rejection_type_correct", 0),
        candidate_summary.get("rejection_type_total", 0),
    ))
    L.append(_aggregate_row(
        "affected_claims accuracy",
        baseline_summary.get("affected_claims_correct", 0),
        baseline_summary.get("affected_claims_total", 0),
        candidate_summary.get("affected_claims_correct", 0),
        candidate_summary.get("affected_claims_total", 0),
    ))
    L.append(_aggregate_row(
        "received_date accuracy",
        baseline_summary.get("received_date_correct", 0),
        baseline_summary.get("received_date_total", 0),
        candidate_summary.get("received_date_correct", 0),
        candidate_summary.get("received_date_total", 0),
    ))
    L.append(_aggregate_row(
        "deadline accuracy",
        baseline_summary.get("deadline_correct", 0),
        baseline_summary.get("deadline_total", 0),
        candidate_summary.get("deadline_correct", 0),
        candidate_summary.get("deadline_total", 0),
    ))
    # Time + cost
    b_wall = baseline_summary.get("wall_time_sec", 0.0)
    c_wall = candidate_summary.get("wall_time_sec", 0.0)
    L.append(
        f"| total wall time | {b_wall:.1f}s | {c_wall:.1f}s |"
        f" {c_wall - b_wall:+.1f}s |"
    )
    b_cost = baseline_summary.get("total_cost_usd", 0.0)
    c_cost = candidate_summary.get("total_cost_usd", 0.0)
    L.append(
        f"| total cost | ${b_cost:.4f} | ${c_cost:.4f} |"
        f" ${c_cost - b_cost:+.4f} |"
    )
    b_in = baseline_summary.get("total_input_tokens", 0)
    c_in = candidate_summary.get("total_input_tokens", 0)
    L.append(
        f"| total input tokens | {b_in:,} | {c_in:,} | {c_in - b_in:+,} |"
    )
    b_out = baseline_summary.get("total_output_tokens", 0)
    c_out = candidate_summary.get("total_output_tokens", 0)
    L.append(
        f"| total output tokens | {b_out:,} | {c_out:,} | {c_out - b_out:+,} |"
    )
    L.append("")

    # ---- Per-case detail table ----
    L.append("## Per-case detail")
    L.append("")
    L.append(
        "| case_id | mock rej | real rej | rej match? | mock claims | real claims |"
        " claims match? | mock latency | real latency | mock cost | real cost |"
    )
    L.append(
        "|---------|----------|----------|------------|-------------|-------------|"
        "----------------|--------------|--------------|-----------|-----------|"
    )
    for cid in overlap:
        d = delta["cases"][cid]
        b = d["baseline"]
        c = d["candidate"]
        rej_match = "y" if b["rejection_types"] == c["rejection_types"] else "n"
        claims_match = "y" if (b["claims_match"] == c["claims_match"]
                               and b["claims_total"] == c["claims_total"]) else "n"
        L.append(
            f"| {cid} | {','.join(b['rejection_types'])[:18] or '-'} |"
            f" {','.join(c['rejection_types'])[:18] or '-'} | {rej_match} |"
            f" {b['claims_match']}/{b['claims_total']} |"
            f" {c['claims_match']}/{c['claims_total']} | {claims_match} |"
            f" {b['latency_sec']:.2f}s | {c['latency_sec']:.2f}s |"
            f" ${b['cost_usd']:.4f} | ${c['cost_usd']:.4f} |"
        )
    L.append("")

    # ---- Per-rejection-type breakdown ----
    L.append("## Per-rejection-type breakdown")
    L.append("")
    L.append("| Type | Baseline pass | Candidate pass | Delta |")
    L.append("|------|---------------|----------------|-------|")
    b_types = baseline_summary.get("by_type", {})
    c_types = candidate_summary.get("by_type", {})
    all_types = sorted(set(b_types.keys()) | set(c_types.keys()))
    for t in all_types:
        b_st = b_types.get(t, {})
        c_st = c_types.get(t, {})
        b_p = b_st.get("pass", 0)
        b_c = b_st.get("count", 0)
        c_p = c_st.get("pass", 0)
        c_c = c_st.get("count", 0)
        L.append(
            f"| {t} | {b_p}/{b_c} ({_safe_div(b_p, b_c) * 100:.0f}%) |"
            f" {c_p}/{c_c} ({_safe_div(c_p, c_c) * 100:.0f}%) |"
            f" {c_p - b_p:+d} |"
        )
    L.append("")

    # ---- Most improved + regressions ----
    improved = [cid for cid in overlap if delta["cases"][cid]["deltas"]["improved"]]
    regressed = [cid for cid in overlap if delta["cases"][cid]["deltas"]["regressed"]]

    L.append("## Most improved cases (candidate > baseline)")
    L.append("")
    if not improved:
        L.append("- (none)")
    else:
        for cid in improved[:5]:
            d = delta["cases"][cid]
            L.append(
                f"- **{cid}**: rej_types `{d['baseline']['rejection_types']}` → "
                f"`{d['candidate']['rejection_types']}`; "
                f"claims {d['baseline']['claims_match']}/{d['baseline']['claims_total']} → "
                f"{d['candidate']['claims_match']}/{d['candidate']['claims_total']}"
            )
    L.append("")

    L.append("## Regressions (candidate < baseline)")
    L.append("")
    if not regressed:
        L.append("- (none)")
    else:
        for cid in regressed[:5]:
            d = delta["cases"][cid]
            L.append(
                f"- **{cid}**: rej_types `{d['baseline']['rejection_types']}` → "
                f"`{d['candidate']['rejection_types']}`; "
                f"claims {d['baseline']['claims_match']}/{d['baseline']['claims_total']} → "
                f"{d['candidate']['claims_match']}/{d['candidate']['claims_total']}"
            )
    L.append("")

    # ---- Cost projection ----
    L.append("## Cost projection")
    L.append("")
    L.append(
        f"Extrapolated at {projection['monthly_volume']:,} OAs/month based on this "
        f"run's per-case cost:"
    )
    L.append("")
    L.append(f"- Per-case cost: ${projection['per_case_cost_usd']:.4f}")
    L.append(f"- Projected monthly: ${projection['projected_monthly_usd']:,.2f}")
    L.append(f"- Projected annual:  ${projection['annual_usd']:,.2f}")
    L.append(f"- Notes: {projection['note']}")
    L.append("")

    return "\n".join(L) + "\n"


def _aggregate_row(label: str, b_pass: int, b_total: int, c_pass: int, c_total: int) -> str:
    """One row in the aggregate metrics table."""
    return (
        f"| {label} | {b_pass}/{b_total} | {c_pass}/{c_total} |"
        f" {_pct_delta(b_pass, b_total, c_pass, c_total)} |"
    )


# ---------------------------------------------------------------------------
# 5. CLI glue.
# ---------------------------------------------------------------------------
def run_compare(
    baseline_dir: Path,
    candidate_dir: Path,
    output_root: Optional[Path] = None,
    monthly_volume: int = _DEFAULT_PROJECTION_VOLUME,
) -> Path:
    """Programmatic entry point — used by both the CLI and the tests.

    Returns the path to the directory containing COMPARE.md + per_case_delta.json.
    """
    baseline_dir = baseline_dir.resolve()
    candidate_dir = candidate_dir.resolve()
    baseline_summary = _load_summary(baseline_dir)
    candidate_summary = _load_summary(candidate_dir)
    baseline_cases = _load_per_case(baseline_dir)
    candidate_cases = _load_per_case(candidate_dir)

    delta = build_per_case_delta(baseline_cases, candidate_cases)

    n_completed = candidate_summary.get("n_completed", len(candidate_cases))
    projection = project_cost_per_month(candidate_summary, n_completed, monthly_volume)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_root = output_root or (_REPO_ROOT / "data" / "eval_compare")
    out_dir = out_root / f"{timestamp}-{uuid.uuid4().hex[:6]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = build_compare_report(
        baseline_summary,
        candidate_summary,
        delta,
        projection,
        timestamp,
        baseline_dir,
        candidate_dir,
    )
    (out_dir / "COMPARE.md").write_text(report, encoding="utf-8")

    delta_payload = {
        "timestamp": timestamp,
        "baseline_dir": str(baseline_dir),
        "candidate_dir": str(candidate_dir),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "delta": delta,
        "projection": projection,
    }
    (out_dir / "per_case_delta.json").write_text(
        json.dumps(delta_payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    return out_dir


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two eval_cases.py output directories. Typical use: "
            "baseline = mock run, candidate = anthropic run. Emits "
            "COMPARE.md + per_case_delta.json."
        )
    )
    parser.add_argument("baseline_dir", type=Path)
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("--output", type=Path,
                        help="Output root dir. Default: data/eval_compare/")
    parser.add_argument("--projection-volume", type=int,
                        default=_DEFAULT_PROJECTION_VOLUME,
                        help=f"Monthly OA volume for cost projection "
                             f"(default {_DEFAULT_PROJECTION_VOLUME}).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not args.baseline_dir.exists():
        print(f"Error: baseline dir not found: {args.baseline_dir}", file=sys.stderr)
        return 2
    if not args.candidate_dir.exists():
        print(f"Error: candidate dir not found: {args.candidate_dir}", file=sys.stderr)
        return 2

    try:
        out_dir = run_compare(
            args.baseline_dir,
            args.candidate_dir,
            output_root=args.output,
            monthly_volume=args.projection_volume,
        )
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Comparison written to: {out_dir}")
    print(f"  - {out_dir / 'COMPARE.md'}")
    print(f"  - {out_dir / 'per_case_delta.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
