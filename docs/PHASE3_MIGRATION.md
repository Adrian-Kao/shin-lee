# Phase 3: Migration to digiRunner + Dify

**Planning doc — 2026-06-05**
**Author:** Claude (research + artefact generation pass)
**Scope:** PLAN + ARTEFACTS only. No backend / frontend code touched in this pass.
**Companion artefacts:** `dify_workflows/*.workflow.json`, `digirunner/*.yaml`, `dify_workflows/prompts_export.md`.

---

## 0. TL;DR

- **Why:** the user has chosen TPIsoftware digiRunner + Dify as the production landing stack. Both ship 2026 features that subsume parts of our hand-rolled gateway (`auth.py`, `rate_limit.py`) and orchestrator (`orchestrator.py` 6-step DAG) without sacrificing the 8 invariants in `CLAUDE.md §4` — provided we move carefully.
- **What stays:** every Q10 / Q13 / Q14 / Q15 differentiator. Mapping table, audit hash chain, grounded-citation verifier, confidential-routing rule. These are our IP and the regulator-facing story.
- **What moves:** Q12 auth (→ digiRunner OIDC), Q18 RPM (→ digiRunner policy plugin), Q1 orchestration step graph (→ Dify workflow DSL). The LLM prompts (already YAML-externalised in Day 8A) paste-import into Dify LLM nodes 1:1.
- **Rollout:** four phases over ~4 weeks (3.1 design + shadow, 3.2 digiRunner front-line, 3.3 cutover, 3.4 cleanup). Acceptance gates per phase; rollback is a DNS / vite-proxy env flip.
- **Risk top-3:** (a) Dify workflow output diverging from our orchestrator on edge cases — mitigated by shadow mode + `eval_cases.py` harness against 30 cases; (b) digiRunner trust-list misconfiguration giving upstream-header auth to wrong IP — mitigated by Day 8C's per-IP whitelist + non-loopback boot guard; (c) Confidential-case routing slipping through Dify default LLM provider — mitigated by keeping our orchestrator's `_security_level_for_case()` check on the thin-gateway side AND adding a Dify IF/ELSE branch.
- **Day-0 effort estimate:** 1 senior FE/BE engineer × ~4 weeks + 1 TPIsoftware solution architect for ~1 week (configuration + reference architecture review). Cost: digiRunner licensing + Dify hosting (self-host or Dify Cloud team plan). See §10.

---

## 1. Goals + non-goals

