# Observability (Q19) — metrics, correlation IDs, structured logs

This document explains the Q19 observability surface: what `/metrics` exposes,
how a single request is traced end to end across the two services, and how to
wire Grafana.

> Decision (docs/DECISIONS.md Q19): **全套四層** — a four-layer dashboard:
> 系統 (system) · 品質 (quality) · 業務 (business) · 成本 (cost).
> The stub it replaces was "Prometheus 指標 stub + JSON log".

---

## 1. `/metrics` — Prometheus exposition

Both services expose a real Prometheus text exposition (format **v0.0.4**,
`Content-Type: text/plain; version=0.0.4; charset=utf-8`):

| Service    | URL                          |
|------------|------------------------------|
| Gateway    | `http://gateway:8010/metrics`   |
| AI Engine  | `http://ai_engine:8011/metrics` |

Implementation: `backend/shared/metrics.py` is a **dependency-free** in-process
registry (Counter / Histogram / Gauge) that renders the exposition by hand, so
the POC needs no extra `pip install`. An operator who already runs the official
client can set `METRICS_USE_PROMETHEUS_CLIENT=1` to opt in (lazy import); the
default is the hand-rolled path the test-suite exercises.

> **Security:** `/metrics` is intentionally **ungated at the app layer** — a
> Prometheus job can't mint a JWT or the AI Engine internal token. Restrict it
> at the **network layer** (internal-only listener, scrape credential at the
> reverse proxy, or a private Prometheus network). See the SECURITY NOTE on the
> gateway `/metrics` handler and `ops/grafana/prometheus_scrape.example.yml`.

### Metrics by layer

**系統 (system)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_request_duration_seconds` | histogram | `endpoint`, `method`, `status` | request latency → p50/p95/p99 per route (both services). |
| `audit_write_duration_seconds` | histogram | — | audit-row write latency. **SLO: p99 < 0.1s** (invariant #4). |
| `llm_errors_total` | counter | `model` | LLM call errors per model. |

**品質 (quality)**

| Metric | Type | Meaning |
|---|---|---|
| `citations_total` | counter | citations emitted in drafts (denominator). |
| `citations_invalid_total` | counter | citations that failed grounding (numerator → hallucination rate). |
| `prompt_injection_detected_total` | counter | prompt-injection attempts detected + neutralised (Q11). |

**業務 (business)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `oa_analyzed_total` | counter | `tenant` | office actions analyzed (not cache hits / errors). |
| `exports_total` | counter | `tenant`, `signed_off` | export attempts, split by attorney sign-off. |
| `signoff_refused_total` | counter | — | exports refused for missing sign-off (Q16 hard gate). |

**成本 (cost)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `llm_cost_usd_total` | counter | `tenant`, `model` | cumulative LLM spend (USD). |
| `llm_cost_usd_month_to_date` | gauge | `tenant`, `model` | MTD spend, bridged **read-only** from rate_limit at scrape time. |
| `llm_tokens_total` | counter | `model`, `kind` (`prompt`/`completion`) | LLM token throughput. |
| `llm_route_total` | counter | `model` | which model the Q15 router picked (local↔cloud↔cheap mix). |

### Cardinality discipline

Labels are **deliberately bounded**. `user_id` and `case_id` are NEVER labels —
they are high-cardinality and would explode the series count (and leak who did
what into the metrics store). `tenant` is the only tenant-level label and only
on metrics where per-tenant breakdown is operationally necessary. `model` is a
small fixed router set, capped at 64 chars defensively.

---

## 2. Correlation / request IDs — end-to-end tracing

Every request carries an `X-Request-ID`. One request → one id → both services'
logs.

```
client ──X-Request-ID?──▶ gateway ──X-Request-ID──▶ ai_engine
                            │                          │
                       bind + log                 bind + log
                       echo on response           echo on response
```

* **Gateway** (`request_id_middleware`, outermost layer): accepts an inbound
  `X-Request-ID` (so digiRunner / a reverse proxy can supply the trace id) or
  mints a fresh `uuid4` hex. It binds the id into a `contextvars.ContextVar`,
  echoes it on **every** response (including 4xx/5xx), and propagates it on the
  gateway→ai_engine call via `observability.request_id_headers(...)`.
* **AI Engine** (`_observability_middleware`, outermost layer): reads the
  inbound `X-Request-ID` back out, binds it, and echoes it — so its JSON log
  lines carry the **same** id as the gateway's.

The id is sanitised before use (trimmed, length-capped at 200, control/newline
chars stripped) so a forged header can't forge log lines.

### Propagation status

| Gateway → AI Engine call | Propagated? |
|---|---|
| `/v1/oa/upload` → `/v1/ai/extract_text` | ✅ wired (`request_id_headers`) |
| `orchestrator.AIEngineClient.call` (parse / retrieve / draft / verify / deadline) | ⚠ **pending** — see cross-file follow-up below |

> **Cross-file follow-up (not in Agent D's ownership):** the orchestrator's
> `AIEngineClient.call` (and its `_internal_headers()` source in `auth.py`)
> need a one-line change to send `request_id_headers(_internal_headers())`
> instead of `_internal_headers()`. The mechanism is in place
> (`observability.request_id_headers`); only those two call sites remain. Until
> then the analyze-path correlation is bound + logged on **each** service but
> the id is regenerated at the AI-Engine hop rather than shared. Logs are still
> structured and individually traceable; the gateway-side id still ties the
> whole gateway flow + audit row together.

---

## 3. Structured logging

`observability.configure_logging(service)` installs a JSON log formatter +
the request-id filter on the root handler (called at the top of each app's
`main.py`). Every log line is a single-line JSON object:

```json
{"ts":"2026-06-10T09:00:00+0000","level":"INFO","logger":"patentmind.gateway.egress",
 "service":"gateway","request_id":"a1b2c3...","message":"..."}
```

* `request_id` is stamped automatically — application code just calls
  `logger.info("...")`.
* `extra={...}` kwargs are folded in as top-level fields.
* `LOG_FORMAT=text` switches to a human-readable line for local dev;
  `LOG_LEVEL` (default `INFO`) gates verbosity.

---

## 4. Grafana

* Dashboard: `ops/grafana/patentmind_q19_dashboard.json` — import into Grafana,
  pick your Prometheus datasource. Panels cover all four layers + a `tenant`
  template variable.
* Scrape config: `ops/grafana/prometheus_scrape.example.yml`.

---

## 5. Sentry (optional)

`observability.init_sentry(service)` wires crash reporting when `SENTRY_DSN`
is set (no-op otherwise). PII is not sent (`send_default_pii=False`); every
event is tagged with `service`.
