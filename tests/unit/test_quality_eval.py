"""Unit tests for the Q19 offline quality-eval pipeline
(backend/gateway/quality_eval.py).

The audit DB path is monkeypatched onto a fresh tmp file (mirroring
test_backup.py / test_audit_archive.py) and rows are seeded via a private
``AuditWriter`` bound to that tmp DB — never the global ``audit.writer``
singleton. Every asserted metric is hand-computed in the test so the math is
provably correct, not merely self-consistent.

The seeded fixture mirrors the REAL handler shapes from main.py:
  * ``/v1/oa/analyze`` success → model_used set, cache_hit False, no error.
  * ``/v1/oa/analyze`` cache hit → model_used "cache", cache_hit True.
  * ``/v1/oa/analyze`` error → error True, model_used None.
  * ``/v1/oa/export`` success → attorney_signoff True + prov_* counts.
  * ``/v1/oa/export`` refused → attorney_signoff False, signoff_passed False,
    error True (the 409 hard gate), prov_* still present.
"""
from __future__ import annotations

import pytest

from backend.gateway import audit, quality_eval
from backend.gateway.rate_limit import estimate_cost
from backend.shared import config
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_audit(tmp_path, monkeypatch):
    """Point AUDIT_DB_PATH at a fresh tmp DB + return a bound AuditWriter."""
    audit_db = tmp_path / "audit.db"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", audit_db)
    writer = audit.AuditWriter(path=audit_db)
    return writer


def _user(user_id: str = "alice", tenant_id: str = "tenant_a") -> User:
    return User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name=user_id,
    )


def _analyze(
    writer, *, tenant, model, ptok, ctok, latency, error=False, cache=False
):
    pd = {"authz_passed": True, "cache_hit": cache}
    if error:
        pd["error"] = True
    writer.write(
        user=_user(tenant_id=tenant),
        case_id="case-x",
        endpoint="/v1/oa/analyze",
        request_payload={"q": 1},
        response_payload={"a": 1},
        masked_rules=["email"],
        model_used=model,
        prompt_tokens=ptok,
        completion_tokens=ctok,
        latency_ms=latency,
        policy_decisions=pd,
    )


def _export(
    writer, *, tenant, latency, signed, total, accepted, ai, edited, added
):
    pd = {
        "authn_passed": True,
        "authz_passed": True,
        "signoff_passed": signed,
        "attorney_signoff": signed,
        "prov_total_segments": total,
        "prov_accepted_segments": accepted,
        "prov_ai_generated": ai,
        "prov_attorney_edited": edited,
        "prov_attorney_added": added,
    }
    if not signed:
        # 409 hard-gate refusal path sets error True.
        pd["error"] = True
    writer.write(
        user=_user(tenant_id=tenant),
        case_id="case-x",
        endpoint="/v1/oa/export",
        request_payload={"segment_count": total},
        response_payload={"content_sha256": "deadbeef"},
        masked_rules=[],
        model_used=None,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=latency,
        policy_decisions=pd,
    )


# ---------------------------------------------------------------------------
# 1. Empty / young DB → zeros, never raises, never divides by zero.
# ---------------------------------------------------------------------------
def test_empty_db_returns_zeros(tmp_audit):
    rep = quality_eval.build_report()
    assert rep["rows_in_window"] == 0
    assert rep["business"]["acceptance_rate"] == 0.0
    assert rep["business"]["signoff_refusal_rate"] == 0.0
    assert rep["quality"]["attorney_edit_rate"] == 0.0
    assert rep["cost"]["total_usd"] == 0.0
    assert rep["cost"]["per_oa_usd"] == 0.0
    assert rep["system"]["latency_overall"]["p95_ms"] == 0.0
    assert rep["model_mix"] == {}
    # And it renders without raising.
    text = quality_eval.render_report(rep)
    assert "ATTORNEY ACCEPTANCE" in text


def test_missing_db_file_returns_zeros(tmp_path, monkeypatch):
    # Point at a path that does not exist at all (no AuditWriter created).
    monkeypatch.setattr(config, "AUDIT_DB_PATH", tmp_path / "nope.db")
    rep = quality_eval.build_report(days=7)
    assert rep["rows_in_window"] == 0
    assert rep["cost"]["total_usd"] == 0.0


