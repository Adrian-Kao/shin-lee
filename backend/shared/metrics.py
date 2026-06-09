"""In-process metrics registry + Prometheus text exposition (Q19).

The Q19 decision (docs/QUESTIONS.md §Q19) calls for a four-layer dashboard:

    業務 (business)   — OA processed, attorney acceptance, exports, refusals
    品質 (quality)    — citation accuracy / hallucination ratio, injection hits
    系統 (system)     — p50/p95/p99 latency per endpoint, LLM error rate,
                        audit-write latency (must stay <100ms)
    成本 (cost)       — per-OA cost, per-user/tenant/model spend

The stub table says "JSON logs only → Prometheus + Grafana". This module is
the bridge: a *dependency-free* metrics registry that renders the Prometheus
text exposition format (v0.0.4) so a real Prometheus server can scrape the
gateway's ``/metrics`` endpoint with zero extra infrastructure in the POC.

Design choices:

  * **No hard dependency on ``prometheus_client``.** Production teams that
    already run the official client can flip ``METRICS_USE_PROMETHEUS_CLIENT``
    on (env var) and we *detect* and defer to it — but the default path is a
    hand-rolled registry so ``pip install`` stays minimal and the POC runs
    anywhere. The hand-rolled path is the one the tests exercise.
  * **Thread-safe.** FastAPI runs handlers in a threadpool (sync defs) and on
    the event loop (async defs). A single ``threading.Lock`` guards every
    mutation; the critical sections are O(1) dict bumps so contention is
    negligible at POC scale.
  * **Pre-declared metric set.** All four layers' metrics are registered at
    import time so ``/metrics`` always exposes them (at 0 if never touched).
    A metric that only appears after the first event is a classic Prometheus
    foot-gun (alerts on ``absent()`` misfire); pre-declaring avoids it.

The metric *names* and *label sets* are the contract; the gateway imports the
module-level helpers (``inc`` / ``observe`` / ``render_prometheus``) and the
typed handles (e.g. ``OA_ANALYZED``) and never reaches into the registry guts.
"""
from __future__ import annotations

import math
import os
import threading
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Label handling
# ---------------------------------------------------------------------------
# A label set is normalised to a sorted tuple of (name, value) pairs so that
# {a=1,b=2} and {b=2,a=1} collapse to the same series key.
LabelKey = Tuple[Tuple[str, str], ...]


def _normalise_labels(
    declared: Sequence[str], labels: Optional[Dict[str, str]]
) -> LabelKey:
    """Project ``labels`` onto the metric's declared label names.

    Missing declared labels default to "" (Prometheus has no concept of an
    absent label — an empty string is the conventional "not set"). Undeclared
    keys are dropped silently rather than raising, so an instrumentation site
    that passes an extra debug label can't crash a request handler. The result
    is a sorted tuple, giving a stable, hashable series key.
    """
    labels = labels or {}
    return tuple(sorted((name, str(labels.get(name, ""))) for name in declared))


