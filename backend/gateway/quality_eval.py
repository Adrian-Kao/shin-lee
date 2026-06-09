"""Q19 — offline AI-quality / attorney-acceptance evaluation pipeline.

docs/QUESTIONS.md Q19 ("AI 品質怎麼證明 / 怎麼持續監控") asks for a quality
dashboard with four lenses, and a "週/月律師抽樣評分" pipeline that turns the
raw audit log into a periodic report:

  * **業務 (business)** — OA processed, exports, and the headline metric:
    **attorney acceptance rate** = the proportion of AI-generated draft segments
    the attorney adopted *unchanged*. This is the number that proves the product
    actually saves attorney time rather than just generating text they rewrite.
  * **品質 (quality)** — citation accuracy / hallucination rate. In the POC the
    grounded-citation verifier (Q14) is the hard wall, so a *clean* run is the
    base case; this module surfaces the proxy it can compute from the audit row
    (sign-off refusal rate + attorney-edit rate as the inverse of acceptance).
  * **系統 (system)** — latency p50/p95/p99 per endpoint, plus an audit-write
    health proxy.
  * **成本 (cost)** — total + per-model + per-tenant $ from the token columns,
    and the per-OA average cost.

Where the numbers come from
---------------------------
Every gateway request already writes exactly one audit row (Q13 invariant #4),
and that row carries the raw material:

  * ``endpoint``                  — which handler ran (``/v1/oa/analyze`` etc.)
  * ``model_used``                — routed model (Q15) or ``"cache"`` / ``None``
  * ``prompt_tokens`` / ``completion_tokens`` — for cost (Q18 ``estimate_cost``)
  * ``latency_ms``                — for the percentile lenses
  * ``policy_decisions`` (JSON)   — booleans + the export provenance COUNTS:
        ``prov_total_segments``, ``prov_accepted_segments``,
        ``prov_ai_generated``,   ``prov_attorney_edited``,
        ``prov_attorney_added``, ``attorney_signoff``, ``signoff_passed``,
        ``error``, ``cache_hit`` …
    (read straight off ``/v1/oa/export``'s real handler in main.py — see the
    ``pd[...] = summary....`` block.)

This module is **read-only over the audit DB**, exactly like ``audit_archive.py``
and ``backup.py``: it opens the live DB with the ``file:...?mode=ro`` URI idiom
and never writes. It does NOT add an HTTP endpoint (kept off ``main.py``); it is
a thin library an ops cron calls weekly/monthly, with a CLI mirroring
``audit_archive.py`` / ``deadline.py`` / ``backup.py``.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Endpoint constants — the exact strings the gateway writes (main.py).
EP_ANALYZE = "/v1/oa/analyze"
EP_EXPORT = "/v1/oa/export"


# ---------------------------------------------------------------------------
# Lazy config resolution (honours conftest / test monkeypatching, exactly like
# audit_archive.py + backup.py — config constants are mutated per session).
# ---------------------------------------------------------------------------
def _audit_db_path() -> Path:
    from backend.shared import config

    return Path(config.AUDIT_DB_PATH)


# ---------------------------------------------------------------------------
# Read-only audit access.
# ---------------------------------------------------------------------------
# Columns the analyzer needs. Pulled in rowid (insertion) order so an
# "audit-write monotonicity" health check can confirm timestamps never go
# backwards relative to insertion.
_SELECT = (
    "SELECT audit_id, timestamp_utc, tenant_id, endpoint, model_used, "
    "       prompt_tokens, completion_tokens, latency_ms, policy_decisions "
    "FROM audit ORDER BY rowid ASC"
)


def _read_rows() -> list[dict[str, Any]]:
    """Read every audit row (rowid ASC) as plain dicts, read-only.

    Opens a fresh short-lived connection in URI read-only mode so this module
    can never mutate the audit log (defence in depth atop the append-only
    triggers). Returns ``[]`` when the DB file or the ``audit`` table does not
    exist yet (fresh / young checkout) — never raises for an empty DB.
    """
    path = _audit_db_path()
    if not path.exists():
        return []
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(_SELECT)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        # audit table not created yet (DB file exists but is empty).
        return []
    finally:
        conn.close()
    # Decode the policy_decisions JSON blob once, up front.
    for r in rows:
        raw = r.get("policy_decisions")
        try:
            r["policy_decisions"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            r["policy_decisions"] = {}
    return rows


# ---------------------------------------------------------------------------
# Time window filtering.
# ---------------------------------------------------------------------------
def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO ``timestamp_utc`` to an aware datetime, or None on failure."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _in_window(
    rows: list[dict[str, Any]],
    *,
    days: Optional[int],
    tenant: Optional[str],
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Filter rows to the last ``days`` (None = all time) and optional tenant."""
    cutoff: Optional[datetime] = None
    if days is not None:
        ref = now or datetime.now(timezone.utc)
        cutoff = ref - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for r in rows:
        if tenant is not None and r.get("tenant_id") != tenant:
            continue
        if cutoff is not None:
            dt = _parse_ts(r.get("timestamp_utc"))
            # A row with an unparseable timestamp is conservatively dropped from
            # a windowed report (it can't be placed in time) but kept when
            # days is None (whole-history view).
            if dt is None or dt < cutoff:
                continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Percentiles.