# ---------------------------------------------------------------------------
# 2. Acceptance rate — hand-computed, per tenant and overall.
# ---------------------------------------------------------------------------
def test_acceptance_rate_and_provenance(tmp_audit):
    w = tmp_audit
    # tenant_a: two exports.
    #   export 1 (signed): total=10, ai=8, edited=1, added=1, accepted=9
    #   export 2 (signed): total=10, ai=2, edited=5, added=3, accepted=4
    _export(w, tenant="tenant_a", latency=5, signed=True,
            total=10, accepted=9, ai=8, edited=1, added=1)
    _export(w, tenant="tenant_a", latency=5, signed=True,
            total=10, accepted=4, ai=2, edited=5, added=3)
    # tenant_b: one fully-accepted AI export.
    #   total=5, ai=5, edited=0, added=0, accepted=5
    _export(w, tenant="tenant_b", latency=5, signed=True,
            total=5, accepted=5, ai=5, edited=0, added=0)

    rep = quality_eval.build_report()
    biz = rep["business"]

    # Overall: ai_generated = 8+2+5 = 15 ; total = 10+10+5 = 25 → 15/25 = 0.6
    assert biz["acceptance_rate"] == pytest.approx(0.6)
    # Per tenant: tenant_a ai=10 total=20 → 0.5 ; tenant_b ai=5 total=5 → 1.0
    assert biz["acceptance_rate_by_tenant"]["tenant_a"] == pytest.approx(0.5)
    assert biz["acceptance_rate_by_tenant"]["tenant_b"] == pytest.approx(1.0)

    prov = biz["provenance_totals"]
    assert prov["total_segments"] == 25
    assert prov["ai_generated"] == 15
    assert prov["attorney_edited"] == 6   # 1+5+0
    assert prov["attorney_added"] == 4    # 1+3+0
    assert prov["accepted_segments"] == 18  # 9+4+5

    # quality edit/added rates: 6/25 = 0.24 ; 4/25 = 0.16
    assert rep["quality"]["attorney_edit_rate"] == pytest.approx(0.24)
    assert rep["quality"]["attorney_added_rate"] == pytest.approx(0.16)


def test_tenant_filter_scopes_acceptance(tmp_audit):
    w = tmp_audit
    _export(w, tenant="tenant_a", latency=5, signed=True,
            total=10, accepted=9, ai=8, edited=1, added=1)
    _export(w, tenant="tenant_b", latency=5, signed=True,
            total=5, accepted=5, ai=5, edited=0, added=0)

    rep = quality_eval.build_report(tenant="tenant_b")
    # Only tenant_b in scope: 5/5 = 1.0
    assert rep["business"]["acceptance_rate"] == pytest.approx(1.0)
    assert rep["rows_in_window"] == 1
    assert set(rep["business"]["acceptance_rate_by_tenant"]) == {"tenant_b"}