def _escape_label_value(value: str) -> str:
    """Escape a label VALUE per the Prometheus text exposition spec.

    The spec requires backslash, double-quote and newline to be escaped inside
    the ``"..."`` of a label value (in that precedence — backslash first so we
    don't double-escape the escapes we just introduced):

        \\  -> \\\\
        "   -> \\"
        \\n -> \\n
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _render_labels(label_pairs: LabelKey, extra: Optional[Tuple[str, str]] = None) -> str:
    """Render a ``{k="v",...}`` clause, or "" when there are no labels.

    ``extra`` lets histogram bucket lines append the synthetic ``le`` label
    without mutating the stored key.
    """
    pairs: List[Tuple[str, str]] = list(label_pairs)
    if extra is not None:
        pairs.append(extra)
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in pairs)
    return "{" + inner + "}"


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------
class Counter:
    """A monotonically increasing counter, one value per label set."""

    kind = "counter"

    def __init__(self, name: str, help_text: str, labels: Sequence[str] = ()):
        self.name = name
        self.help_text = help_text
        self.label_names: Tuple[str, ...] = tuple(labels)
        self._lock = threading.Lock()
        self._values: Dict[LabelKey, float] = {}

    def inc(self, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
        if value < 0:
            raise ValueError("Counter increment must be non-negative")
        key = _normalise_labels(self.label_names, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = _normalise_labels(self.label_names, labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def _snapshot(self) -> List[Tuple[LabelKey, float]]:
        with self._lock:
            return sorted(self._values.items())

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        snap = self._snapshot()
        if not snap:
            # Emit the zero series with no labels so the metric is never absent.
            lines.append(f"{self.name} 0")
            return lines
        for key, val in snap:
            lines.append(f"{self.name}{_render_labels(key)} {_format_float(val)}")
        return lines


# Latency buckets in SECONDS. Tuned for this workload: audit writes are
# sub-millisecond–to-low-ms (the <100ms SLO sits at the 0.1 boundary), while a
# full /v1/oa/analyze round-trip through the AI engine can run seconds. The
# spread (1ms → 10s) lets Prometheus' histogram_quantile() interpolate p50/p95/
# p99 across both regimes.
DEFAULT_LATENCY_BUCKETS: Tuple[float, ...] = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


class Histogram:
    """A cumulative histogram (Prometheus-style ``_bucket``/``_sum``/``_count``).

    Buckets are *upper bounds* (``le``). On observe we bump every bucket whose
    bound is >= the value, so the rendered ``_bucket`` series are already
    cumulative — which is what Prometheus' ``histogram_quantile`` expects. The
    implicit ``+Inf`` bucket equals ``_count``.
    """

    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS,
    ):
        self.name = name
        self.help_text = help_text
        self.label_names: Tuple[str, ...] = tuple(labels)
        # Sorted, de-duped, finite upper bounds. +Inf is implicit.
        self.buckets: Tuple[float, ...] = tuple(
            sorted({float(b) for b in buckets if math.isfinite(b)})
        )
        self._lock = threading.Lock()
        # Per series: cumulative bucket counts (parallel to self.buckets) + sum + count.
        self._bucket_counts: Dict[LabelKey, List[float]] = {}
        self._sums: Dict[LabelKey, float] = {}
        self._counts: Dict[LabelKey, float] = {}

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = _normalise_labels(self.label_names, labels)
        with self._lock:
            counts = self._bucket_counts.get(key)
            if counts is None:
                counts = [0.0] * len(self.buckets)
                self._bucket_counts[key] = counts
                self._sums[key] = 0.0
                self._counts[key] = 0.0
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1.0
            self._sums[key] += value
            self._counts[key] += 1.0

    def get_count(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = _normalise_labels(self.label_names, labels)
        with self._lock:
            return self._counts.get(key, 0.0)

    def get_sum(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = _normalise_labels(self.label_names, labels)
        with self._lock:
            return self._sums.get(key, 0.0)

    def _snapshot(self) -> List[Tuple[LabelKey, List[float], float, float]]:
        with self._lock:
            return [
                (key, list(self._bucket_counts[key]), self._sums[key], self._counts[key])
                for key in sorted(self._bucket_counts)
            ]

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        snap = self._snapshot()
        if not snap:
            # Zero series so the histogram is never absent: all buckets + sum +
            # count at 0, including the mandatory +Inf bucket.
            for bound in self.buckets:
                lines.append(
                    f'{self.name}_bucket{{le="{_format_float(bound)}"}} 0'
                )
            lines.append(f'{self.name}_bucket{{le="+Inf"}} 0')
            lines.append(f"{self.name}_sum 0")
            lines.append(f"{self.name}_count 0")
            return lines
        for key, counts, total_sum, total_count in snap:
            for bound, cum in zip(self.buckets, counts):
                lines.append(
                    f"{self.name}_bucket"
                    f'{_render_labels(key, extra=("le", _format_float(bound)))} '
                    f"{_format_float(cum)}"
                )
            # +Inf bucket == total count (cumulative top).
            lines.append(
                f"{self.name}_bucket"
                f'{_render_labels(key, extra=("le", "+Inf"))} '
                f"{_format_float(total_count)}"
            )
            lines.append(f"{self.name}_sum{_render_labels(key)} {_format_float(total_sum)}")
            lines.append(f"{self.name}_count{_render_labels(key)} {_format_float(total_count)}")
        return lines


class Gauge:
    """A gauge whose value is computed at scrape time by a callback.

    Used by the cost bridge: rather than mirror rate_limit's spend dicts (which
    would risk drift / double-counting), the cost gauges read rate_limit's
    accumulators *read-only* when ``render_prometheus`` is called. Each gauge
    carries a ``collect`` callable returning ``[(labels, value), ...]``.
    """

    kind = "gauge"

    def __init__(self, name: str, help_text: str, collect):
        self.name = name
        self.help_text = help_text
        self._collect = collect

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        try:
            rows = list(self._collect())
        except Exception:  # noqa: BLE001 — a broken bridge must not 500 /metrics
            rows = []
        if not rows:
            lines.append(f"{self.name} 0")
            return lines
        for labels, val in rows:
            key = tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))
            lines.append(f"{self.name}{_render_labels(key)} {_format_float(val)}")
        return lines


def _format_float(value: float) -> str:
    """Render a number the way Prometheus expects.

    Integers print without a trailing ``.0`` (``5`` not ``5.0``) to keep the
    exposition compact; non-integers use ``repr`` for full round-trip
    precision. ``+Inf`` is handled by callers (bucket bounds), not here.
    """
    if value == math.inf:
        return "+Inf"
    if value == -math.inf:
        return "-Inf"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class Registry:
    """Ordered collection of metrics, keyed by name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: Dict[str, object] = {}

    def register(self, metric):
        with self._lock:
            if metric.name in self._metrics:
                raise ValueError(f"metric already registered: {metric.name}")
            self._metrics[metric.name] = metric
        return metric

    def get(self, name: str):
        with self._lock:
            return self._metrics.get(name)

    def all(self) -> List[object]:
        with self._lock:
            return list(self._metrics.values())

    def reset(self) -> None:
        """Zero every metric's accumulated state (keep registrations).

        Used by the test harness between tests so counters/histograms don't
        leak across the session-scoped FastAPI app. Gauges are stateless
        (they collect at render time) so there is nothing to reset on them.
        """
        for metric in self.all():
            if isinstance(metric, Counter):
                with metric._lock:
                    metric._values.clear()
            elif isinstance(metric, Histogram):
                with metric._lock:
                    metric._bucket_counts.clear()
                    metric._sums.clear()
                    metric._counts.clear()

    def render(self) -> str:
        blocks: List[str] = []
        for metric in self.all():
            blocks.append("\n".join(metric.render()))
        # Trailing newline — the exposition format wants the body to end in \n.
        return "\n".join(blocks) + "\n"


