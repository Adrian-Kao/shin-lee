"""Evaluation harness for the 30 synthetic demo cases.

CLI:
    python scripts/eval_cases.py [--mode mock|anthropic] [--case CASE-DEMO-NN]
                                 [--concurrency N] [--output DIR] [--confirm]

Defaults: --mode mock, all 30 cases, concurrency=4 (mock) / 2 (anthropic),
output=data/eval_results/<TIMESTAMP>/

This harness calls backend.gateway.orchestrator.orchestrate_analysis directly
(in-process), reroutes its outbound httpx.AsyncClient calls into the AI Engine
FastAPI app via httpx.ASGITransport, and seeds all 30 case patents into the
shared RAG store before running. No HTTP sockets, no FastAPI startup.

Outputs:
    <out>/CASE-DEMO-NN.json   — per-case predicted vs expected
    <out>/REPORT.md           — aggregate accuracy + per-rejection-type
                                breakdown + per-case table + worst cases

The harness is intentionally read-only against the backend codebase (no
imports modified, no monkey-patches that survive the run). All wiring lives
in this single file so a future cleanup can delete it cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import statistics
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("eval_cases")

# ---------------------------------------------------------------------------
# 1. Path + env setup — MUST come before any `backend.*` or `data.*` import.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _bootstrap_env(mode: str) -> None:
    """Set env vars before backend imports so config picks them up.

    Mock mode forces fully-in-memory backends; anthropic mode flips the LLM
    router but keeps every other backend in-memory so the harness stays
    hermetic for everything except the LLM call itself.

    The 4 backend-selector vars are FORCED (not setdefault) so a stale
    `VECTOR_BACKEND=qdrant` in a dev shell can't silently sabotage the run.
    JWT_SECRET / DB paths stay advisory (setdefault).
    """
    # FORCED vars — a stale value in the shell would break the eval harness.
    forced = {
        "LLM_MODE": "anthropic" if mode == "anthropic" else "mock",
        "VECTOR_BACKEND": "memory",
        "EMBEDDING_BACKEND": "mock",
        "CACHE_BACKEND": "memory",
    }
    for key, new_val in forced.items():
        old_val = os.environ.get(key)
        if old_val is not None and old_val != new_val:
            logger.warning("Eval harness forced %s=%s (was %r)", key, new_val, old_val)
        os.environ[key] = new_val

    # Config refuses to load in non-mock mode if JWT_SECRET is the default
    # placeholder; we don't issue JWTs (we call the orchestrator directly,
    # bypassing the FastAPI auth dependency) so any non-default value works.
    os.environ.setdefault("JWT_SECRET", "eval-harness-no-jwt-issued-here-32bytes-placeholder")
    # Use ephemeral SQLite paths so an eval run never touches the dev's
    # data/audit.db or data/redaction_mapping.db.
    #
    # NB: backend.shared.config exposes AUDIT_DB_PATH / MAPPING_DB_PATH as
    # module-level CONSTANTS (not env-driven), and backend.gateway.masking
    # binds the name at import time. So setting env vars is not enough — we
    # also mutate the constants on the config module right after the (very
    # small) import, before the gateway/ai_engine modules touch them. This
    # mirrors the trick tests/conftest.py uses for the same reason.
    _scratch = Path(tempfile.mkdtemp(prefix="patentmind-eval-"))
    os.environ.setdefault("AUDIT_DB_PATH", str(_scratch / "audit.db"))
    os.environ.setdefault("MAPPING_DB_PATH", str(_scratch / "mapping.db"))
    from backend.shared import config as _cfg
    _cfg.AUDIT_DB_PATH = Path(os.environ["AUDIT_DB_PATH"])
    _cfg.MAPPING_DB_PATH = Path(os.environ["MAPPING_DB_PATH"])


# ---------------------------------------------------------------------------
# 2. Comparison helpers (pure functions, no backend deps).
# ---------------------------------------------------------------------------
def _roc_to_iso_date(roc: tuple[int, int, int] | list[int]) -> str:
    """Convert (ROC_year, month, day) → 'YYYY-MM-DD'."""
    y, m, d = roc
    return f"{y + 1911:04d}-{m:02d}-{d:02d}"


def _add_months_naive(base_iso: str, months: int) -> str:
    """Add `months` to YYYY-MM-DD, clamping day to month length.

    Matches the spirit of TW's '兩個月內' counting in the synthetic OA fixtures.
    Used only as a sanity bound, not the source of truth — the orchestrator's
    deadline module uses a 60-day rule.
    """
    y, m, d = (int(x) for x in base_iso.split("-"))
    m_total = m + months - 1
    y += m_total // 12
    m = m_total % 12 + 1
    # day clamp (no calendar library needed for the months ∈ {1,2,3,6} we see)
    days_in_month = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    d = min(d, days_in_month)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _add_days_iso(base_iso: str, days: int) -> str:
    """Add `days` calendar days to YYYY-MM-DD via stdlib date arithmetic."""
    from datetime import date as _date, timedelta
    y, m, d = (int(x) for x in base_iso.split("-"))
    nd = _date(y, m, d) + timedelta(days=days)
    return nd.isoformat()


def compare_rejection_types(predicted: list[str], expected: list[str]) -> bool:
    return set(predicted) == set(expected)


def compare_affected_claims_per_rejection(
    predicted: list[dict], expected: list[dict]
) -> tuple[int, int]:
    """Per-rejection-type set comparison.

    Returns (matches, total). For each expected rejection, we look up
    predicted rejections with the same type; the union of their
    affected_claims must equal the expected set.
    """
    matches = 0
    total = len(expected)
    # group predicted by type
    pred_by_type: dict[str, set[int]] = {}
    for r in predicted:
        pred_by_type.setdefault(r["rejection_type"], set()).update(r["affected_claims"])
    for r in expected:
        t = r["rejection_type"]
        exp_set = set(r["affected_claims"])
        if pred_by_type.get(t) == exp_set:
            matches += 1
    return matches, total


# ---------------------------------------------------------------------------
# 3. The core eval runner — invoked once env + backend are wired up.
# ---------------------------------------------------------------------------
class EvalRunner:
    """Holds backend-module references so import is deferred to after env setup."""

    def __init__(self, mode: str):
        # Deferred imports — env vars must already be set.
        from backend.ai_engine import main as ai_main
        from backend.ai_engine import rag as rag_mod
        from backend.gateway import orchestrator as orch_mod
        from backend.shared.models import (
            AnalysisRequest,
            Patent,
            User,
            UserRole,
        )
        from data.cases import synthetic_cases as sc

        self.mode = mode
        self.ai_main = ai_main
        self.rag_mod = rag_mod
        self.orch_mod = orch_mod
        self.AnalysisRequest = AnalysisRequest
        self.Patent = Patent
        self.User = User
        self.UserRole = UserRole
        self.sc = sc

        # Cache the synthetic case dicts keyed by case_id for O(1) lookup.
        self.cases_by_id: dict[str, dict] = {c["case_id"]: c for c in sc.CASES}

        # Stand up an in-process "alice" attorney user. We bypass the FastAPI
        # auth dependency entirely; calling orchestrate_analysis directly does
        # not require a JWT (auth + ACL are enforced one layer up in main.py).
        self.user = User(
            user_id="alice",
            tenant_id="tenant_a",
            role=UserRole.ATTORNEY,
            display_name="Alice (eval harness)",
            daily_token_quota=10_000_000,
        )

        self._patch_httpx()

    def _patch_httpx(self) -> None:
        """Reroute orchestrator outbound httpx calls into in-process AI Engine.

        Mirrors tests/conftest.py::patched_ai_engine but applied globally for
        the eval run rather than per-fixture.
        """
        import httpx
        ai_app = self.ai_main.app
        original_async_client = httpx.AsyncClient

        def _patched(*args, **kwargs):
            kwargs["transport"] = httpx.ASGITransport(app=ai_app)
            kwargs.setdefault("base_url", "http://eval-ai-engine")
            kwargs.setdefault("timeout", 60.0)
            return original_async_client(*args, **kwargs)

        self.orch_mod.httpx.AsyncClient = _patched

    def seed_patents(self) -> int:
        """Index every case's patent into tenant_a so RAG returns real hits.

        Without this the orchestrator still works but every grounded_set is
        empty, which masks the verifier's behavior and zeroes out the
        retrieval-quality signal in the report.
        """
        from datetime import datetime as _dt
        n_total = 0
        for case in self.sc.CASES:
            p = case["patent"]
            pub_y, pub_m, pub_d = self.sc._roc_to_ce(p["publication_date_roc"])
            patent = self.Patent(
                patent_no=p["patent_no"],
                title=p["title"],
                abstract=p["abstract"],
                claims=p["claims"],
                publication_date=_dt(pub_y, pub_m, pub_d, tzinfo=timezone.utc),
                jurisdiction=p["jurisdiction"],
                is_local=False,
            )
            n_total += self.rag_mod.index_patent(
                self.user.tenant_id, patent, spec_text=p.get("spec_text", "")
            )
        return n_total

    async def run_one(self, case_id: str, semaphore: asyncio.Semaphore) -> dict:
        """Execute the orchestrator on a single case; return result dict.

        Captures wall-clock latency, exceptions (so one failure doesn't sink
        the batch), and every comparison field the report needs.
        """
        async with semaphore:
            return await self._run_one_unguarded(case_id)

    async def _run_one_unguarded(self, case_id: str) -> dict:
        case = self.cases_by_id[case_id]
        oa_path = _REPO_ROOT / "data" / "cases" / case_id / "oa.txt"
        if not oa_path.exists():
            return {
                "case_id": case_id,
                "status": "error",
                "error": f"missing oa.txt at {oa_path}",
            }
        oa_text = oa_path.read_text(encoding="utf-8")

        req = self.AnalysisRequest(
            oa_text=oa_text,
            case_id=case_id,
            target_patent_no=case["patent"]["patent_no"],
            user_hint=None,
        )

        started = time.monotonic()
        try:
            response, obs = await self.orch_mod.orchestrate_analysis(self.user, req)
        except Exception as e:
            return {
                "case_id": case_id,
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
                "latency_sec": time.monotonic() - started,
            }
        latency = time.monotonic() - started

        # ---- Extract predicted fields ----
        pred_rejections = [
            {
                "rejection_type": r.rejection_type.value,
                "affected_claims": sorted(r.affected_claims),
                "cited_prior_art": list(r.cited_prior_art),
                "confidence": float(r.confidence),
                "examiner_argument_preview": r.examiner_argument[:160],
            }
            for r in response.oa.rejections
        ]
        pred_types = sorted({r["rejection_type"] for r in pred_rejections})
        # Normalize to date-only (YYYY-MM-DD) so JSON diffs vs the date-only
        # expected value aren't muddied by a "T09:00:00+00:00" tail. The
        # startswith() comparison below still works either way.
        pred_received_iso = response.oa.received_date.isoformat()[:10]
        # statutory_deadline lives in deadline_summary, not on oa (oa.deadline is
        # the same value but the deadline_summary dict carries the warnings/etc).
        pred_statutory = response.deadline_summary.statutory_deadline.isoformat()

        # ---- Expected from the synthetic fixture ----
        exp_rejections = [
            {
                "rejection_type": r["rejection_type"],
                "affected_claims": sorted(r["affected_claims"]),
                "cited_prior_art": list(r["cited_prior_art"]),
                "statute": r["statute"],
            }
            for r in case["oa"]["rejections"]
        ]
        exp_types = sorted({r["rejection_type"] for r in exp_rejections})
        exp_received_iso = _roc_to_iso_date(case["oa"]["date_roc"])
        # Sanity bound: orchestrator uses 60-day TW rule; fixture uses
        # response_months (typically 2). We accept the statutory_deadline if
        # it equals received + 60 days OR received + response_months (with
        # weekend/holiday rollover slack of +/- 7 days).
        response_months = case["oa"].get("response_months", 2)
        target_a = _add_days_iso(exp_received_iso, 60)
        target_b = _add_months_naive(exp_received_iso, response_months)

        # ---- Comparisons ----
        rej_types_match = compare_rejection_types(pred_types, exp_types)
        claims_matches, claims_total = compare_affected_claims_per_rejection(
            pred_rejections, exp_rejections
        )
        received_match = pred_received_iso.startswith(exp_received_iso)
        deadline_within_range = (
            pred_statutory.startswith(target_a) or pred_statutory.startswith(target_b)
            or _within_days(pred_statutory[:10], target_a, 7)
            or _within_days(pred_statutory[:10], target_b, 7)
        )

        # ---- Drafts ----
        drafts_out = []
        for d in response.drafts:
            drafts_out.append({
                "rejection_id": d.rejection_id,
                "strategy_preview": d.strategy[:200],
                "draft_text_lines": d.draft_text.count("\n") + (1 if d.draft_text else 0),
                "draft_text_chars": len(d.draft_text),
                "grounded_citations": list(d.grounded_citations),
                "confidence": float(d.confidence),
            })

        # ---- Retrieval top-3 (across all rejections, sorted by score desc) ----
        top_hits = sorted(response.related_prior_art, key=lambda h: -h.score)[:3]
        retrieval_out = [
            {
                "patent_no": h.patent_no,
                "section": h.section,
                "score": float(h.score),
                "text_preview": h.text[:160],
            }
            for h in top_hits
        ]

        return {
            "case_id": case_id,
            "status": "ok",
            "latency_sec": latency,
            "model_used": obs.get("model_used"),
            "cost_meta": {
                "prompt_tokens": response.cost_meta.prompt_tokens,
                "completion_tokens": response.cost_meta.completion_tokens,
                "estimated_cost_usd": response.cost_meta.estimated_cost_usd,
                "model": response.cost_meta.model,
            },
            "predicted": {
                "rejections": pred_rejections,
                "rejection_types": pred_types,
                "received_date": pred_received_iso,
                "statutory_deadline": pred_statutory,
                "recommended_internal_deadline":
                    response.deadline_summary.recommended_internal_deadline.isoformat(),
                "days_remaining": response.deadline_summary.days_remaining,
                "deadline_warnings": list(response.deadline_summary.warnings),
            },
            "expected": {
                "rejections": exp_rejections,
                "rejection_types": exp_types,
                "received_date": exp_received_iso,
                "deadline_candidates": [target_a, target_b],
                "response_months": response_months,
            },
            "comparison": {
                "rejection_types_match": rej_types_match,
                "affected_claims_matches": claims_matches,
                "affected_claims_total": claims_total,
                "received_date_match": received_match,
                "deadline_within_range": deadline_within_range,
            },
            "drafts": drafts_out,
            "retrieval_top_hits": retrieval_out,
        }


def _within_days(iso_a: str, iso_b: str, days: int) -> bool:
    """Return True if |iso_a - iso_b| <= days. Both are 'YYYY-MM-DD'."""
    from datetime import date as _date
    try:
        a = _date(*(int(x) for x in iso_a.split("-")[:3]))
        b = _date(*(int(x) for x in iso_b.split("-")[:3]))
    except Exception:
        return False
    return abs((a - b).days) <= days


# ---------------------------------------------------------------------------
# 4. Aggregate report.
# ---------------------------------------------------------------------------
def _safe_div(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def build_report(
    results: list[dict],
    mode: str,
    concurrency: int,
    wall_time_sec: float,
    timestamp: str,
) -> str:
    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] != "ok"]

    total = len(results)
    # ---- Accuracy buckets ----
    rt_pass = sum(1 for r in ok if r["comparison"]["rejection_types_match"])
    rt_total = len(ok)
    ac_pass = sum(r["comparison"]["affected_claims_matches"] for r in ok)
    ac_total = sum(r["comparison"]["affected_claims_total"] for r in ok)
    rd_pass = sum(1 for r in ok if r["comparison"]["received_date_match"])
    dl_pass = sum(1 for r in ok if r["comparison"]["deadline_within_range"])

    # ---- Token totals ----
    total_prompt = sum(r["cost_meta"]["prompt_tokens"] for r in ok)
    total_completion = sum(r["cost_meta"]["completion_tokens"] for r in ok)
    total_cost = sum(r["cost_meta"]["estimated_cost_usd"] for r in ok)

    # ---- Per-rejection-type breakdown (computed against expected ground truth) ----
    type_stats: dict[str, dict] = {}
    for r in ok:
        # group expected types
        for er in r["expected"]["rejections"]:
            t = er["rejection_type"]
            st = type_stats.setdefault(t, {"count": 0, "pass": 0, "confs": []})
            st["count"] += 1
            # Per-rejection-type pass = predicted contained this type with matching claims
            pred_match = any(
                pr["rejection_type"] == t and set(pr["affected_claims"]) == set(er["affected_claims"])
                for pr in r["predicted"]["rejections"]
            )
            if pred_match:
                st["pass"] += 1
            # mean confidence over all predicted rejections of this type
            for pr in r["predicted"]["rejections"]:
                if pr["rejection_type"] == t:
                    st["confs"].append(pr["confidence"])

    # ---- Worst-performing cases ----
    def _badness(r: dict) -> tuple:
        # Higher = worse. Failed > misclassified > latency.
        if r["status"] != "ok":
            return (10, 0)
        c = r["comparison"]
        score = 0
        if not c["rejection_types_match"]:
            score += 4
        score += (c["affected_claims_total"] - c["affected_claims_matches"])
        if not c["received_date_match"]:
            score += 1
        if not c["deadline_within_range"]:
            score += 1
        return (score, r.get("latency_sec", 0))

    sorted_for_worst = sorted(results, key=_badness, reverse=True)
    # Only surface real failures. Tuple-compare `(0, 0.02) > (0, 0)` is True,
    # which previously made perfect-classification runs list 5 perfect cases
    # as "worst" purely on latency. Gate on the classification score (slot 0).
    worst = [r for r in sorted_for_worst if _badness(r)[0] > 0][:5]

    # ---- Render markdown ----
    L: list[str] = []
    L.append(f"# PatentMind eval — {timestamp}")
    L.append("")
    L.append(f"Mode: {mode}")
    L.append(f"Cases: {total} ({len(ok)} complete, {len(err)} failed to execute)")
    L.append(f"Concurrency: {concurrency}")
    L.append(f"Wall time: {wall_time_sec:.1f}s")
    L.append(
        f"Total tokens: input={total_prompt} output={total_completion}"
        f"{' (mock mode = 0 real tokens)' if mode == 'mock' else ''}"
    )
    L.append(f"Estimated cost: ${total_cost:.2f}{' (mock = $0 actual)' if mode == 'mock' else ''}")
    L.append("")

    L.append("## Classification accuracy")
    L.append("")
    L.append("|                          | Pass | Fail | Rate  |")
    L.append("|--------------------------|------|------|-------|")
    L.append(
        f"| rejection_type           | {rt_pass:>4} | {rt_total - rt_pass:>4} |"
        f" {_safe_div(rt_pass, rt_total) * 100:>4.1f}% |"
    )
    L.append(
        f"| affected_claims (per rej)| {ac_pass:>4} | {ac_total - ac_pass:>4} |"
        f" {_safe_div(ac_pass, ac_total) * 100:>4.1f}% |"
    )
    L.append(
        f"| received_date            | {rd_pass:>4} | {rt_total - rd_pass:>4} |"
        f" {_safe_div(rd_pass, rt_total) * 100:>4.1f}% |"
    )
    L.append(
        f"| deadline                 | {dl_pass:>4} | {rt_total - dl_pass:>4} |"
        f" {_safe_div(dl_pass, rt_total) * 100:>4.1f}% |"
    )
    L.append("")

    L.append("## Per-rejection-type breakdown")
    L.append("")
    L.append("| Type                | Count | Pass rate | Mean confidence |")
    L.append("|---------------------|-------|-----------|-----------------|")
    for t in sorted(type_stats.keys()):
        st = type_stats[t]
        rate = _safe_div(st["pass"], st["count"]) * 100
        mean_conf = statistics.fmean(st["confs"]) if st["confs"] else 0.0
        L.append(f"| {t:<19} | {st['count']:>5} | {rate:>7.1f}% | {mean_conf:>15.2f} |")
    L.append("")

    L.append("## Per-case detail")
    L.append("")
    L.append("| case_id       | rej_pred                  | rej_expected              | OK | deadline           | draft_lines | tokens | latency |")
    L.append("|---------------|---------------------------|---------------------------|----|--------------------|-------------|--------|---------|")
    for r in sorted(results, key=lambda x: x["case_id"]):
        if r["status"] != "ok":
            L.append(
                f"| {r['case_id']:<13} | -                         | -                         | x  | -                  | -           | -      |"
                f" ERROR: {r.get('error', '?')[:30]} |"
            )
            continue
        c = r["comparison"]
        ok_mark = "OK" if (
            c["rejection_types_match"]
            and c["received_date_match"]
            and c["deadline_within_range"]
        ) else "--"
        pred_str = ",".join(r["predicted"]["rejection_types"])[:25]
        exp_str = ",".join(r["expected"]["rejection_types"])[:25]
        dl = r["predicted"]["statutory_deadline"][:10]
        draft_lines = sum(d["draft_text_lines"] for d in r["drafts"])
        tok = r["cost_meta"]["prompt_tokens"] + r["cost_meta"]["completion_tokens"]
        L.append(
            f"| {r['case_id']:<13} | {pred_str:<25} | {exp_str:<25} | {ok_mark} |"
            f" {dl:<18} | {draft_lines:>11} | {tok:>6} | {r['latency_sec']:>6.2f}s |"
        )
    L.append("")

    if worst:
        L.append("## Worst-performing cases (top 5)")
        L.append("")
        for r in worst:
            L.append(f"### {r['case_id']}")
            if r["status"] != "ok":
                L.append(f"- Status: ERROR — {r.get('error', '?')}")
                L.append("")
                continue
            c = r["comparison"]
            pred = r["predicted"]["rejection_types"]
            exp = r["expected"]["rejection_types"]
            if not c["rejection_types_match"]:
                L.append(f"- Failure mode: predicted={pred}, expected={exp}")
            if c["affected_claims_matches"] < c["affected_claims_total"]:
                L.append(
                    f"- Claims mismatch: {c['affected_claims_matches']}/"
                    f"{c['affected_claims_total']} rejections had exact claim sets"
                )
            if not c["received_date_match"]:
                L.append(
                    f"- Received date: predicted={r['predicted']['received_date']},"
                    f" expected={r['expected']['received_date']}"
                )
            if not c["deadline_within_range"]:
                L.append(
                    f"- Deadline: predicted={r['predicted']['statutory_deadline']},"
                    f" expected candidates={r['expected']['deadline_candidates']}"
                )
            L.append(f"- Latency: {r['latency_sec']:.2f}s")
            L.append(f"- Tokens: {r['cost_meta']['prompt_tokens'] + r['cost_meta']['completion_tokens']}")
            L.append("")

    if err:
        L.append("## Execution errors")
        L.append("")
        for r in err:
            L.append(f"- {r['case_id']}: {r.get('error', '?')}")
        L.append("")

    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 5. CLI glue.
# ---------------------------------------------------------------------------
def _confirm_cost(estimated_usd: float, threshold: float, auto_confirm: bool) -> bool:
    if estimated_usd <= threshold:
        return True
    if auto_confirm:
        return True
    print(
        f"\nEstimated cost ${estimated_usd:.2f} exceeds confirmation threshold "
        f"${threshold:.2f}. Type 'y' to proceed: ",
        end="",
        flush=True,
    )
    line = sys.stdin.readline().strip().lower()
    return line == "y"


async def _amain(args: argparse.Namespace) -> int:
    # Fail-fast checks that don't require backend imports — do them BEFORE
    # the ~5s EvalRunner construction + seed_patents() so a missing key
    # exits in <1s instead of after a wasted seeding pass.
    if args.mode == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: --mode anthropic requires ANTHROPIC_API_KEY env var.",
            file=sys.stderr,
        )
        return 3

    runner = EvalRunner(args.mode)
    print(f"Seeding {len(runner.sc.CASES)} patents into RAG (tenant_a)...", flush=True)
    n_chunks = runner.seed_patents()
    print(f"  indexed {n_chunks} chunks.", flush=True)

    if args.case:
        case_ids = [args.case]
    else:
        case_ids = [c["case_id"] for c in runner.sc.CASES]
    case_ids = [cid for cid in case_ids if cid in runner.cases_by_id]
    if not case_ids:
        print(f"No matching cases for --case={args.case!r}.", file=sys.stderr)
        return 2

    # Anthropic mode: rough pre-estimate from input OA size so we can prompt.
    if args.mode == "anthropic":
        total_chars = 0
        for cid in case_ids:
            oa = _REPO_ROOT / "data" / "cases" / cid / "oa.txt"
            if oa.exists():
                total_chars += len(oa.read_text(encoding="utf-8"))
        # Very rough: input tokens ~ chars/3, ~4 LLM calls per case (parse +
        # draft + verify, summed over rejections), output ~25% of input,
        # Sonnet 4.5 ~$3/M input, $15/M output.
        est_input_tok = (total_chars // 3) * 4
        est_output_tok = est_input_tok // 4
        est_cost = (est_input_tok * 3 + est_output_tok * 15) / 1_000_000
        print(f"Anthropic mode: rough cost estimate ${est_cost:.2f} for {len(case_ids)} cases.")
        if not _confirm_cost(est_cost, threshold=5.0, auto_confirm=args.confirm):
            print("Aborted.", file=sys.stderr)
            return 4

    concurrency = args.concurrency or (2 if args.mode == "anthropic" else 4)
    sem = asyncio.Semaphore(concurrency)

    print(f"Running {len(case_ids)} cases with concurrency={concurrency}...", flush=True)
    wall_start = time.monotonic()
    tasks = [runner.run_one(cid, sem) for cid in case_ids]
    # return_exceptions=True so a BaseException (CancelledError, MemoryError,
    # KeyboardInterrupt) in one task doesn't tank the other in-flight
    # results. _run_one_unguarded already converts ordinary Exceptions into
    # error dicts; this handles the BaseException tier.
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[dict] = []
    for i, r in enumerate(raw_results):
        if isinstance(r, dict):
            results.append(r)
            continue
        cid = case_ids[i]  # parallel list — same order as `tasks`
        if isinstance(r, BaseException) and not isinstance(r, Exception):
            # BaseException leaked past _run_one_unguarded's try/except.
            results.append({
                "case_id": cid,
                "status": "error",
                "error": f"{type(r).__name__}: {r}",
            })
        elif isinstance(r, Exception):
            # Defensive: _run_one_unguarded should have caught this already.
            results.append({"case_id": cid, "status": "error", "error": str(r)})
        else:
            # Should never happen — gather returns either the result or an
            # exception. Surface it loudly.
            results.append({"case_id": cid, "status": "error", "error": f"unexpected result type: {type(r).__name__}"})
    wall_time = time.monotonic() - wall_start

    # ---- Write outputs ----
    # uuid suffix prevents two runs within the same second from clobbering
    # each other's output dir (e.g. parallel CI shards, rapid re-runs).
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_root = Path(args.output) if args.output else (_REPO_ROOT / "data" / "eval_results")
    out_dir = out_root / f"{timestamp}-{uuid.uuid4().hex[:6]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for r in results:
        path = out_dir / f"{r['case_id']}.json"
        # sort_keys=True so cross-run JSON diffs are stable.
        path.write_text(
            json.dumps(r, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    report = build_report(results, args.mode, concurrency, wall_time, timestamp)
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8")

    # ---- Console summary ----
    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] != "ok"]
    print()
    print(f"Done in {wall_time:.1f}s. {len(ok)}/{len(results)} cases ok, {len(err)} errors.")
    print(f"Output: {out_dir}")
    print(f"Report: {out_dir / 'REPORT.md'}")
    return 0 if not err else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the orchestrator against the 30 synthetic demo cases."
    )
    parser.add_argument("--mode", choices=("mock", "anthropic"), default="mock")
    parser.add_argument("--case", help="Run a single case (e.g. CASE-DEMO-001).")
    parser.add_argument("--concurrency", type=int, default=0,
                        help="Concurrent orchestrator calls. Default: 4 mock / 2 anthropic.")
    parser.add_argument("--output", help="Output directory root. Default: data/eval_results/.")
    parser.add_argument("--confirm", action="store_true",
                        help="Auto-confirm cost prompt in anthropic mode.")
    args = parser.parse_args(argv)

    # asyncio.Semaphore(N) raises a bare ValueError for negative N. Catch it
    # here with a friendly argparse error (exits 2, no traceback).
    if args.concurrency < 0:
        parser.error("--concurrency must be >= 0 (0 means auto-pick by mode)")

    _bootstrap_env(args.mode)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