# ---------------------------------------------------------------------------
# 3. Sign-off refusal rate.
# ---------------------------------------------------------------------------
def test_signoff_refusal_rate(tmp_audit):
    w = tmp_audit
    # 3 export attempts: 2 signed, 1 refused.
    _export(w, tenant="tenant_a", latency=5, signed=True,
            total=4, accepted=4, ai=4, edited=0, added=0)
    _export(w, tenant="tenant_a", latency=5, signed=True,
            total=4, accepted=4, ai=4, edited=0, added=0)
    _export(w, tenant="tenant_a", latency=5, signed=False,
            total=4, accepted=0, ai=4, edited=0, added=0)

    rep = quality_eval.build_report()
    biz = rep["business"]
    assert biz["exports_total"] == 3
    assert biz["exports_signed_off"] == 2
    assert biz["exports_refused"] == 1
    # 1 refused / 3 total = 0.333...
    assert biz["signoff_refusal_rate"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 4. Latency percentiles — fixed sample, unambiguous nearest-rank values.
# ---------------------------------------------------------------------------
def test_latency_percentiles(tmp_audit):
    w = tmp_audit
    # 10 analyze rows, latencies 10,20,...,100 (mock model so they're priced
    # but we don't assert cost here).
    for ms in range(10, 101, 10):
        _analyze(w, tenant="tenant_a", model="mock", ptok=0, ctok=0, latency=ms)

    rep = quality_eval.build_report()
    lat = rep["system"]["latency_overall"]
    # sorted = [10,20,...,100], N=10. nearest-rank:
    #   p50 = ceil(0.50*10)=5th  = 50
    #   p95 = ceil(0.95*10)=10th = 100
    #   p99 = ceil(0.99*10)=10th = 100
    assert lat["count"] == 10
    assert lat["p50_ms"] == 50.0
    assert lat["p95_ms"] == 100.0
    assert lat["p99_ms"] == 100.0
    assert lat["min_ms"] == 10.0
    assert lat["max_ms"] == 100.0
    assert lat["mean_ms"] == pytest.approx(55.0)

    # Per-endpoint bucket carries the same numbers.
    ep = rep["system"]["latency_by_endpoint"]["/v1/oa/analyze"]
    assert ep["p50_ms"] == 50.0 and ep["p95_ms"] == 100.0


# ---------------------------------------------------------------------------
# 5. Cost — per-model, per-tenant, per-OA, hand-computed against estimate_cost.
# ---------------------------------------------------------------------------
def test_cost_breakdown(tmp_audit):
    w = tmp_audit
    HAIKU = "claude-haiku-4-5-20251001"
    # tenant_a: 1 haiku analyze (1000 prompt / 2000 completion).
    _analyze(w, tenant="tenant_a", model=HAIKU, ptok=1000, ctok=2000, latency=30)
    # tenant_a: 1 mock analyze (1000 / 1000) — mock priced via fallback.
    _analyze(w, tenant="tenant_a", model="mock", ptok=1000, ctok=1000, latency=40)
    # tenant_b: 1 haiku analyze (500 / 500).
    _analyze(w, tenant="tenant_b", model=HAIKU, ptok=500, ctok=500, latency=20)
    # a cache hit + an error row: neither should contribute cost / model mix.
    _analyze(w, tenant="tenant_a", model="cache", ptok=0, ctok=0, latency=2, cache=True)
    _analyze(w, tenant="tenant_a", model=None, ptok=0, ctok=0, latency=3, error=True)

    rep = quality_eval.build_report()
    cost = rep["cost"]

    # Hand-compute via the shared estimator (single source of truth).
    haiku_a = estimate_cost(HAIKU, {"prompt_tokens": 1000, "completion_tokens": 2000})
    mock_a = estimate_cost("mock", {"prompt_tokens": 1000, "completion_tokens": 1000})
    haiku_b = estimate_cost(HAIKU, {"prompt_tokens": 500, "completion_tokens": 500})

    expected_total = haiku_a + mock_a + haiku_b
    assert cost["total_usd"] == pytest.approx(round(expected_total, 6))

    # by_model: haiku = haiku_a + haiku_b ; mock = mock_a
    assert cost["by_model"][HAIKU] == pytest.approx(round(haiku_a + haiku_b, 6))
    assert cost["by_model"]["mock"] == pytest.approx(round(mock_a, 6))

    # by_tenant: tenant_a = haiku_a + mock_a ; tenant_b = haiku_b
    assert cost["by_tenant"]["tenant_a"] == pytest.approx(round(haiku_a + mock_a, 6))
    assert cost["by_tenant"]["tenant_b"] == pytest.approx(round(haiku_b, 6))

    # business counters: 3 successful analyze, 1 cache hit, 1 error.
    biz = rep["business"]
    assert biz["oa_analyzed"] == 3
    assert biz["cache_hits"] == 1
    assert biz["oa_analyze_errors"] == 1

    # per-OA = total / oa_analyzed (3). Cache + error excluded from denominator.
    assert cost["per_oa_usd"] == pytest.approx(round(expected_total / 3, 6))

    # model mix: haiku ×2, mock ×1 ; cache / None excluded.
    assert rep["model_mix"] == {HAIKU: 2, "mock": 1}


# ---------------------------------------------------------------------------
# 6. Days window filters out old rows.
# ---------------------------------------------------------------------------
def test_days_window_filters_old_rows(tmp_audit):
    import datetime as _dt

    w = tmp_audit
    # Seed one row stamped "now".
    _analyze(w, tenant="tenant_a", model="mock", ptok=10, ctok=10, latency=5)

    # A wide window includes the recent row.
    rep_all = quality_eval.build_report(days=3650)
    assert rep_all["rows_in_window"] == 1

    # Push the reference "now" 500 days into the future with a 1-day window:
    # the cutoff (now-1d) is then ~499 days after the row, so the row is older
    # than the cutoff and is excluded — proving the window actually filters.
    future = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=500)
    rep_old = quality_eval.build_report(days=1, now=future)
    assert rep_old["rows_in_window"] == 0