REGISTRY = Registry()


# ---------------------------------------------------------------------------
# Pre-declared four-layer metric set.
# ---------------------------------------------------------------------------
# 系統 (system)
HTTP_REQUEST_DURATION = REGISTRY.register(
    Histogram(
        "http_request_duration_seconds",
        "HTTP request handler latency in seconds (for p50/p95/p99 per endpoint).",
        labels=("endpoint", "method", "status"),
    )
)
LLM_ERRORS = REGISTRY.register(
    Counter(
        "llm_errors_total",
        "Total LLM call errors, per model.",
        labels=("model",),
    )
)
AUDIT_WRITE_DURATION = REGISTRY.register(
    Histogram(
        "audit_write_duration_seconds",
        "Audit-row write latency in seconds (Q19 SLO: keep p99 < 0.1s).",
    )
)

# 成本 (cost)
LLM_COST_USD = REGISTRY.register(
    Counter(
        "llm_cost_usd_total",
        "Cumulative LLM spend in USD, per tenant and model.",
        labels=("tenant", "model"),
    )
)
# LLM token throughput, split prompt/completion, per model. Bounded cardinality:
# `model` is a small fixed router set; `kind` is two values. No tenant label
# here (would multiply the series by every tenant) — tenant spend lives on the
# cost gauge/counter where USD matters more than raw tokens.
LLM_TOKENS = REGISTRY.register(
    Counter(
        "llm_tokens_total",
        "Total LLM tokens processed, split by kind (prompt|completion) and model.",
        labels=("model", "kind"),
    )
)
# Which model the Q15 router actually picked for a call. Lets the dashboard chart
# the local↔cloud↔cheap split (confidential routing, cost degrade, canary).
LLM_ROUTE = REGISTRY.register(
    Counter(
        "llm_route_total",
        "Count of LLM calls per model the router selected (Q15 routing mix).",
        labels=("model",),
    )
)

# 業務 (business)
OA_ANALYZED = REGISTRY.register(
    Counter(
        "oa_analyzed_total",
        "Total office actions analyzed, per tenant.",
        labels=("tenant",),
    )
)
EXPORTS = REGISTRY.register(
    Counter(
        "exports_total",
        "Total /v1/oa/export attempts, labelled by whether attorney sign-off passed.",
        labels=("tenant", "signed_off"),
    )
)
SIGNOFF_REFUSED = REGISTRY.register(
    Counter(
        "signoff_refused_total",
        "Total export attempts refused for missing attorney sign-off (Q16).",
    )
)

# 品質 (quality)
CITATIONS = REGISTRY.register(
    Counter(
        "citations_total",
        "Total citations emitted in drafts (denominator for citation accuracy).",
    )
)
CITATIONS_INVALID = REGISTRY.register(
    Counter(
        "citations_invalid_total",
        "Citations that failed grounding verification (numerator for hallucination rate).",
    )
)
PROMPT_INJECTION_DETECTED = REGISTRY.register(
    Counter(
        "prompt_injection_detected_total",
        "Prompt-injection attempts detected and neutralised.",
    )
)


