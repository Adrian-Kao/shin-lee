"""Unit tests for the dependency-free metrics registry (Q19).

Covers:
  * Counter inc + Histogram observe accumulate correctly.
  * render_prometheus() output is well-formed: HELP/TYPE lines, cumulative
    histogram buckets, the +Inf bucket == _count, label escaping for nasty
    values (quote / backslash / newline).
  * Concurrent inc is lock-safe (no lost updates).
"""

from __future__ import annotations

import threading

from backend.shared import metrics


def _parse_lines(text: str):
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


def test_counter_inc_accumulates():
    c = metrics.Counter("test_counter_total", "help", labels=("a",))
    c.inc({"a": "x"})
    c.inc({"a": "x"}, value=4)
    c.inc({"a": "y"})
    assert c.get({"a": "x"}) == 5.0
    assert c.get({"a": "y"}) == 1.0
    assert c.get({"a": "z"}) == 0.0


def test_counter_rejects_negative():
    c = metrics.Counter("neg_total", "help")
    try:
        c.inc(value=-1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on negative inc")


def test_histogram_observe_accumulates_and_is_cumulative():
    h = metrics.Histogram("test_latency_seconds", "help", buckets=(0.1, 0.5, 1.0))
    for v in (0.05, 0.2, 0.2, 0.8, 5.0):
        h.observe(v)
    assert h.get_count() == 5.0
    assert abs(h.get_sum() - (0.05 + 0.2 + 0.2 + 0.8 + 5.0)) < 1e-9

    lines = h.render()
    text = "\n".join(lines)
    # Bucket counts must be cumulative and non-decreasing.
    # <=0.1 : {0.05} -> 1
    # <=0.5 : {0.05,0.2,0.2} -> 3
    # <=1.0 : {0.05,0.2,0.2,0.8} -> 4
    # +Inf  : all 5
    assert 'test_latency_seconds_bucket{le="0.1"} 1' in text
    assert 'test_latency_seconds_bucket{le="0.5"} 3' in text
    assert 'test_latency_seconds_bucket{le="1"} 4' in text
    assert 'test_latency_seconds_bucket{le="+Inf"} 5' in text
    assert "test_latency_seconds_count 5" in text


def test_render_has_help_and_type_lines():
    text = metrics.render_prometheus()
    assert "# HELP http_request_duration_seconds" in text
    assert "# TYPE http_request_duration_seconds histogram" in text
    assert "# TYPE llm_errors_total counter" in text
    # Histogram emits the mandatory +Inf bucket even with no observations.
    assert 'audit_write_duration_seconds_bucket{le="+Inf"} 0' in text


def test_label_escaping():
    c = metrics.Counter("escape_total", "help", labels=("model",))
    # Value containing a backslash, a double-quote and a newline.
    nasty = 'a\\b"c\nd'
    c.inc({"model": nasty})
    line = "\n".join(c.render())
    # backslash -> \\ ; quote -> \" ; newline -> \n  (all inside model="...")
    assert 'model="a\\\\b\\"c\\nd"' in line, line
    # Sanity: a raw newline must NOT appear inside the rendered series line.
    series = [ln for ln in c.render() if ln.startswith("escape_total{")]
    assert len(series) == 1
    assert "\n" not in series[0].replace("\\n", "")


def test_integer_floats_render_without_decimal():
    c = metrics.Counter("int_total", "help")
    c.inc(value=3)
    assert "int_total 3" in "\n".join(c.render())


def test_concurrent_inc_is_lock_safe():
    c = metrics.Counter("concurrent_total", "help")
    threads = []
    per_thread = 1000
    n_threads = 8

    def worker():
        for _ in range(per_thread):
            c.inc()

    for _ in range(n_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert c.get() == float(per_thread * n_threads)


def test_module_helpers_inc_and_observe():
    metrics.REGISTRY.reset()
    metrics.inc("oa_analyzed_total", {"tenant": "tenant_a"})
    metrics.inc("oa_analyzed_total", {"tenant": "tenant_a"})
    assert metrics.OA_ANALYZED.get({"tenant": "tenant_a"}) == 2.0

    metrics.observe(
        "http_request_duration_seconds", 0.3, {"endpoint": "/x", "method": "POST", "status": "200"}
    )
    assert (
        metrics.HTTP_REQUEST_DURATION.get_count(
            {"endpoint": "/x", "method": "POST", "status": "200"}
        )
        == 1.0
    )


def test_helpers_noop_on_unknown_name():
    # Must not raise for an unregistered name, or for a type mismatch.
    metrics.inc("does_not_exist_total")
    metrics.observe("does_not_exist_seconds", 1.0)
    # Counter name fed to observe (type mismatch) is a no-op, not a crash.
    metrics.observe("llm_errors_total", 1.0)


def test_registry_reset_zeros_state():
    metrics.LLM_ERRORS.inc({"model": "m"})
    metrics.AUDIT_WRITE_DURATION.observe(0.01)
    metrics.REGISTRY.reset()
    assert metrics.LLM_ERRORS.get({"model": "m"}) == 0.0
    assert metrics.AUDIT_WRITE_DURATION.get_count() == 0.0


def test_full_render_parses_well_formed():
    metrics.REGISTRY.reset()
    text = metrics.render_prometheus()
    # Every non-comment line must have exactly: <name>[{labels}] <value>
    for ln in _parse_lines(text):
        # Split on the last space — value is the final token.
        head, _, value = ln.rpartition(" ")
        assert head, ln
        # value parses as a float or is +Inf/-Inf
        if value not in ("+Inf", "-Inf"):
            float(value)
    assert text.endswith("\n")


def test_cost_bridge_gauge_renders():
    # The bridge gauge must render even when rate_limit has no spend yet.
    text = metrics.render_prometheus()
    assert "# TYPE llm_cost_usd_month_to_date gauge" in text