### 1.1 Goals
- Production-grade auth via digiRunner OIDC against the firm's IdP (Keycloak / Auth0 / Okta), replacing our POC `_USERS` dict and HS256 single-secret JWT.
- No-code workflow editing: non-engineers (paralegals, prompt engineers) can iterate on `parse_oa` / `draft_response` / `verify_citations` prompts and the DAG without a Python deploy.
- Centrally managed Anthropic key inside digiRunner's AI gateway secret vault (TPIsoftware's 2026 [AI gateway feature](https://docs.tpi.dev/)) + Dify's model provider config. Removes the `.env` ANTHROPIC_API_KEY scatter risk.
- Governance + observability: digiRunner's [real-time monitoring dashboards with AI usage insights](https://www.tpisoftware.com/en/products/digirunner) replace our `print()` + Sentry-only path.
- Defence in depth preserved: our 8 invariants ([CLAUDE.md §4](../CLAUDE.md)) stay enforced — see §4 risk register for the per-invariant migration test.

### 1.2 Non-goals
- **Not** rewriting Q10 redaction (mapping table stays on-prem in `data/`, invariant per [CLAUDE.md §9](../CLAUDE.md)).
- **Not** rewriting Q13 audit chain (regulator-facing, hash-chained, our compliance story).
- **Not** rewriting Q14 grounded-citation verifier (Dify can call our `/v1/verify_citations` HTTP node — moving the logic into a Dify code node would erase the defence-in-depth invariant from [docs/SECURITY_AUDIT.md §"What's done well" item #4](./SECURITY_AUDIT.md)).
- **Not** rewriting Q15 confidential routing (single source of truth = our case-management rule; Dify gets a hint via IF/ELSE branch but never authoritative).
- **Not** rewriting the SPA (`frontend/`) — vite proxy `/api/*` re-points from `:8010` to digiRunner's listener.
- **Not** moving our case ACL model to digiRunner (case-level row authz lives in our thin gateway; digiRunner does coarse-grain endpoint authz only).

---

## 2. Architecture target

Current 3-layer:

```
Frontend (Vite SPA :5173)
    │ /api/*
    ▼
Gateway :8010  ── orchestrator.py (6-step DAG) ──► AI Engine :8011
    │                                                 │
    └─── audit.py, masking.py, cache.py, auth.py     └── llm_client.py
```

Target 5-layer:

```
┌────────────────────────────────────────────────────────────────────┐
│ Frontend (Vite SPA :5173)                                          │
└─────────────────────┬──────────────────────────────────────────────┘
                      │ /api/*  (vite proxy → digiRunner ingress)
                      ▼
┌────────────────────────────────────────────────────────────────────┐
│ digiRunner Enterprise (or digiRunner Cloud)                        │
│   - OIDC redirect → firm IdP                                       │
│   - Issued JWT → forwarded as x-user-id / x-tenant-id / x-role     │
│   - Rate limit policy (RPM + per-user quotas)                      │
│   - AI gateway feature: managed Anthropic key, usage dashboard     │
│   - Route definitions: OpenAPI import of our gateway spec          │
│   - Upstream → THIN gateway (via mTLS or trusted IP)               │
└─────────────────────┬──────────────────────────────────────────────┘
                      │ x-user-id, x-tenant-id, x-user-role headers
                      │ (validated identity; Day 8C upstream-auth path)
                      ▼
┌────────────────────────────────────────────────────────────────────┐
│ THIN gateway :8010  (post-migration: backend/gateway_thin/)        │
│   STAYS:  audit.append, masking.redact/unmask, case_acl,          │
│           cache.get/set (optional), thin auth shim                │
│   GONE:   login endpoint, JWT issuance, RPM policy, orchestrator  │
│   ENDPOINTS: /v1/gateway/redact          (Dify HTTP node calls)   │
│              /v1/gateway/audit/append    (Dify HTTP node calls)   │
│              /v1/gateway/audit/recent    (AuditView.jsx via dgR)  │
│              /v1/gateway/audit/verify    (AuditView.jsx via dgR)  │
│              /v1/gateway/quota           (dashboard via dgR)      │
└─────────────────────┬──────────────────────────────────────────────┘
                      │ HTTP (intra-VPC, mTLS in production)
                      ▼
┌────────────────────────────────────────────────────────────────────┐
│ Dify (1.6+, self-host or Dify Cloud)                               │
│   - Anthropic provider configured (claude-sonnet-4-6 + haiku-4-5) │
│   - Workflows: analyze_oa, extract_pdf, ocr_page                   │
│   - LLM nodes paste-import prompts/{parse_oa,draft,verify}.yaml    │
│   - HTTP nodes call thin gateway + AI engine direct                │
│   - IF/ELSE: confidential-case branch → internal Ollama provider   │
│   - Exposes workflows as MCP servers (Dify 1.6 feature)           │
└─────────────────────┬──────────────────────────────────────────────┘
                      │ HTTP
                      ▼
┌────────────────────────────────────────────────────────────────────┐
│ AI Engine :8011  (kept — Dify can't replace our deterministic      │
│   regex/dictionary code: pdf_parser, deadline, oa_analyzer text   │
│   normalization, rag retrieval against numpy/Qdrant store)        │
│   ENDPOINTS Dify will call:                                        │
│     POST /v1/retrieve_prior_art   (RAG retrieval, our IP)         │
│     POST /v1/deadline             (ROC holidays calc, our IP)     │
│     POST /v1/ai/extract_text      (PDF/DOCX → text)               │
│   ENDPOINTS Dify replaces:                                         │
│     POST /v1/parse_oa             (becomes a Dify LLM node)       │
│     POST /v1/draft_response       (becomes a Dify LLM node)       │
│     POST /v1/verify_citations     (becomes a Dify LLM node)       │
└────────────────────────────────────────────────────────────────────┘
```

Key shifts:

1. The orchestrator's 6-step DAG ([backend/gateway/orchestrator.py:73-141](../backend/gateway/orchestrator.py)) is now a Dify workflow graph (`dify_workflows/analyze_oa.workflow.json`). One workflow node per step.
2. The 3 LLM call sites in `llm_client.py` collapse into 3 Dify LLM nodes whose system prompts are paste-imported from the YAMLs externalised in Day 8A.
3. Redaction (Q3+Q10) becomes a Dify HTTP node calling our thin gateway's first-class `/v1/redact` (which Day 8B already shipped). Mapping table never leaves our box.
4. Audit (Q13) becomes a Dify HTTP node calling our thin gateway's first-class `/v1/audit/append` (which Day 8B already shipped). Hash chain stays authoritative in our SQLite (Phase 4: Postgres).
5. Case ACL (Q12) lives in the thin gateway — digiRunner's coarse endpoint authz cannot enforce per-row case_id, only role + path. Thin gateway re-checks `authorize_case_access(user, body.case_id)` after Pydantic parse (the post-Day 8G pattern).
6. Confidential routing (Q15) gets a Dify IF/ELSE branch upstream of the LLM nodes, plus our orchestrator's check stays as defense-in-depth on the thin gateway side. Belt + braces, per [SECURITY_AUDIT.md §"What's done well" item #2](./SECURITY_AUDIT.md).

---

## 3. What stays vs what moves

| Concern | Today | Post-3.3 | Evidence file:line |
|---|---|---|---|
| OIDC / login | `backend/gateway/main.py:266` (built-in /v1/auth/login) | digiRunner OIDC → IdP | [main.py:266-344](../backend/gateway/main.py) |
| JWT issuance + verify | `backend/gateway/auth.py:68-96` | digiRunner mints; thin gateway trusts upstream headers | [auth.py:68-96](../backend/gateway/auth.py) |
| Per-user RPM | `backend/gateway/rate_limit.py:check_rpm` | digiRunner policy plugin | [rate_limit.py](../backend/gateway/rate_limit.py) |
| Per-user token quota | `backend/gateway/rate_limit.py:check_quotas` | digiRunner AI gateway quota | [rate_limit.py](../backend/gateway/rate_limit.py) |
| Cost circuit breaker | `backend/gateway/rate_limit.py:cost_circuit_state` | digiRunner AI gateway dashboard | [rate_limit.py](../backend/gateway/rate_limit.py) |
| 6-step orchestration | `backend/gateway/orchestrator.py:58-198` | Dify workflow JSON | [orchestrator.py:58-198](../backend/gateway/orchestrator.py) |
| LLM call: parse_oa | `backend/ai_engine/oa_analyzer.py` + `llm_client.py` | Dify LLM node (system from `parse_oa.yaml`) | [parse_oa.yaml](../backend/ai_engine/prompts/parse_oa.yaml) |
| LLM call: draft_response | `oa_analyzer.py` + `llm_client.py` | Dify LLM node (system from `draft_response.yaml`) | [draft_response.yaml](../backend/ai_engine/prompts/draft_response.yaml) |
| LLM call: verify_citations | `oa_analyzer.py` + `llm_client.py` | Dify LLM node (system from `verify_citations.yaml`) | [verify_citations.yaml](../backend/ai_engine/prompts/verify_citations.yaml) |
| Anthropic key storage | `.env` ANTHROPIC_API_KEY scattered | digiRunner AI gateway secret vault + Dify provider config | [config.py](../backend/shared/config.py) |
| Redaction (PII + dict) | `backend/gateway/masking.py` | **STAYS** — Dify HTTP node calls `/v1/redact` | [masking.py](../backend/gateway/masking.py) |
| Mapping table | `data/redaction_mapping.db` (gitignored) | **STAYS** — never leaves on-prem | [CLAUDE.md §9 "Don't store mapping table outside on-prem"](../CLAUDE.md) |
| Audit hash chain | `backend/gateway/audit.py` (SQLite) | **STAYS** — Dify HTTP node calls `/v1/audit/append` | [audit.py](../backend/gateway/audit.py) |
| Case ACL | `backend/gateway/auth.py:authorize_case_access` | **STAYS** — thin gateway re-checks after Pydantic parse (post-Day 8G) | [auth.py:117-135](../backend/gateway/auth.py) |
| Confidential-case routing | `backend/gateway/orchestrator.py:201-209` + `llm_client.py` defense-in-depth | **STAYS as authoritative** + Dify IF/ELSE branch as upstream hint | [orchestrator.py:201-209](../backend/gateway/orchestrator.py) |
| Grounded-citation verifier | `backend/ai_engine/oa_analyzer.py` | **STAYS** — Dify HTTP node calls our `/v1/verify_citations` (the verifier is the wall, per [CLAUDE.md §4 invariant #5](../CLAUDE.md)) | [oa_analyzer.py](../backend/ai_engine/oa_analyzer.py) |
| RAG retrieval | `backend/ai_engine/rag.py` | **STAYS** — Dify HTTP node calls `/v1/retrieve_prior_art` | [rag.py](../backend/ai_engine/rag.py) |
| Deadline calc (ROC holidays) | `backend/ai_engine/deadline.py` | **STAYS** — Dify HTTP node calls `/v1/deadline` | [deadline.py](../backend/ai_engine/deadline.py) |
| PDF / DOCX extraction | `backend/ai_engine/pdf_parser.py` | **STAYS** — Dify Iteration node calls `/v1/ai/extract_text` | [pdf_parser.py](../backend/ai_engine/pdf_parser.py) |
| Vision OCR (scanned PDF) | `backend/ai_engine/llm_client.py:vision_ocr` | **STAYS** initially. Phase 4 option: move to Dify Vision node with confidential branch | [llm_client.py](../backend/ai_engine/llm_client.py) |
| Frontend | Vite SPA | **UNCHANGED** — vite proxy re-points `/api/*` to digiRunner | [client.js](../frontend/src/api/client.js) |
| Case ACL data | `_CASE_ACL` dict in `auth.py` | **STAYS** initially. Phase 4: Postgres | [auth.py](../backend/gateway/auth.py) |
| Demo passwords / X-Demo-Secret | `backend/gateway/main.py:266` | **GONE** — replaced by IdP login. The whole `_DUMMY_HASH_FOR_TIMING` and `DEMO_LOGIN_SECRET` machinery deletes. | [main.py:266-356](../backend/gateway/main.py) |

---

## 4. Migration phases

### Phase 3.1 — Dify workflow design + shadow mode (1 week)

**Goal:** stand up Dify, build the 3 workflows, prove output equivalence on 30 cases before any traffic switch.

**Steps:**
1. Provision Dify sandbox. Self-host (docker-compose) OR Dify Cloud (per Dify docs, both support DSL import). Confirm version is **1.6+** for two-way MCP support (so we can later expose `claim_tree` as an MCP tool — see [Dify v1.6 release notes](https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support)).
2. Configure Anthropic as a model provider in Dify (`claude-sonnet-4-6` + `claude-haiku-4-5-20251001`). Reuse the existing `ANTHROPIC_API_KEY` — no double key.
3. Import workflows: `dify_workflows/analyze_oa.workflow.json`, `extract_pdf.workflow.json`, `ocr_page.workflow.json`. Verify graph renders. Fix any node IDs Dify assigns at import (Dify generates timestamp-based node IDs; our pseudo-IDs are placeholders — see `prompts_export.md` for the manual fallback).
4. Wire each LLM node's system prompt: copy from `backend/ai_engine/prompts/*.yaml` `system:` block. `dify_workflows/prompts_export.md` has paste-ready strings.
5. Wire HTTP nodes to point at our thin gateway and AI engine (`http://<thin-gw>:8010/v1/gateway/redact` etc.). For local dev, use `host.docker.internal`. For sandbox, set CIDR allow-list on the thin gateway upstream-trust list (Day 8C `UPSTREAM_AUTH_TRUSTED_IPS` env).
6. **Shadow mode:** in `backend/gateway/orchestrator.py` — add a `SHADOW_DIFY_WORKFLOW_URL` env. When set, after producing our own AnalysisResponse, fire-and-forget a request to Dify's workflow `run` API with the same input, write the response to `data/shadow/<request_id>.json`, never block the caller. `scripts/eval_cases.py` reads both and diffs.
7. Run shadow against all 30 synthetic cases (`data/cases/`). Compare:
   - `oa.rejections[].rejection_type` — must match
   - `oa.rejections[].affected_claims` — must match
   - `drafts[].grounded_citations` — set-equality (order independent)
   - `deadline_summary.statutory_deadline` — must match
8. **Acceptance:** Dify workflow matches our orchestrator on **>= 28/30 cases**. The 2 allowed misses must be documented (probably the multi-rejection edge case where rejection ordering differs).

**Files touched:** `backend/gateway/orchestrator.py` (add `_shadow_call_dify` helper, behind env flag, NOT removing existing path). New: `scripts/diff_shadow.py`. No frontend / thin-gateway / AI-engine code change.

**Rollback:** unset `SHADOW_DIFY_WORKFLOW_URL`. Zero impact.

### Phase 3.2 — digiRunner front-line + thin gateway (1 week)

**Goal:** stand up digiRunner; switch the SPA from `:8010` direct to digiRunner; thin out the gateway.

**Steps:**
1. Provision digiRunner. From [TPIsoftware product page](https://www.tpisoftware.com/en/products/digirunner): "OAuth 2.0 authentication, OpenID Connect (OIDC) and API Key for authentication, with mTLS and JWT key encryption". Pick the SKU per §10.
2. Configure OIDC against the firm's IdP. Use `digirunner/oidc.yaml` template — placeholders for issuer URL, client ID, client secret, scopes.
3. Define routes via OpenAPI import (digiRunner supports OAS 2/3 upload per [docs.tpi.dev/guide/api-management/api-registry](https://docs.tpi.dev/guide/api-management/api-registry)). Export our FastAPI OpenAPI spec (`backend/gateway/main.py` already publishes `/openapi.json`) and upload to digiRunner. Then per-route: set upstream to thin gateway, attach OIDC policy, attach rate-limit policy. Use `digirunner/routes.yaml` template (operator transcribes into the digiRunner UI; the YAML is the design intent + audit trail).
4. Configure upstream-header forwarding. digiRunner adds: `x-user-id`, `x-tenant-id`, `x-user-role` (Day 8C path our thin gateway already trusts). Critically: digiRunner is the **single trusted upstream IP**; our thin gateway's `UPSTREAM_AUTH_TRUSTED_IPS` allow-list contains only digiRunner's outbound IP.
5. Wire rate-limit policy at digiRunner level. From [TPIsoftware docs](https://www.tpisoftware.com/en/products/digirunner): "Manage AI endpoints with governance, routing, rate limiting, and access control". Match our existing thresholds (60 RPM/user default, the value in `backend/gateway/rate_limit.py`).
6. Thin out the gateway:
   - Keep: `audit.py`, `masking.py`, `cache.py`, the case-ACL part of `auth.py` (the `authorize_case_access` function + `_CASE_ACL` data), `_internal_headers()` for talking to AI engine.
   - Drop: `/v1/auth/login` endpoint, `_USERS` table, `_DUMMY_HASH_FOR_TIMING`, `_verify_password`, `DEMO_LOGIN_SECRET` path, `rate_limit.check_rpm/check_quotas/check_login_rpm` enforcement (the data accumulators stay if dashboard reads them; the enforcement is now upstream).
   - The `auth_dependency` becomes "read upstream headers via Day 8C's already-shipped path; refuse JWT auth path".
7. Re-run all 120 pytests. They should still pass — the upstream-header path was Day 8C's deliverable and is already test-covered.
8. **Acceptance:**
   - All 120 pytests green.
   - Every SECURITY_AUDIT.md C-1..C-4 still holds (re-tested: upstream header from wrong IP returns 401; upstream header from trusted IP with role=AUDITOR claim → thin gateway *demotes* to local-table role per Day 8C confused-deputy defence).
   - The 5 must-survive invariants pass:
     - Invariant #1 (Gateway never directly calls LLM): grep `llm_client` in `gateway_thin/` returns no hits.
     - Invariant #3 (Redaction mandatory): every path to Dify goes through `/v1/redact`.
     - Invariant #4 (Audit on every request): Dify workflow has audit HTTP node on every exit branch.
     - Invariant #6 (case_id checked on every request): thin gateway's `authorize_case_access` still fires post-Pydantic-parse.
     - Invariant #7 (confidential auto-routes local): Dify IF/ELSE branch + thin gateway re-check.

**Files touched:** rename `backend/gateway/` → `backend/gateway_thin/`. Move `orchestrator.py` to `legacy/orchestrator.py.bak` (not deleted yet; see 3.4). Update `client.js` vite proxy target if needed.

**Rollback:** revert the rename, traffic split via vite proxy env.

### Phase 3.3 — Cutover (3 days)

**Goal:** flip live traffic with zero data loss + working rollback in < 5 minutes.

**Steps:**
1. **Day 1 (pilot tenant):** pick one demo law firm (one tenant_id). Configure DNS for that tenant's subdomain to resolve to digiRunner; other tenants stay on direct `:8010`. Use digiRunner's per-route weighting if available, otherwise `vite.config.js` proxy env var split.
2. **Day 1 monitoring:** watch digiRunner dashboard (request rate, error rate, p95 latency), Sentry (frontend + backend), thin-gateway audit log (volume + chain verify). Alert thresholds: error rate > 2%, p95 latency > 5s, audit chain verify fail.
3. **Day 2 (gradual ramp):** if Day 1 green for 24h, switch second tenant. Then third. Watch each.
4. **Day 3 (full cutover):** all tenants on digiRunner. Direct `:8010` still listening for emergency rollback.
5. **Rollback procedure** (any time during 3.3 within 5 min):
   - Revert DNS / vite proxy env to point at `:8010`.
   - Thin gateway is still running; the `gateway_thin` code path accepts direct calls if the upstream-header auth path is satisfied — OR we keep a "emergency legacy login" fallback enabled by env flag for this exact rollback window.
   - Outstanding Dify workflow runs complete; their audit rows still append correctly (the audit endpoint accepts any properly-signed request from the trusted IP).
6. **Acceptance:**
   - 72h post-cutover with error rate < 2%, p95 < 5s, zero audit chain verify failures across all tenants (per-tenant verify still single-tenant; H-4 cross-tenant verify remains open from `SECURITY_AUDIT.md`).

### Phase 3.4 — Post-cutover cleanup (1 week)

**Goal:** delete the legacy paths so they can't accidentally come back.

**Steps:**
1. Delete `legacy/orchestrator.py.bak`, the entire `_USERS` machinery, `LoginRequest`/`LoginResponse`, `_DUMMY_HASH_FOR_TIMING`, the demo-secret header handling. Update tests to delete or skip tests that target the legacy login.
2. Update CI: GitHub Actions adds a sandbox-digiRunner smoke job alongside the existing pytest+vite build. (Likely a `docker-compose -f docker-compose.dgr.yml` with a minimal digiRunner image for CI hermeticity.)
3. Update `HANDOFF.md §21` (added in this pass; see "Updates to handoff" below).
4. Train operators on Dify workflow editor (1-2h session). Hand them `prompts_export.md` so they know which YAML the prompt came from when they want to A/B test a variant.

**Acceptance:** `grep -r "LoginRequest\|_USERS\|_DUMMY_HASH" backend/` returns 0 hits. CI sandbox-digiRunner job green for 5 consecutive runs.

---

## 5. Concrete artefacts shipped in this doc

- §6 — three Dify workflow JSON files (in `dify_workflows/`)
- §7 — three digiRunner config YAMLs (in `digirunner/`)
- §8 — thin-gateway shape (file list to keep / drop)
- `dify_workflows/prompts_export.md` — paste-ready system prompts (operator's manual-setup fallback if JSON import has quirks)
- `dify_workflows/README.md` (this section, mirrored as `dify_workflows/README.md`)

---

## 6. Dify workflow JSON files

### Dify schema confidence statement

Dify's official documentation does not publish a stable formal schema for the workflow DSL. The most authoritative public artefacts are:

- The community-driven sample [Winson-030/dify-DSL](https://github.com/Winson-030/dify-DSL/blob/main/DifyDocumentQueryWorkflow.yml) which we reverse-engineered to confirm the shape: top-level `app:` / `workflow:` / `workflow.graph.nodes` / `workflow.graph.edges`.
- The Dify maintainer statement in [GitHub Discussion #8090](https://github.com/langgenius/dify/discussions/8090): *"Dify's DSL is essentially the JSON structure of the data in the front-end canvas. JSON passed from the front end is converted into a Python dictionary or model on the back end. These objects are then converted into YAML, but they basically retain their original structure."*
- The [HTTP-request node docs](https://docs.dify.ai/en/use-dify/nodes/http-request) confirming method / url / headers / params / body / authorization sub-keys.

Our JSON files therefore use what we believe is the canonical Dify 1.6+ shape but are best treated as **importable templates** rather than canonical. Sections of every file marked `// [CONFIRM WITH TPISOFT]` and `// PLACEHOLDER:` indicate spots where the operator must adjust IDs after Dify's import auto-assigns timestamp-based node IDs (per the `scripts/generate_id.py` convention in `dify-workflow-builder`).

Dify imports YAML natively (per [Dify Blog: Introducing Dify Workflow](https://dify.ai/blog/dify-ai-workflow)) but accepts JSON-compatible structure. We ship `.json` files for tooling friendliness; the operator can `yaml.safe_dump(json.load(f))` if Dify rejects the JSON form.

### 6.1 `analyze_oa.workflow.json` — main orchestrator

**DAG** (matches `backend/gateway/orchestrator.py:73-141`):

```
Start (vars: oa_text, tenant_id, case_id, target_patent_no, security_level)
  → HTTP redact_oa_text                 POST {THIN}/v1/gateway/redact
  → LLM parse_oa                        prompt: parse_oa.yaml
                                        model: claude-sonnet-4-6
                                        structured_output: rejections schema
  → HTTP retrieve_prior_art             POST {AI_ENGINE}/v1/retrieve_prior_art
                                        (one HTTP call per rejection — see Iteration note)
  → LLM draft_response                  prompt: draft_response.yaml
                                        model: claude-sonnet-4-6
  → LLM verify_citations                prompt: verify_citations.yaml
                                        model: claude-haiku-4-5-20251001
  → HTTP compute_deadline               POST {AI_ENGINE}/v1/deadline
  → HTTP append_audit                   POST {THIN}/v1/gateway/audit/append
  → IF/ELSE confidential branch         if security_level == "confidential":
                                          re-route LLM nodes to local Ollama provider
                                          (mirror branch — kept as defense-in-depth)
  → End (returns AnalysisResponse shape)
```

**Iteration:** retrieval + draft are per-rejection in our orchestrator (lines 84-117). In Dify 1.x this maps to the `iteration` node type wrapping retrieval + draft + verify, iterating over `parse_oa.rejections[]`. The iteration container holds: HTTP `retrieve` → LLM `draft` → LLM `verify`. Outputs aggregate into a `drafts[]` list at the iteration's output handle.

**Expected input** (from Start node):
```json
{
  "oa_text": "string (untrusted; will be redacted in node 1)",
  "tenant_id": "string",
  "case_id": "string",
  "target_patent_no": "string",
  "security_level": "public|confidential"
}
```

**Expected output** (at End node):
```json
{
  "request_id": "uuid",
  "oa": {"received_date": "...", "rejections": [...]},
  "drafts": [{"rejection_id": "...", "draft_text": "...", "grounded_citations": [...]}],
  "related_prior_art": [...],
  "deadline_summary": {...},
  "cost_meta": {...}
}
```

**LLM node prompt sources:**
- `parse_oa` node: paste from [`backend/ai_engine/prompts/parse_oa.yaml`](../backend/ai_engine/prompts/parse_oa.yaml) `system:` block.
- `draft_response` node: paste from `draft_response.yaml`.
- `verify_citations` node: paste from `verify_citations.yaml`.

**HTTP node targets:**
- `redact_oa_text` → `POST {{THIN_GATEWAY_URL}}/v1/gateway/redact` body `{"text":"{{Start.oa_text}}","tenant_id":"{{Start.tenant_id}}"}`. Returns `{"redacted":"...","mask_rules_triggered":[...]}`.
- `retrieve_prior_art` → `POST {{AI_ENGINE_URL}}/v1/retrieve_prior_art` body `{"tenant_id":"...","rejection":{...},"target_patent_no":"...","top_k":5}`. Returns `{"hits":[...]}`.
- `compute_deadline` → `POST {{AI_ENGINE_URL}}/v1/deadline` body `{"received_date_iso":"...","jurisdiction":"TW","calendar_version":"2025.1"}`. Returns `DeadlineInfo`.
- `append_audit` → `POST {{THIN_GATEWAY_URL}}/v1/gateway/audit/append` body matches `backend/gateway/main.py:AuditAppendRequest` (Day 8B endpoint). Returns `{"appended":true,"row_id":N}`.

**Authorization on every HTTP node:** `Authorization: Bearer {{env.INTERNAL_TOKEN}}` so the thin gateway accepts the call (digiRunner trust-list IP allow-list is the primary defence; the bearer is defense-in-depth).

### 6.2 `extract_pdf.workflow.json`

**Purpose:** when the SPA uploads a PDF/DOCX, this workflow runs first to convert binary → text, then feeds the text to `analyze_oa.workflow.json`.

**DAG:**

```
Start (vars: file_b64, content_type, tenant_id, case_id)
  → IF/ELSE branch by content_type
       application/pdf → HTTP extract_pdf_text   POST {AI_ENGINE}/v1/ai/extract_text
       application/vnd.openxmlformats-officedocument.wordprocessingml.document
                       → HTTP extract_docx_text  POST {AI_ENGINE}/v1/ai/extract_text
       else            → End (error: unsupported_content_type)
  → Iteration over extracted pages (only for scanned PDF)
       child workflow: ocr_page.workflow.json (per-page Vision OCR)
  → Variable aggregator: join page texts with "\n\n--- page break ---\n\n"
  → End (return concatenated text)
```

**Expected input:** base64-encoded file bytes + content type. Matches `backend/ai_engine/main.py:/v1/ai/extract_text` payload.

**Expected output:** `{"text":"...full extracted text...","pages":N,"used_ocr_pages":[...]}`.

### 6.3 `ocr_page.workflow.json`

**Purpose:** Vision OCR for one scanned PDF page. Called by `extract_pdf.workflow.json` from inside an Iteration node.

**DAG:**

```
Start (vars: page_image_b64, security_level)
  → IF/ELSE on security_level
       confidential → End (error: vision_ocr_blocked_for_confidential)
                      // mirrors backend/ai_engine/llm_client.py:vision_ocr's assert
       public       → LLM vision_ocr (model: claude-haiku-4-5-20251001, vision-enabled)
  → End (return page text)
```

**Why a separate workflow:** Dify 1.x Iteration child can be a code node or a tool, but exposing OCR as its own workflow lets us A/B-test (e.g., switch to a local model via a Dify provider swap) without editing `extract_pdf`.

### 6.4 `prompts_export.md`

Paste-ready system prompts for operators to manually populate the 3 LLM nodes if JSON import has quirks. See `dify_workflows/prompts_export.md`.

---

## 7. digiRunner config templates

### Schema confidence statement

digiRunner's [official docs](https://docs.tpi.dev/) make it clear that route + OIDC + policy configuration happens via the digiRunner **UI** (web admin console), not declarative YAML files like Kong / Apigee. From [docs.tpi.dev API Registry](https://docs.tpi.dev/guide/api-management/api-registry): three registration methods are OpenAPI document upload, Custom URL Registration, or UI form. There is no documented "kubectl-apply-this-YAML" pattern.

Therefore `digirunner/*.yaml` files are **design intent + audit trail** templates for the operator to transcribe into the digiRunner UI. They are valid YAML for portability but are NOT canonical digiRunner config — every field is `[CONFIRM WITH TPISOFT]`-able.

### 7.1 `routes.yaml`

Design-intent YAML for the routes the operator registers in digiRunner. One entry per upstream URL. See `digirunner/routes.yaml`.

### 7.2 `oidc.yaml`

OIDC provider template with placeholders for the firm's Keycloak / Auth0 / Okta. See `digirunner/oidc.yaml`.

### 7.3 `ai-gateway-models.yaml`

Managed model config: Anthropic key (from external secret), claude-sonnet-4-6 routing rules, cost tracking per `x-case-id` header forwarded by digiRunner. See `digirunner/ai-gateway-models.yaml`.

---

## 8. Thin gateway shape (post-migration `backend/gateway_thin/`)

### Files that survive

| File | Purpose | Why it stays |
|---|---|---|
| `audit.py` | Q13 SQLite hash-chain audit | Differentiator. Regulator story. Per-tenant chain authoritative. |
| `masking.py` | Q10 PII + customer dictionary, reversible | Differentiator. Mapping table never leaves on-prem ([CLAUDE.md §9](../CLAUDE.md)). |
| `cache.py` | Q9 in-memory response cache | Optional. Could move to digiRunner cache plugin. Keep for now — defense-in-depth latency. |
| `case_acl.py` | Extracted from current `auth.py` — only `authorize_case_access` + `_CASE_ACL` | digiRunner does endpoint authz only. Per-row case_id authz stays here. |
| Upstream-header auth shim | The portion of `auth.py` that reads `x-user-id` / `x-tenant-id` / `x-user-role` from trusted IPs (Day 8C, already shipped) | Required boundary trust check. |

### Files that leave

| File | Where it goes |
|---|---|
| `main.py:/v1/auth/login` + `LoginRequest`/`LoginResponse` + `_DUMMY_HASH_FOR_TIMING` + demo-secret path | Gone. Replaced by digiRunner OIDC. |
| `auth.py:_USERS` + `_get_password_hash` + `_verify_password` + `issue_token` + `verify_token` | Gone. digiRunner mints JWTs; thin gateway only reads headers. |
| `rate_limit.py:check_rpm` + `check_login_rpm` enforcement | Gone. digiRunner policy plugin enforces. (Cost accumulator code MAY stay if we want the local dashboard.) |
| `orchestrator.py` | Gone. Replaced by `dify_workflows/analyze_oa.workflow.json`. |
| `main.py:analyze_oa` endpoint | Gone. Frontend now calls digiRunner → digiRunner → Dify workflow. |
| `main.py:upload_oa` endpoint | Gone. Frontend now calls digiRunner → Dify `extract_pdf.workflow.json`. |
| `main.py:/v1/redaction_preview` | Stays (renamed `/v1/gateway/redact` per Day 8B; legacy alias kept until 3.4 cleanup). |
| Login pre-auth rate limit (Day 8I) | Gone. digiRunner edge protects. |

### Thin gateway's endpoints (post-migration)

```
POST /v1/gateway/redact          — called by Dify HTTP node, requires Bearer INTERNAL_TOKEN + upstream-trusted IP
POST /v1/gateway/audit/append    — called by Dify HTTP node, same auth
GET  /v1/gateway/audit/recent    — called by AuditView.jsx via digiRunner (digiRunner forwards user identity)
GET  /v1/gateway/audit/verify    — same; AUDITOR role required
GET  /v1/gateway/quota           — read-only dashboard; tenant scope from forwarded headers
GET  /v1/health                  — liveness probe, no auth
```

Every endpoint applies: (a) upstream-trusted-IP check (Day 8C); (b) bearer token check; (c) where the endpoint needs case_id authz (e.g., `/v1/gateway/redact` with a case_id in body), `authorize_case_access(user, body.case_id)` runs after Pydantic parse (the post-Day 8G pattern).

---

## 9. Risk register

| Risk | Severity | Impact | Mitigation | Owner | Phase |
|---|---|---|---|---|---|
| Dify workflow output diverges from our orchestrator on edge cases | High | Wrong rejection_type / missed citation / divergent deadline → attorney loses trust | Shadow mode in 3.1 + `scripts/diff_shadow.py` against 30 cases. Acceptance gate >= 28/30. | Eng | 3.1 |
| digiRunner OIDC config error (wrong client secret, wrong scope) | High | Login broken; emergency rollback needed | Day 8C `UPSTREAM_AUTH_TRUSTED_IPS` is per-IP, not wildcard — wrong IP = no auth bypass. Pre-cutover smoke test in sandbox. | Ops + TPIsoft | 3.2 |
| Anthropic key in two places during 3.1 shadow | Medium | Double cost if Dify calls real API in shadow | Use the same key in both Dify and our `.env`. Shadow's Dify run charges once. Verify in 3.1 acceptance by comparing Anthropic dashboard usage. | Eng | 3.1 |
| Case ACL state split between digiRunner endpoint authz and our thin gateway row authz | Medium | Possible double-403 or coverage gap | Ours stays authoritative. digiRunner trusts our 403. Document in operator runbook. | Eng | 3.2 |
| Confidential routing miss: a confidential case slips through Dify's default cloud LLM | **Critical** | PII / privileged content leaks to Anthropic | Three defences (belt + braces + suspenders): (a) digiRunner AI gateway routes confidential `x-case-id` ending `-CONF` to local provider; (b) Dify IF/ELSE branch checks `Start.security_level` and routes to internal Ollama provider; (c) thin gateway audit row records `policy_decisions.local_lm_used=true` for cross-check. Plus our existing `llm_client.py:556-563` defense-in-depth assert STAYS in any path that still flows through our AI engine. | Eng + Sec | 3.1 + 3.2 |
| Audit chain split: digiRunner logs request metadata, we log invariant audit row, neither is authoritative | High | Forensic gap if a row is missing | Our `/v1/gateway/audit/append` STAYS the single source of truth for the hash chain. digiRunner logs are operational, not regulatory. The Dify workflow's terminal HTTP node always calls `/v1/gateway/audit/append` (no IF/ELSE branch skips it). Verified by 3.2 acceptance: re-run pytest `test_audit_error_path.py` against the new flow. | Eng | 3.2 |
| Dify schema instability (Dify upgrades break our JSON) | Medium | Workflow import fails after Dify upgrade | Pin Dify version. Test imports after every Dify minor bump in CI sandbox job. | Ops | 3.4+ |
| Operator without prompt-engineering background edits a Dify LLM node and breaks the JSON output contract | Medium | `parse_oa` returns malformed JSON → orchestration fails downstream | Use Dify 1.3+ Structured Outputs feature with JSON Schema editor enabled on each LLM node (per [Dify v1.3 announcement](https://x.com/dify_ai/status/1914991892611416342)). Add unit-test-style "schema validation" code node after each LLM node. | Eng | 3.1 |
| digiRunner trusted-IP allow-list misconfigured (loopback only) but production uses non-loopback | High | Thin gateway refuses all calls | Day 8C added a boot guard: non-loopback trust without `UPSTREAM_AUTH_SHARED_SECRET` in non-mock mode raises at startup. Verify in 3.2 acceptance. | Ops | 3.2 |
| MCP exposure (Dify 1.6 feature) leaks a workflow's URL with embedded credentials | High | Anyone with the MCP URL can call the workflow | Per [Dify MCP docs](https://docs.dify.ai/en/use-dify/publish/publish-mcp): "treat it like an API key". Don't expose `analyze_oa` as MCP. We do expose `claim_tree` lookup later only via authenticated digiRunner route. | Eng | 3.4+ |

---

## 10. Open questions for TPIsoftware contact

1. **SKU selection.** Which digiRunner SKU fits our profile (one law firm, ~100 attorneys, ~1000 OAs/month, on-prem-preferred)? Options visible in public docs: `digiRunner Enterprise (Standalone / High Availability)`, `digiRunner Lite (Standalone / HA)`, `digiRunner Cloud`, and `digiRunner Express`. Public pricing is "request a quote" — see [Capterra](https://www.capterra.com/p/10015814/digiRunner/). Likely answer: Enterprise Standalone for on-prem law firm pilot; HA for multi-firm SaaS later.
2. **Dify integration reference architecture.** Does TPIsoftware publish a digiRunner-fronts-Dify reference architecture? Their [COMPUTEX 2026 announcement](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html) refers to "managing LLMs and AI agents" but no specific Dify reference doc surfaced in our search. Ask for: a diagram + sample config + reference customer using both.
3. **Cost estimate (back-of-envelope for stakeholder pitch).** For 100 attorneys + 1k OAs/month: digiRunner Enterprise license (annual) + Dify Cloud team plan OR Dify self-host infra. Anthropic cost is `~$5-10/day` per `HANDOFF.md §13.3` so that's separable. We need the digiRunner + Dify annual TCO.
4. **Reference customer in patent / legal vertical.** Any Taiwan or APAC law firm using digiRunner + Dify together? Helps the stakeholder pitch.
5. **Dify version + MCP support on TPIsoftware's recommended Dify deployment.** Need 1.6+ for two-way MCP (we don't depend on it for analyze_oa but want it for future `claim_tree` MCP tool). Public docs show Dify 1.x is current — confirm.
6. **Migration support hours.** TPIsoftware solution architect consulting cost for the 3.2 OIDC + routes setup. Budget 1 week (~40 hours).
7. **digiRunner AI gateway feature: managed Anthropic key.** Confirm digiRunner's AI gateway feature ([2026 product page](https://www.tpisoftware.com/en/products/digirunner)) supports: (a) Anthropic provider with `claude-sonnet-4-6` model name; (b) prompt caching pass-through (we use 5-min ephemeral cache for our patent-specific system prompts, per `HANDOFF.md §13.3`); (c) per-`x-case-id` cost tagging.
8. **digiRunner config-as-code option.** Public docs are UI-first ([docs.tpi.dev](https://docs.tpi.dev/)). Is there a `gitops` mode (export config to YAML, version-control it, apply via CI)? Without it, our Phase 3.4 "CI sandbox-digiRunner smoke job" needs a Terraform / Pulumi / API-driven path.
9. **mTLS between digiRunner and thin gateway.** Day 8C path is upstream-IP + bearer. Production should add mTLS. digiRunner docs reference mTLS support — what's the cert provisioning + rotation story?
10. **Holiday calendar feed.** Out of scope for Phase 3 but related: our `deadline.py` hardcodes 2025 ROC holidays. Does TPIsoftware have a recommended way to feed holiday tables into Dify workflows (a tool we can register), or do we keep it in our AI engine?

---

## 11. Updates to handoff

Append the following to `HANDOFF.md` (see §21 added in this pass): "Phase 3 migration plan: see `docs/PHASE3_MIGRATION.md`. Generated artefacts in `dify_workflows/` and `digirunner/`."

---

## Sources

- [TPIsoftware digiRunner APIM Platform](https://www.tpisoftware.com/en/products/digirunner)
- [TPIsoftware digiRunner Cloud](https://www.tpisoftware.com/en/products/digirunner-cloud)
- [digiRunner Documentation (docs.tpi.dev)](https://docs.tpi.dev/)
- [digiRunner API Registry guide](https://docs.tpi.dev/guide/api-management/api-registry)
- [digiRunner APIM Architecture](https://docs.tpi.dev/overview/apim-architecture/integration)
- [digiRunner Open Source on GitHub](https://github.com/TPIsoftwareOSPO/digiRunner-Open-Source)
- [TPIsoftware COMPUTEX 2026 announcement (PRNewswire)](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html)
- [TPIsoftware blog: OIDC and API management](https://blog.tpisoftware.com/en/smartmgmt/apimgmt/oidc-apim/)
- [digiRunner pricing on Capterra](https://www.capterra.com/p/10015814/digiRunner/)
- [digiRunner Enterprise on AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-pmlw6yaa37dju)
- [Dify Docs: Workflow & Node Description](https://docs.dify.ai/guides/workflow/node)
- [Dify Docs: HTTP Request node](https://docs.dify.ai/en/use-dify/nodes/http-request)
- [Dify Docs: LLM node (legacy)](https://legacy-docs.dify.ai/guides/workflow/node/llm)
- [Dify Docs: MCP Server publish](https://docs.dify.ai/en/use-dify/publish/publish-mcp)
- [Dify Blog: Introducing Dify Workflow](https://dify.ai/blog/dify-ai-workflow)
- [Dify Blog: v1.6 two-way MCP support](https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support)
- [Dify v1.3 Structured Outputs announcement](https://x.com/dify_ai/status/1914991892611416342)
- [Dify DSL community discussion #8090](https://github.com/langgenius/dify/discussions/8090)
- [Awesome Dify Workflow examples](https://github.com/svcvit/Awesome-Dify-Workflow/blob/main/README_EN.md)
- [Winson-030 Dify DSL sample (workflow YAML structure reference)](https://github.com/Winson-030/dify-DSL/blob/main/DifyDocumentQueryWorkflow.yml)
- [Dify Workflow Skill discussion #34916](https://github.com/langgenius/dify/discussions/34916)
- [DslGenAgent — DSL generation reference](https://github.com/01554/DslGenAgent)
- Local source files referenced inline (CLAUDE.md, HANDOFF.md, docs/SECURITY_AUDIT.md, backend/ai_engine/prompts/*.yaml, backend/gateway/orchestrator.py)