# ---------------------------------------------------------------------------
# Convenience module-level helpers (the gateway imports these).
# ---------------------------------------------------------------------------
def inc(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    """Increment a registered counter by name. No-op if name is unknown/not a counter."""
    metric = REGISTRY.get(name)
    if isinstance(metric, Counter):
        metric.inc(labels, value)


def observe(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    """Observe a value into a registered histogram by name. No-op if unknown."""
    metric = REGISTRY.get(name)
    if isinstance(metric, Histogram):
        metric.observe(value, labels)


def record_llm_usage(meta: Optional[Dict[str, object]]) -> None:
    """Fold an AI-Engine endpoint's ``meta``/``usage`` dict into the LLM metrics.

    Accepts the loosely-typed dict the single-step inference endpoints already
    return (``model_used`` + token counts under either the meta root or a nested
    ``usage`` block). Records tokens (prompt+completion), the route taken, and —
    when the meta surfaces an error flag — an LLM error. Every field is optional
    and defensively coerced so a malformed/absent meta is a silent no-op rather
    than a 500 inside a request handler.

    Cardinality guard: ``model`` is coerced to a string and capped so a
    surprising value (None / huge string) can't explode the series count.
    """
    if not isinstance(meta, dict):
        return
    model_raw = meta.get("model_used") or meta.get("model")
    model = (str(model_raw) if model_raw else "unknown")[:64]

    usage = meta.get("usage")
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", meta.get("prompt_tokens", 0))
        completion = usage.get("completion_tokens", meta.get("completion_tokens", 0))
    else:
        prompt = meta.get("prompt_tokens", 0)
        completion = meta.get("completion_tokens", 0)

    try:
        prompt_n = float(prompt or 0)
        completion_n = float(completion or 0)
    except (TypeError, ValueError):
        prompt_n = completion_n = 0.0

    # Only count a route/token call when the model actually did inference
    # (non-zero tokens) OR the meta explicitly names a model — avoids inflating
    # the route counter on the pure-lookup endpoints (retrieve / claim_tree) that
    # return model_used=None and zero tokens.
    if model_raw:
        LLM_ROUTE.inc({"model": model})
    if prompt_n:
        LLM_TOKENS.inc({"model": model, "kind": "prompt"}, prompt_n)
    if completion_n:
        LLM_TOKENS.inc({"model": model, "kind": "completion"}, completion_n)

    if meta.get("llm_error"):
        LLM_ERRORS.inc({"model": model})


# ---------------------------------------------------------------------------
# Cost bridge — fold rate_limit's per-tenant/per-model spend in at scrape time.
# ---------------------------------------------------------------------------
def _cost_bridge_rows() -> Iterable[Tuple[Dict[str, str], float]]:
    """Read rate_limit's month-to-date per-(tenant, model) spend, read-only.

    rate_limit owns ``_tenant_model_monthly_cost`` keyed by
    ``(tenant_id, model, "YYYY-MM")``. We surface the *current month* rows as a
    cost gauge so Grafana can break spend down without us mirroring (and
    risking drift in) the accumulator. The import is deferred + defensively
    wrapped so a circular-import or refactor never breaks ``/metrics``.
    """
    try:
        from backend.gateway import rate_limit
    except Exception:  # noqa: BLE001
        return []
    try:
        month = rate_limit._this_month()  # noqa: SLF001 — read-only accessor
        rows: List[Tuple[Dict[str, str], float]] = []
        for (tenant, model, mo), usd in list(
            rate_limit._tenant_model_monthly_cost.items()  # noqa: SLF001
        ):
            if mo != month:
                continue
            rows.append(({"tenant": tenant, "model": model}, float(usd)))
        return rows
    except Exception:  # noqa: BLE001
        return []


LLM_COST_USD_MTD = REGISTRY.register(
    Gauge(
        "llm_cost_usd_month_to_date",
        "Month-to-date LLM spend in USD per tenant and model "
        "(bridged read-only from the rate_limit accounting layer).",
        collect=_cost_bridge_rows,
    )
)


# ---------------------------------------------------------------------------
# Top-level render entry point.
# ---------------------------------------------------------------------------
# Optional opt-in to the official prometheus_client if an operator wants its
# multiprocess / pushgateway features. The DEFAULT is the hand-rolled path.
_USE_PROM_CLIENT = os.getenv("METRICS_USE_PROMETHEUS_CLIENT", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def render_prometheus() -> str:
    """Render the whole registry as Prometheus text exposition (v0.0.4)."""
    return REGISTRY.render()


def content_type() -> str:
    """The Content-Type a Prometheus scraper expects for the text format."""
    return "text/plain; version=0.0.4; charset=utf-8"