# ---------------------------------------------------------------------------
def _percentile(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank percentile over an already-sorted list.

    ``q`` in [0,1]. Uses the nearest-rank method: rank = ceil(q * N), clamped to
    [1, N], 1-indexed — i.e. p50 of 4 sorted values is the 2nd, p95/p99 of a
    small sample is the max. Chosen over linear interpolation because it always
    returns an *observed* latency (an SLO is about real requests, not an
    interpolated fiction) and is unambiguous to hand-verify in tests.
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    import math

    rank = math.ceil(q * n)
    if rank < 1:
        rank = 1
    if rank > n:
        rank = n
    return float(sorted_vals[rank - 1])


def _latency_stats(latencies: list[int]) -> dict[str, Any]:
    """p50/p95/p99 + count/min/max/mean over a list of latency_ms ints."""
    vals = sorted(float(x) for x in latencies if x is not None)
    if not vals:
        return {
            "count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
            "min_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0,
        }
    return {
        "count": len(vals),
        "p50_ms": _percentile(vals, 0.50),
        "p95_ms": _percentile(vals, 0.95),
        "p99_ms": _percentile(vals, 0.99),
        "min_ms": vals[0],
        "max_ms": vals[-1],
        "mean_ms": round(sum(vals) / len(vals), 3),
    }


# ---------------------------------------------------------------------------
# Cost.
# ---------------------------------------------------------------------------
def _estimate_cost(model: Optional[str], prompt: int, completion: int) -> float:
    """Per-row $ via rate_limit.estimate_cost (imported read-only).

    Cache hits (``model_used == "cache"``) and audit rows with no model
    (``None`` — e.g. an export, or an errored request that never reached the
    LLM) cost $0: there was no inference. Everything else is priced through the
    shared estimator so this report and the live billing path agree.
    """
    if not model or model == "cache":
        return 0.0
    from backend.gateway.rate_limit import estimate_cost

    return estimate_cost(
        model, {"prompt_tokens": prompt or 0, "completion_tokens": completion or 0}
    )


# ---------------------------------------------------------------------------
# The report.
# ---------------------------------------------------------------------------
def _zero_report(
    *, days: Optional[int], tenant: Optional[str], generated_at: str
) -> dict[str, Any]:
    """Structurally-complete report over zero rows (never divide-by-zero)."""
    empty_lat = _latency_stats([])
    return {
        "generated_at": generated_at,
        "window_days": days,
        "tenant_filter": tenant,
        "rows_in_window": 0,
        "business": {
            "oa_analyzed": 0,
            "oa_analyze_errors": 0,
            "cache_hits": 0,
            "exports_total": 0,
            "exports_signed_off": 0,
            "exports_refused": 0,
            "signoff_refusal_rate": 0.0,
            "acceptance_rate": 0.0,
            "acceptance_rate_by_tenant": {},
            "provenance_totals": {
                "total_segments": 0,
                "accepted_segments": 0,
                "ai_generated": 0,
                "attorney_edited": 0,
                "attorney_added": 0,
            },
        },
        "quality": {
            "attorney_edit_rate": 0.0,
            "attorney_added_rate": 0.0,
            "signoff_refusal_rate": 0.0,
        },
        "system": {
            "latency_overall": empty_lat,
            "latency_by_endpoint": {},
            "audit_write_health": {
                "rows": 0,
                "timestamp_monotonic": True,
                "out_of_order_rows": 0,
            },
        },
        "cost": {
            "total_usd": 0.0,
            "per_oa_usd": 0.0,
            "by_model": {},
            "by_tenant": {},
        },
        "model_mix": {},
    }


def _acceptance(prov: dict[str, int]) -> float:
    total = prov.get("total_segments", 0)
    if total <= 0:
        return 0.0
    # Headline acceptance = AI-generated segments the attorney ADOPTED
    # UNCHANGED ÷ all segments. ``accepted_segments`` already counts segments
    # whose final state is "accepted as-is"; ``ai_generated`` is the count of
    # those that were AI-authored (vs attorney_edited / attorney_added). The
    # adopted-AI-unchanged count is therefore ``ai_generated`` (an AI segment
    # that was edited is reclassified as attorney_edited, and one the attorney
    # wrote is attorney_added). We divide that by the total segment count.
    return round(prov.get("ai_generated", 0) / total, 6)


def build_report(
    *,
    days: Optional[int] = None,
    tenant: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compute the weekly/monthly quality report.

    Parameters
    ----------
    days :
        Restrict to audit rows from the last ``days`` days. ``None`` = all
        history.
    tenant :
        Restrict to a single ``tenant_id``. ``None`` = all tenants.
    now :
        Reference "now" for the window cutoff (injectable for deterministic
        tests). Defaults to ``datetime.now(timezone.utc)``.

    Returns a structured report dict. Robust to an empty/young audit DB: every
    rate is guarded against division by zero and a no-rows report returns zeros.
    """
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    rows = _in_window(_read_rows(), days=days, tenant=tenant, now=now)

    if not rows:
        return _zero_report(days=days, tenant=tenant, generated_at=generated_at)

    # --- 業務 / 品質 counters -------------------------------------------------
    oa_analyzed = 0          # successful analyze (not error, not cache hit)
    oa_analyze_errors = 0
    cache_hits = 0
    exports_total = 0
    exports_signed_off = 0
    exports_refused = 0      # sign-off hard-gate refusals (signoff=False)

    # Provenance accumulators, overall + per tenant.
    prov_overall = {
        "total_segments": 0, "accepted_segments": 0, "ai_generated": 0,
        "attorney_edited": 0, "attorney_added": 0,
    }
    prov_by_tenant: dict[str, dict[str, int]] = {}

    # --- 系統 latency buckets -------------------------------------------------
    latency_overall: list[int] = []
    latency_by_endpoint: dict[str, list[int]] = {}

    # --- 成本 accumulators ----------------------------------------------------
    total_cost = 0.0
    cost_by_model: dict[str, float] = {}
    cost_by_tenant: dict[str, float] = {}
    model_mix: dict[str, int] = {}

    # --- audit-write health (timestamp monotonicity vs insertion order) ------
    last_dt: Optional[datetime] = None
    out_of_order = 0

    for r in rows:
        ep = r.get("endpoint") or "(unknown)"
        pd = r.get("policy_decisions") or {}
        tid = r.get("tenant_id") or "(unknown)"
        model = r.get("model_used")
        ptok = int(r.get("prompt_tokens") or 0)
        ctok = int(r.get("completion_tokens") or 0)
        lat = r.get("latency_ms")

        # latency (every endpoint contributes to overall + its own bucket).
        if lat is not None:
            latency_overall.append(int(lat))
            latency_by_endpoint.setdefault(ep, []).append(int(lat))

        # audit-write health: timestamps should be non-decreasing in rowid order.
        dt = _parse_ts(r.get("timestamp_utc"))
        if dt is not None:
            if last_dt is not None and dt < last_dt:
                out_of_order += 1
            last_dt = dt

        # cost + model mix (only rows that actually invoked a priced model).
        is_error = bool(pd.get("error"))
        if model and model != "cache":
            model_mix[model] = model_mix.get(model, 0) + 1
            row_cost = _estimate_cost(model, ptok, ctok)
            total_cost += row_cost
            cost_by_model[model] = cost_by_model.get(model, 0.0) + row_cost
            cost_by_tenant[tid] = cost_by_tenant.get(tid, 0.0) + row_cost

        # endpoint-specific business counters.
        if ep == EP_ANALYZE:
            if is_error:
                oa_analyze_errors += 1
            elif pd.get("cache_hit"):
                cache_hits += 1
            else:
                oa_analyzed += 1
        elif ep == EP_EXPORT:
            exports_total += 1
            signed = bool(pd.get("attorney_signoff"))
            if signed:
                exports_signed_off += 1
            # A refusal is specifically the sign-off hard gate firing
            # (signoff_passed False AND an error on this export). ACL-403 /
            # 400-mismatch are export *attempts* but not sign-off refusals, so
            # they are NOT counted here (mirrors main.py's signoff_refused_total
            # which only increments on the 409 path).
            if (not signed) and is_error and not pd.get("signoff_passed", False):
                exports_refused += 1

            # Provenance counts are present whenever the handler computed the
            # summary (success AND the 409 refusal path); absent on the ACL-403
            # path that throws before summarising. Accumulate when present.
            if "prov_total_segments" in pd:
                contrib = {
                    "total_segments": int(pd.get("prov_total_segments") or 0),
                    "accepted_segments": int(pd.get("prov_accepted_segments") or 0),
                    "ai_generated": int(pd.get("prov_ai_generated") or 0),
                    "attorney_edited": int(pd.get("prov_attorney_edited") or 0),
                    "attorney_added": int(pd.get("prov_attorney_added") or 0),
                }
                for k, v in contrib.items():
                    prov_overall[k] += v
                pt = prov_by_tenant.setdefault(
                    tid,
                    {"total_segments": 0, "accepted_segments": 0, "ai_generated": 0,
                     "attorney_edited": 0, "attorney_added": 0},
                )
                for k, v in contrib.items():
                    pt[k] += v

    # --- derive rates (all division-by-zero guarded) -------------------------
    acceptance_rate = _acceptance(prov_overall)
    acceptance_by_tenant = {t: _acceptance(p) for t, p in prov_by_tenant.items()}

    signoff_refusal_rate = (
        round(exports_refused / exports_total, 6) if exports_total else 0.0
    )

    total_seg = prov_overall["total_segments"]
    attorney_edit_rate = (
        round(prov_overall["attorney_edited"] / total_seg, 6) if total_seg else 0.0
    )
    attorney_added_rate = (
        round(prov_overall["attorney_added"] / total_seg, 6) if total_seg else 0.0
    )

    # per-OA cost = total inference $ / number of OAs analyzed (the unit of
    # business value). Cache hits are excluded from the denominator (no
    # inference happened) but their $0 is already excluded from the numerator.
    per_oa_usd = round(total_cost / oa_analyzed, 6) if oa_analyzed else 0.0

    return {
        "generated_at": generated_at,
        "window_days": days,
        "tenant_filter": tenant,
        "rows_in_window": len(rows),
        "business": {
            "oa_analyzed": oa_analyzed,
            "oa_analyze_errors": oa_analyze_errors,
            "cache_hits": cache_hits,
            "exports_total": exports_total,
            "exports_signed_off": exports_signed_off,
            "exports_refused": exports_refused,
            "signoff_refusal_rate": signoff_refusal_rate,
            "acceptance_rate": acceptance_rate,
            "acceptance_rate_by_tenant": acceptance_by_tenant,
            "provenance_totals": prov_overall,
        },
        "quality": {
            "attorney_edit_rate": attorney_edit_rate,
            "attorney_added_rate": attorney_added_rate,
            "signoff_refusal_rate": signoff_refusal_rate,
        },
        "system": {
            "latency_overall": _latency_stats(latency_overall),
            "latency_by_endpoint": {
                ep: _latency_stats(v) for ep, v in sorted(latency_by_endpoint.items())
            },
            "audit_write_health": {
                "rows": len(rows),
                "timestamp_monotonic": out_of_order == 0,
                "out_of_order_rows": out_of_order,
            },
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "per_oa_usd": per_oa_usd,
            "by_model": {m: round(c, 6) for m, c in sorted(cost_by_model.items())},
            "by_tenant": {t: round(c, 6) for t, c in sorted(cost_by_tenant.items())},
        },
        "model_mix": dict(sorted(model_mix.items())),
    }


# ---------------------------------------------------------------------------
# Human-readable renderer.
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_report(report: dict[str, Any]) -> str:
    """Render the report dict as a plain-text weekly/monthly summary."""
    b = report["business"]
    q = report["quality"]
    s = report["system"]
    c = report["cost"]
    lat = s["latency_overall"]

    window = (
        f"last {report['window_days']} days"
        if report.get("window_days") is not None
        else "all history"
    )
    tenant = report.get("tenant_filter") or "ALL tenants"

    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("PatentMind — AI 品質 / 律師採用率 報告 (Q19)")
    lines.append(f"  generated_at : {report['generated_at']}")
    lines.append(f"  window       : {window}")
    lines.append(f"  tenant       : {tenant}")
    lines.append(f"  audit rows   : {report['rows_in_window']}")
    lines.append("=" * 64)

    lines.append("")
    lines.append("業務 BUSINESS")
    lines.append(f"  OA analyzed (ok)        : {b['oa_analyzed']}")
    lines.append(f"  OA analyze errors       : {b['oa_analyze_errors']}")
    lines.append(f"  cache hits              : {b['cache_hits']}")
    lines.append(f"  exports total           : {b['exports_total']}")
    lines.append(f"    signed off            : {b['exports_signed_off']}")
    lines.append(f"    refused (sign-off gate): {b['exports_refused']}")
    lines.append(f"  sign-off refusal rate   : {_pct(b['signoff_refusal_rate'])}")
    lines.append(
        f"  *** ATTORNEY ACCEPTANCE  : {_pct(b['acceptance_rate'])}  "
        f"(AI segments adopted unchanged) ***"
    )
    if b["acceptance_rate_by_tenant"]:
        lines.append("  acceptance by tenant    :")
        for t, rate in b["acceptance_rate_by_tenant"].items():
            lines.append(f"      {t:<16}    : {_pct(rate)}")
    pt = b["provenance_totals"]
    lines.append(
        f"  segments: total={pt['total_segments']} "
        f"ai={pt['ai_generated']} edited={pt['attorney_edited']} "
        f"added={pt['attorney_added']} accepted={pt['accepted_segments']}"
    )

    lines.append("")
    lines.append("品質 QUALITY")
    lines.append(f"  attorney edit rate      : {_pct(q['attorney_edit_rate'])}")
    lines.append(f"  attorney added rate     : {_pct(q['attorney_added_rate'])}")
    lines.append(f"  sign-off refusal rate   : {_pct(q['signoff_refusal_rate'])}")

    lines.append("")
    lines.append("系統 SYSTEM (latency ms)")
    lines.append(
        f"  overall  n={lat['count']:<5} "
        f"p50={lat['p50_ms']:.0f} p95={lat['p95_ms']:.0f} p99={lat['p99_ms']:.0f} "
        f"max={lat['max_ms']:.0f}"
    )
    for ep, el in s["latency_by_endpoint"].items():
        lines.append(
            f"    {ep:<18} n={el['count']:<5} "
            f"p50={el['p50_ms']:.0f} p95={el['p95_ms']:.0f} p99={el['p99_ms']:.0f}"
        )
    awh = s["audit_write_health"]
    lines.append(
        f"  audit-write health      : rows={awh['rows']} "
        f"monotonic={awh['timestamp_monotonic']} "
        f"out_of_order={awh['out_of_order_rows']}"
    )

    lines.append("")
    lines.append("成本 COST (USD)")
    lines.append(f"  total                   : ${c['total_usd']:.4f}")
    lines.append(f"  per-OA average          : ${c['per_oa_usd']:.4f}")
    if c["by_model"]:
        lines.append("  by model                :")
        for m, cost in c["by_model"].items():
            lines.append(f"      {m:<28} : ${cost:.4f}")
    if c["by_tenant"]:
        lines.append("  by tenant               :")
        for t, cost in c["by_tenant"].items():
            lines.append(f"      {t:<28} : ${cost:.4f}")

    lines.append("")
    lines.append("MODEL MIX")
    if report["model_mix"]:
        for m, n in report["model_mix"].items():
            lines.append(f"  {m:<30} : {n}")
    else:
        lines.append("  (no priced inference rows)")

    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (mirrors audit_archive.py / backup.py / deadline.py).
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    # Windows console is often cp950/cp1252; force utf-8 so 中文 + the report
    # box-drawing print cleanly (mirrors backup.py / deadline.py CLI style).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    days: Optional[int] = None
    tenant: Optional[str] = None
    as_json = False

    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--days":
            i += 1
            if i >= len(argv):
                print("--days requires an integer argument", file=sys.stderr)
                return 2
            try:
                days = int(argv[i])
            except ValueError:
                print(f"--days expects an integer, got {argv[i]!r}", file=sys.stderr)
                return 2
        elif arg.startswith("--days="):
            try:
                days = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"--days expects an integer, got {arg!r}", file=sys.stderr)
                return 2
        elif arg == "--tenant":
            i += 1
            if i >= len(argv):
                print("--tenant requires a tenant_id argument", file=sys.stderr)
                return 2
            tenant = argv[i]
        elif arg.startswith("--tenant="):
            tenant = arg.split("=", 1)[1]
        elif arg == "--json":
            as_json = True
        elif arg in ("-h", "--help"):
            print(
                "usage: python -m backend.gateway.quality_eval "
                "[--days N] [--tenant T] [--json]",
                file=sys.stderr,
            )
            return 0
        else:
            print(f"unknown argument {arg!r}", file=sys.stderr)
            return 2
        i += 1

    report = build_report(days=days, tenant=tenant)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
