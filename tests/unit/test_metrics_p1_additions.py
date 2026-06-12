"""Q19 P1 additions — cache-hit counter, circuit-breaker + quota bridges, and
the Grafana dashboard JSONs under docs/observability/grafana/."""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.shared import metrics

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRAFANA_DIR = _REPO_ROOT / "docs" / "observability" / "grafana"
_DASHBOARDS = [
    _GRAFANA_DIR / "patentmind_system_overview.json",
    _GRAFANA_DIR / "patentmind_ai_quality_cost.json",
]


# ---------------------------------------------------------------------------
# cache_requests_total
# ---------------------------------------------------------------------------


def test_cache_requests_counter_registered_and_counts():
    metrics.CACHE_REQUESTS.inc({"result": "hit"})
    metrics.CACHE_REQUESTS.inc({"result": "miss"}, 2)
    assert metrics.CACHE_REQUESTS.get({"result": "hit"}) == 1.0
    assert metrics.CACHE_REQUESTS.get({"result": "miss"}) == 2.0
    text = metrics.render_prometheus()
    assert "# TYPE cache_requests_total counter" in text


# ---------------------------------------------------------------------------
# Q18 circuit-breaker bridge gauges
# ---------------------------------------------------------------------------


def test_circuit_breaker_gauges_render():
    text = metrics.render_prometheus()
    assert "# TYPE cost_circuit_breaker_tripped gauge" in text
    assert "# TYPE cost_circuit_breaker_daily_usd gauge" in text
    assert "# TYPE cost_circuit_breaker_threshold_usd gauge" in text


def test_circuit_breaker_tripped_tracks_rate_limit_state(monkeypatch):
    from backend.gateway import rate_limit
    from backend.shared.config import settings

    # Force a tripped breaker: spend above threshold for today.
    monkeypatch.setattr(settings, "COST_CIRCUIT_DAILY_USD", 0.5)
    monkeypatch.setitem(rate_limit._daily_cost_usd, rate_limit._today(), 1.0)

    text = metrics.render_prometheus()
    assert re.search(r"^cost_circuit_breaker_tripped 1$", text, re.M), text
    threshold = re.search(r"^cost_circuit_breaker_threshold_usd ([0-9.]+)$", text, re.M)
    assert threshold and float(threshold.group(1)) == 0.5


# ---------------------------------------------------------------------------
# Q18 tenant quota bridge gauges
# ---------------------------------------------------------------------------


def test_tenant_quota_bridge_renders_usage_and_cap(monkeypatch):
    from backend.gateway import rate_limit

    monkeypatch.setitem(
        rate_limit._tenant_monthly_tokens, ("tenant_a", rate_limit._this_month()), 12345
    )
    text = metrics.render_prometheus()
    assert "# TYPE tenant_monthly_tokens_used gauge" in text
    assert 'tenant_monthly_tokens_used{tenant="tenant_a"} 12345' in text
    # Cap gauge surfaces the configured tenants (DEMO_TENANTS).
    assert "# TYPE tenant_monthly_token_cap gauge" in text


def test_bridges_never_break_render(monkeypatch):
    # Even if rate_limit is unimportable/broken, /metrics must render.
    import backend.shared.metrics as m

    monkeypatch.setattr(m, "_circuit_state", lambda: (_ for _ in ()).throw(RuntimeError))
    text = m.render_prometheus()
    assert text.endswith("\n")


# ---------------------------------------------------------------------------
# Grafana dashboards — valid JSON, ${DS_PROMETHEUS}, real metric names
# ---------------------------------------------------------------------------


def _exposed_metric_names() -> set[str]:
    names = set()
    for metric in metrics.REGISTRY.all():
        names.add(metric.name)
        if getattr(metric, "kind", "") == "histogram":
            names.update({f"{metric.name}_bucket", f"{metric.name}_sum", f"{metric.name}_count"})
    return names


def test_dashboards_are_valid_json_with_ds_variable():
    for path in _DASHBOARDS:
        assert path.exists(), path
        dash = json.loads(path.read_text(encoding="utf-8"))
        # Import-ready: declares the DS_PROMETHEUS input.
        inputs = {i["name"] for i in dash.get("__inputs", [])}
        assert "DS_PROMETHEUS" in inputs, path.name
        assert dash.get("panels"), path.name
        for panel in dash["panels"]:
            ds = panel.get("datasource", {})
            assert ds.get("uid") == "${DS_PROMETHEUS}", (path.name, panel.get("title"))


def test_dashboard_exprs_reference_real_metrics():
    exposed = _exposed_metric_names()
    metric_token = re.compile(r"\b([a-z][a-z0-9_]{3,})(?:\{|\[| )")
    promql_keywords = {
        "sum", "rate", "increase", "histogram_quantile", "label_values",
        "max", "min", "avg", "count", "by", "on", "le", "endpoint",
        "tenant", "model", "kind", "result", "status", "method",
    }  # fmt: skip
    for path in _DASHBOARDS:
        dash = json.loads(path.read_text(encoding="utf-8"))
        for panel in dash["panels"]:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                for name in metric_token.findall(expr):
                    if name in promql_keywords or "__" in name:
                        continue
                    assert name in exposed, (path.name, panel.get("title"), name)
