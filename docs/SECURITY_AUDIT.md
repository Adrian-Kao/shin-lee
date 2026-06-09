# Security + Permission Audit — patentmind-poc (2026-06-01)

Auditor: Senior application security reviewer (Claude)
Scope: `feature/patentmind-poc` HEAD `6529538` (Day 7B) + peek at compat-refactor branches in `.claude/worktrees/`.
Method: read-only static analysis, file:line evidence for every finding.

---

## TL;DR

| Severity | Count | Examples (one-liner) |
|---|---|---|
| Critical | 4 | Unauthenticated login lets anyone mint any user's JWT; AI Engine has zero auth on every endpoint; gateway case-ACL bypass via missing X-Case-Id header; AI Engine `/v1/index/patent` lets unauth callers poison any tenant's RAG. |
| High | 8 | CORS allows methods+headers `*`; no body-size cap on JSON endpoints; mock embeddings let any caller derive the deterministic vector; `/v1/auth/login` reveals enumerable users via 404; cross-tenant audit verify missing; HS256 single shared secret with no rotation/revocation; missing role gate on `/v1/oa/*` (paralegal can run analyze); no audit row on error paths. |
| Medium | 11 | No HSTS/CSP/Referrer/X-CTO/X-Frame headers; in-memory rate-limit resets on process restart (free retries); pricing fallback may misreport real cost; `print()` to stderr leaks Ollama errors; sqlite3 `check_same_thread=False` without per-thread connections; redaction regex is greedy but not Unicode-normalized (mixed-script bypass); cache stats include hits/misses but no per-tenant slicing; no input length caps on `oa_text`; uvicorn defaults to `host=0.0.0.0` in `__main__`; Sentry release/env not pinned in CI; postgres + redis docker-compose defaults `patentmind:patentmind`. |
| Low / defer | 7 | No CSRF (pure JWT-in-header is fine); no automated dependency scanning in CI; npm audit not blocking; localStorage theme only (no token); SAST/secret-scan pre-commit not configured; `_USERS` hardcoded (POC); React 18.3 + Vite 5.4 are current. |

**Total: 4 Critical · 8 High · 11 Medium · 7 Low/defer = 30 findings.**

**Single most urgent finding:** `/v1/auth/login` issues a valid JWT for any user_id with **no password / no IdP / no rate limit** (`backend/gateway/main.py:73-93` and `backend/gateway/auth.py:68-82`). Anyone who reaches the gateway can immediately mint `audit_dave`'s token, read the full tenant_a audit chain, and verify-chain it; this is publicly demoable harm during the "下週上線 internal demo" if the gateway port is exposed past localhost.

---

## Critical findings — fix before any non-localhost exposure

### C-1. `/v1/auth/login` issues tokens for any user_id with no credential

**File:** `backend/gateway/main.py:73-93`, `backend/gateway/auth.py:68-82`

```python
@app.post("/v1/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    from backend.gateway.auth import _USERS
    if req.user_id not in _USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {req.user_id} not found")
    user = _USERS[req.user_id]
    return LoginResponse(token=issue_token(req.user_id), ...)
```

**Attack scenario.** Anyone reachable on `:8010` (ngrok demo, LAN, CI runner) sends `POST /v1/auth/login {"user_id":"audit_dave"}` and immediately receives a 30-min JWT scoped to tenant_a with AUDITOR role. They then:
1. GET `/v1/audit/recent` → dump every audit row (case IDs, model usage, redaction rules triggered, policy decisions) for tenant_a.
2. GET `/v1/audit/verify` → confirm chain.
3. Repeat with `alice` to escalate to ATTORNEY and call `/v1/oa/analyze` against `CASE-2025-001..003`.

The `scripts/start_ngrok.sh` helper makes this an extra-high-likelihood scenario for the upcoming demo.

**Fix (effort: 4-6 h).**
- Even in POC mode, require either (a) a shared demo bearer header (`X-Demo-Secret`, value injected from `.env`), or (b) a static per-user password in `_USERS`. The frontend Login.jsx already gates user selection client-side; serverside parity is one extra field + bcrypt compare.
- Add `rate_limit.check_rpm()` to `/v1/auth/login` keyed by client IP (currently the only unauthenticated endpoint, so trivially brute-force-able for user enumeration).
- Differentiate 404 vs 401 on bad credentials (current behavior leaks user enumeration via the 404 message).

---

### C-2. AI Engine on `:8011` has zero authentication on every endpoint

**File:** `backend/ai_engine/main.py:99-239`

None of `/v1/parse_oa`, `/v1/retrieve_prior_art`, `/v1/draft_response`, `/v1/verify_citations`, `/v1/deadline`, `/v1/ai/extract_text`, `/v1/index/patent` uses `Depends(...)` for auth. The service trusts that *only the gateway* will ever talk to it.

**Attack scenarios.**
1. **RAG poisoning across tenants.** `POST /v1/index/patent {"tenant_id":"tenant_a", "patent_no":"FAKE-EVIL-001", "title":"<prompt-injection>...", "claims":[...]}` — the tenant_id is read directly from the request body (`backend/ai_engine/main.py:227`), no check it matches a logged-in user, no check the caller is authenticated. Any attacker on the network silently corrupts `tenant_a`'s RAG corpus, which is then quoted as `[GROUNDED_REF_N]` in attorney drafts.
2. **Confidential-routing bypass.** `POST /v1/parse_oa {"oa_text":"<sensitive>", "tenant_id":"x", "case_id":"FOO-CONF", "security_level":"public"}` — `security_level` is supplied by the *caller* (the orchestrator gateway, normally) and there is no server-side rule that ties it to the case_id suffix. A direct caller can force `public`, sending confidential text to the cloud LLM.
3. **Cost abuse.** Anyone can POST to `/v1/ai/extract_text` and burn the operator's Anthropic budget on arbitrary base64 PDFs.
4. **Cross-tenant retrieval.** `POST /v1/retrieve_prior_art {"tenant_id":"tenant_a", ...}` from a `tenant_b` attacker dumps tenant_a's vector hits (incl. patent text in `RetrievalHit.text`).

The fact that `start_backend.sh` binds the AI Engine to `127.0.0.1` is partial mitigation; however `backend/ai_engine/main.py:244` defaults to `host="0.0.0.0"` in `__main__` and a docker-compose / k8s deploy almost certainly will not preserve loopback isolation.

**Fix (effort: 6-8 h).**
- Add a service-to-service shared secret: gateway → AI Engine sends `X-Internal-Token` (HMAC of timestamp + body, or a long-lived random); AI Engine middleware rejects requests without it. Already half-spec'd in CLAUDE.md as "Phase 2.4 service-account role."
- Bind AI Engine to `127.0.0.1` by default in `__main__` and document the explicit knob to expose it.
- On `/v1/parse_oa`, `/v1/draft_response`, `/v1/ai/extract_text`: re-derive `security_level` from `case_id.upper().endswith("-CONF")` instead of trusting the caller (defense-in-depth — `llm_client.achat` already has the assert at `backend/ai_engine/llm_client.py:558`, but the assert relies on the caller having labelled the call correctly).

---

### C-3. Gateway case-ACL bypass when X-Case-Id header is omitted

**File:** `backend/gateway/auth.py:117-135` (specifically lines 127-131)

```python
case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
if not case_id and request.method == "POST":
    body = getattr(request.state, "_cached_body", None)  # <-- never set
    if body and isinstance(body, dict):
        case_id = body.get("case_id")
authorize_case_access(user, case_id)
```

`request.state._cached_body` is **never written anywhere in the codebase** (`grep _cached_body` returns only this read site). FastAPI's dependency system runs `auth_dependency` BEFORE Pydantic body parsing, so the body is not yet available. As a result, for any JSON POST that *omits* `X-Case-Id` header and `case_id` query param but supplies `case_id` in the body, `authorize_case_access(user, case_id=None)` is called, which is a no-op (`auth.py:104-106`).

**Attack scenario.** Bob (paralegal, tenant_a, ACL = `CASE-2025-001` / `002`) sends:
```
POST /v1/oa/analyze
Authorization: Bearer <bob_token>
{"oa_text":"...", "case_id":"CASE-2025-003", "target_patent_no":"..."}
```
(No X-Case-Id header.) Auth passes. The handler at `main.py:117` uses `body.case_id` for the cache key, orchestration call, and audit row — Bob just analyzed a case he has no ACL for. The audit row even records `policy_decisions["authz_passed"]=True`.

Mitigation in practice: the frontend (`client.js:43`) always sends `X-Case-Id`. A malicious / non-browser client does not have to.

**Fix (effort: 2-3 h).**
- Replace the broken body-reading branch with: explicitly read case_id from request body inside `/v1/oa/analyze`, call `authorize_case_access(user, body.case_id)` again after Pydantic parsing.
- Or: move ACL enforcement out of `auth_dependency` and into a per-route dependency that has the Pydantic body in scope.
- Add an integration test: `POST /v1/oa/analyze` *without* X-Case-Id, with `case_id` in body, for a case outside Bob's ACL → expect 403, not 200.

---

### C-4. JWT_SECRET placeholder runtime guardrail only fires when LLM_MODE != mock

**File:** `backend/shared/config.py:99-108`

```python
if (
    settings.LLM_MODE not in {"mock"}
    and "PYTEST_CURRENT_TEST" not in os.environ
    and settings.JWT_SECRET == _PLACEHOLDER_JWT_SECRET
):
    raise RuntimeError(...)
```

The internal demo (Phase B target) uses `LLM_MODE=mock` for cost reasons — so the guardrail is **disabled** for exactly the deployment everyone will see. The placeholder `changeme-generate-with-openssl-rand-hex-32` is a published string in `.env.example:18`; anyone who has read the public repo can forge tokens for the demo box (no need for C-1 at all — just sign their own JWT with the published secret).

**Attack scenario.** Demo box runs with `LLM_MODE=mock` and unset `JWT_SECRET` env → falls back to the placeholder. Attacker reads `.env.example` on GitHub, signs `{"sub":"audit_dave","tenant_id":"tenant_a","role":"auditor","exp":<long-future>}` with HS256 + the placeholder, and `verify_token` (`auth.py:85-96`) accepts it. Same impact as C-1.

**Fix (effort: 1 h).**
- Tighten the guardrail to refuse the placeholder unconditionally unless `PYTEST_CURRENT_TEST` is set. The mock-mode carve-out is a foot-gun.
- `scripts/start_demo.sh` / `start_backend.sh` should `JWT_SECRET=$(openssl rand -hex 32)` *every* boot when the env var is unset, persisting to a `.jwt_secret.tmp` so a backend restart doesn't invalidate frontend sessions mid-demo.
- Add a `/v1/health` field `auth.jwt_secret_is_placeholder: bool` so the operator dashboard shows red on misconfig.

---

## High findings — fix before pilot launch

### H-1. CORS allows `*` methods and `*` headers from `localhost:5173`

**File:** `backend/gateway/main.py:51-56`

```python
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

While the origin allow-list is tight, the wildcard methods + headers + no `allow_credentials=False` means a future change to add cookie-based auth would silently enable cross-origin credentialed requests. Also: `localhost:5173` will need to change for any non-dev frontend deploy and there is no env-driven override.

**Fix (effort: 1 h).** Read `CORS_ALLOWED_ORIGINS` from env (comma-split); restrict `allow_methods=["GET","POST"]`; explicit `allow_headers=["Authorization","Content-Type","X-Case-Id"]`; `allow_credentials=False`; add `max_age=600`.

---

### H-2. No body-size limit on any JSON endpoint; `oa_text` is unbounded

**File:** `backend/shared/models.py:88-94`, `backend/gateway/main.py:115-208`

`AnalysisRequest.oa_text: str` has no `max_length`. FastAPI/starlette will buffer the full body in memory (the only cap is the OS-level socket / nginx if fronted). The internal `rate_limit.check_request_size(estimated_tokens)` happens *after* the body is parsed (`main.py:147`), so a 1 GB JSON body uses 1 GB RAM before being rejected.

**Attack scenario.** Memory DoS: 50 concurrent 500 MB JSON POSTs → uvicorn worker OOM kill.

**Fix (effort: 2 h).**
- Add a starlette middleware that reads `Content-Length` and 413s when > 50 MB. (Yes, before body parse.)
- Add `Field(..., max_length=1_000_000)` to `AnalysisRequest.oa_text`, `target_patent_no` (`max_length=64`), `case_id` (`max_length=128`), `user_hint` (`max_length=8000`).
- Add `model_config = ConfigDict(extra="forbid")` to AnalysisRequest so a future field rename doesn't silently accept and discard old field names.

---

### H-3. Mock embeddings are deterministic SHA-256; same query → same vector across tenants

**File:** `backend/ai_engine/rag.py:172-179`

```python
h = hashlib.sha256(text.encode()).digest()
raw = list(h) * (settings.EMBEDDING_DIM // len(h) + 1)
vec = np.array(raw[: settings.EMBEDDING_DIM], dtype=np.float32) / 255.0
```

In mock mode (default + demo), embedding(text) is a pure function of the text. An attacker who can call `/v1/retrieve_prior_art` directly (see C-2) can reverse-engineer what's in a tenant's index by submitting candidate query strings and scoring against known SHA-256 → vector mappings. Also: anyone who indexes a known patent into their own tenant gets the same vector as the victim tenant's vector for the same patent, enabling a cross-tenant similarity oracle.

CLAUDE.md §7 pitfall #5 acknowledges this as "masks real RAG quality issues" — this audit adds: it *also* masks a tenant-isolation issue.

**Fix (effort: 2 h).** Add tenant-id salt to mock embedding seed (`hashlib.sha256(f"{tenant_id}:{text}".encode())`). Add a `WARNING: mock embeddings are deterministic` field to `/v1/health`. Document that mock mode is OK for dev only; demos should use bge-m3.

---

### H-4. Cross-tenant audit verify is missing (CLAUDE.md §7 pitfall #4)

**File:** `backend/gateway/audit.py:175-207`

`verify_chain(tenant_id)` walks one tenant. There is no global `verify_all_tenants()` that detects a row whose `tenant_id` was modified after insert (the row_hash includes tenant in the hash payload at line 110-118, so the existing verify *would* catch a tenant flip — but only if the auditor knows to look at the right tenant scope). Crucially: `verify_chain` queries `WHERE tenant_id = ?` then walks rows; an attacker who inserts a row with the *wrong* tenant_id is invisible to per-tenant verify because that row is just filtered out of every tenant's view.

**Attack scenario.** Compromised DBA inserts a fake `tenant_a` row tagged with `tenant_id='tenant_zzz'` to suppress evidence of an alice action. Neither tenant_a's nor tenant_b's verify sees it. The hash chain is invariant within each tenant, but the union of "row exists" is no longer reconcilable.

**Fix (effort: 3-4 h).** Add `verify_global_chain()` that walks all rows in rowid order recomputing the hash, comparing against a separately-persisted Merkle-root anchored hourly to S3 Object Lock. The current implementation has no such anchor — the only tamper detection is *internal consistency*.

---

### H-5. HS256 single shared secret; no key rotation, no revocation list, no jti tracking

**File:** `backend/gateway/auth.py:68-96`, `backend/shared/config.py:25-27`

- HS256 means anyone with `JWT_SECRET` can forge tokens (combine with C-4 above).
- No `iss` / `aud` claims → tokens issued by one PatentMind instance work on any other instance using the same secret.
- No revocation: `_revoked_jti: set[str]` does not exist. A leaked token is good for 30 min with no kill switch.
- `jti` is generated (`auth.py:80`) but never checked / persisted.

**Fix (effort: 4-6 h, P0 before any external pilot).** Migrate to RS256 (asymmetric); add `iss="patentmind-<env>"` and `aud="patentmind-gateway"`; persist revoked jtis in Redis with TTL = remaining token life; add `/v1/auth/logout` that revokes the caller's jti.

---

### H-6. Missing role gate on `/v1/oa/analyze`, `/v1/oa/upload`, `/v1/quota`

**File:** `backend/gateway/main.py:115-382`

These endpoints check authn (JWT valid) and ACL (case in user's allow list) but NOT role. A future `_CASE_ACL[carol] = {"CASE-IT-DASHBOARD-DEMO"}` would let the IT_ADMIN role run patent analysis, contradicting `UserRole.IT_ADMIN`'s documented purpose (`backend/shared/models.py:21`: "管理 connector、看儀表板"). PARALEGAL today is allowed to run `/v1/oa/analyze` directly — `/v1/oa/upload` too (`main.py:213` has no role check). The compat-refactor /v1/audit/append already added a role whitelist (`_AUDIT_APPEND_ROLES = {ATTORNEY, IT_ADMIN, AUDITOR}` in the worktree), so the pattern exists; just apply it consistently.

**Fix (effort: 2 h).**
- Add helper `require_roles(user, {UserRole.ATTORNEY, UserRole.PARALEGAL})` and call from every business endpoint.
- Add `tests/integration/test_role_gates.py` that asserts each endpoint × role matrix.

---

### H-7. Cache hit path writes audit row but error path does not — invariant #4 broken

**File:** `backend/gateway/main.py:115-208`

CLAUDE.md §4 invariant #4: "Every gateway request writes exactly one audit row. Even cache hits. Even errors (TODO)."

The cache-hit path correctly writes (`main.py:158-170`). However:
- `rate_limit.check_rpm` (line 142) raises HTTPException → no audit row.
- `rate_limit.check_quotas` (line 150) raises HTTPException → no audit row.
- `orchestrate_analysis` raise (line 180, e.g. AI Engine 500 / Anthropic error) → no audit row.
- The TODO is acknowledged in CLAUDE.md but unaddressed.

**Attack scenario / compliance gap.** Attacker hammers `/v1/oa/analyze` with 100 RPM, each rejected with 429. **Zero** audit trail of the abuse. An attorney whose Anthropic key was exhausted has zero record of which case they tried to analyze (forensic gap if a malpractice claim later asks "did the AI process this OA?").

**Fix (effort: 3-4 h).** Wrap `analyze_oa` and `upload_oa` in `try / except`, write an audit row with `policy_decisions["error"]=True` + the exception class name (NOT message; messages may contain PII). Add a `tests/integration/test_audit_error_path.py`.

---

### H-8. `/v1/auth/login` user enumeration via 404 vs implicit-OK

**File:** `backend/gateway/main.py:84-85`

```python
if req.user_id not in _USERS:
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {req.user_id} not found")
```

Returns 404 with the user_id echoed for unknown users; 200 + token for known users. An attacker walks a username dictionary, gets back a map of which user_ids exist. Pairs with C-1 (no rate limit) — full enumeration in seconds.

**Fix (effort: 30 min).** Always 401 with a generic message; add RPM throttle keyed by client IP.

---

## Medium findings — fix before GA

### M-1. No HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy

**File:** `backend/gateway/main.py:45-56`

No security headers middleware. Even for an internal pilot, a missing X-Frame-Options means the SPA can be iframed (clickjacking — admin tricked into clicking "revoke audit" via overlay).

**Fix (effort: 1 h).** Add `SecurityHeadersMiddleware`:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (production only — `if not DEBUG`).
- `Content-Security-Policy: default-src 'self'; connect-src 'self' <sentry>; script-src 'self' 'unsafe-inline'` (relax later).
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`

---

### M-2. In-memory rate-limit + quota state resets on process restart

**File:** `backend/gateway/rate_limit.py:41-44`

Module-level dicts. After a uvicorn worker restart (deploy, crash, OOM), an attacker who hit the daily quota or tripped the circuit gets a free reset. Multi-worker uvicorn (`--workers N>1`) further means the per-user state is split N ways → N× quota.

**Fix (effort: 4-6 h, already on the roadmap).** Migrate to the same Redis backend now used for cache (Phase 2A landed). The redis_cache module is a good template.

---

### M-3. Pricing fallback for non-Anthropic models silently misreports cost

**File:** `backend/gateway/rate_limit.py:78-102`

If `LLM_MODE=local` (Ollama) or `LLM_MODE=mock`, `_pricing_for("llama3.1:8b")` falls through to the `(3, 15)` fallback table and reports a fictitious cost in the audit row. The audit shows numbers that look real but aren't. The compliance / cost-tracking dashboard will misallocate budget.

**Fix (effort: 1 h).** Fallback should be `0.0` for non-cloud models with a `cost_provenance: "fallback_estimate"` field in cost_meta so downstream knows not to trust it.

---

### M-4. `print()` to stderr in llm_client may leak Ollama error messages

**File:** `backend/ai_engine/llm_client.py:954-962`

```python
except Exception as e:
    print(f"[llm_client] Ollama call failed, falling back to mock: {e}", file=sys.stderr)
```

The exception message can include the request URL, model name, response body snippet (Ollama returns the failing prompt back in some error modes), or the python traceback if the exception wrapping changes. In a deployment pipeline where stderr is collected to a 3rd-party (Datadog, CloudWatch), this can leak prompt fragments — i.e. redacted-but-still-sensitive OA text.

**Fix (effort: 30 min).** Replace with `logger.warning("Ollama call failed: %s", type(e).__name__)` (class name only, no `%s` of the exception itself).

---

### M-5. sqlite3 `check_same_thread=False` without per-thread connections

**File:** `backend/gateway/audit.py:66`, `backend/gateway/masking.py:109`

Both modules share a single `sqlite3.Connection` across threads, mitigated by a `threading.Lock`. This works for the audit table (every write goes through `self._lock`) but means the SQLite WAL doesn't checkpoint efficiently and a slow audit read on the auditor view blocks every other audit write. For mapping table the same lock is held during regex sub callbacks (`masking.py:166-170`), so a single large OA serialises all redactions across all tenants.

**Fix (effort: 2 h).** Use `sqlite3.connect(..., check_same_thread=False, isolation_level=None)` plus per-thread connections via a `threading.local`. Or migrate audit to Postgres (already on roadmap, Q13 stub).

---

### M-6. Redaction regex is not Unicode-normalized; mixed-script bypass possible

**File:** `backend/gateway/masking.py:39-70`

Email rule: `r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"`. A homoglyph attack (`аlice@аpex-ip.com` with Cyrillic `а` U+0430) bypasses redaction — the `a` is not in `[a-zA-Z]`. Phone `phone_tw` is `\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b` — fullwidth digits `０９` bypass. TW national ID similarly.

**Attack scenario.** Attorney pastes a sanitised OA but a fullwidth phone number escapes redaction and is sent to the cloud LLM. Cannot be reversed.

**Fix (effort: 2-3 h).** `unicodedata.normalize("NFKC", text)` *before* regex matching. Add unit tests for fullwidth digit / homoglyph emails / Hangul digits.

---

### M-7. `oa_text` cache key uses raw user-supplied text (not redacted)

**File:** `backend/gateway/main.py:154`

```python
prompt_hash = cache.hash_prompt(body.oa_text + body.target_patent_no, "orchestrator-v1")
```

The cache key is computed from the raw input. Cache values are JSON responses. Cache key includes `tenant:user:case` so cross-user leakage is prevented (Q9 invariant). But: the cache lookup happens **before** redaction (which is in the orchestrator, line 67). A subtle issue is that if the redaction dictionary changes (a new rule added to `TENANT_DICTIONARIES`), old cached responses may be served for an input that would now redact differently — stale unmask behavior.

**Fix (effort: 1 h).** Include `redaction_version` (e.g. `len(PII_RULES) + len(TENANT_DICTIONARIES[tenant])` hash) in cache key. Document in CLAUDE.md.

---

### M-8. No per-tenant cache size cap; one tenant can starve another

**File:** `backend/gateway/cache.py:29-69` and `backend/gateway/redis_cache.py:56-147`

The memory backend has zero eviction policy; the Redis backend relies on `--maxmemory 256mb --maxmemory-policy allkeys-lru` from docker-compose (`docker-compose.yml:48`) but there's no per-tenant quota. A noisy tenant evicts the quiet tenant's hot keys.

**Fix (effort: 3 h, defer to multi-tenant Redis).** Use Redis key tagging (`{tenant_a}:resp:...`) with `redis.json` per-tenant memory limits.

---

### M-9. uvicorn defaults to `host=0.0.0.0` in both services' `__main__`

**File:** `backend/gateway/main.py:420`, `backend/ai_engine/main.py:244`

`uvicorn.run(..., host="0.0.0.0", ...)`. The shell script `start_backend.sh` explicitly sets `--host 127.0.0.1`, but anyone who runs `python -m backend.gateway.main` (debugger, IDE run config, Dockerfile CMD) gets 0.0.0.0 by default — i.e. exposed on every LAN interface.

**Fix (effort: 10 min).** Default to `127.0.0.1`. Document `LISTEN_HOST=0.0.0.0` override in `.env.example`.

---

### M-10. docker-compose dev defaults: `patentmind:patentmind` postgres password, no Redis auth

**File:** `docker-compose.yml:22-62`

The compose file correctly binds all ports to `127.0.0.1` (comment in line 7-9 even calls out "loopback only — LAN exposure unsafe"). But the docs/.env.example don't loudly warn that anyone with shell on the host can read Postgres. For an internal demo on a shared dev box, the credentials are well-known.

**Fix (effort: 30 min).** Generate compose passwords from `openssl rand -hex 24` at first run; persist to a gitignored `.compose-secrets.env`. Add a `make demo-up` target.

---

### M-11. Sentry release / env not pinned in CI; events from dev show up in prod project

**File:** `backend/shared/observability.py:21-52`, `.env.example:82-92`

`SENTRY_ENVIRONMENT` defaults to `"dev"`. If `SENTRY_DSN` is set but `SENTRY_ENVIRONMENT` is not in CI, errors during pytest get filed against the production Sentry project (if the operator uses one DSN for both). Frontend Sentry has the same issue. Also: a separate DSN for frontend is required per `.env.example:88` comment but no runtime check enforces it.

**Fix (effort: 1 h).** Add a startup check in `observability.init_sentry`: if `SENTRY_ENVIRONMENT == "production"` then `SENTRY_RELEASE` MUST be set, else refuse to init. Document one-DSN-per-environment.

---

## Low / defer

- **L-1.** No CSRF protection — correctly N/A because all endpoints use `Authorization: Bearer` (header is not cross-site auto-sent). If a future switch to cookie auth happens, revisit.
- **L-2.** No automated dependency scanning in CI (`pip-audit`, `npm audit --audit-level=high`). Add to `.github/workflows/ci.yml`.
- **L-3.** `frontend/package.json` has `eslint: ^8.57.1` which is EOL'd — upgrade to v9 in Phase 4 UX work.
- **L-4.** `frontend/src/lib/theme.jsx` is the only localStorage use. JWT lives in React state only (clears on tab close) — fine for POC, document for prod (probably want httpOnly cookie + CSRF).
- **L-5.** No pre-commit secret scanner (gitleaks, trufflehog). `.gitignore` is reasonable.
- **L-6.** `_USERS` and `_CASE_ACL` are hardcoded dicts in `auth.py` — acknowledged POC limitation; Phase 2 swap to Postgres.
- **L-7.** React 18.3 + Vite 5.4 + Pydantic 2.9 are current. No outstanding known-CVE pins.

---

## What's done well — preserve through future refactors

1. **JWT placeholder guardrail at boot** (`config.py:99-108`) — refuses to start in non-mock mode with the placeholder. Just tighten the carve-out (see C-4).
2. **Defense-in-depth on Q15 confidential routing** — `AnthropicLLM.achat` asserts `security_level` at `llm_client.py:556-563`, `vision_ocr` asserts at `llm_client.py:695-700`, public router asserts at `llm_client.py:968-972`. Belt + braces. Same for `/v1/oa/upload` rejecting `-CONF` upload at the edge AND pdf_parser refusing internally.
3. **Vision OCR bytes never persisted to disk** — `pdf_parser.extract_pdf_text` uses `fitz.open(stream=pdf_bytes, ...)` (line 73), all in-memory; audit row records `file_size_bytes` only, never the extracted text (`main.py:343-358`).
4. **Spotlight pattern** — every untrusted user input wrapped in `<untrusted_input>` (oa_analyzer.py:157-159), plus the canary token `PMAI-CANARY-7B3F9C2E` is scrubbed post-call (`llm_client.py:78, 622, 1050`).
5. **Audit hash chain** — `prev_row_hash` linkage (`audit.py:107-152`), append-only triggers (`audit.py:52-58`), per-row SHA-256 over `(audit_id, ts, user, tenant, case, endpoint, req_hash, resp_hash, prev_hash)`. Cross-tenant gap is real (H-4) but per-tenant chain is solid.
6. **Mapping table on-prem only** — `MAPPING_DB_PATH` in `data/` (`config.py:14`), `.gitignored` (line 4 of `.gitignore`).
7. **PII redaction is centralised** — every `masking.redact(...)` call in `orchestrator.py:67` happens before any AI Engine call. No bypass path found in non-AI-Engine code.
8. **Pydantic Field type discipline on the digiRunner Compat Refactor 2** (worktree only) — `AuditAppendRequest` has `model_config = {"protected_namespaces": (), "extra": "forbid"}` + length caps (`worktrees/agent-a1fbb1362539d3caf/backend/gateway/main.py:484-511`). This is the right pattern; extend to all schemas (H-2 fix).
9. **Audit-append ACL re-check** in the worktree — `authorize_case_access(user, req.case_id)` is called explicitly after Pydantic body parse (`worktrees/agent-a1fbb1362539d3caf/backend/gateway/main.py:556`). Pattern that fixes C-3 once landed.
10. **Per-tenant RAG isolation in MemoryVectorStore** — `_tenant_index: dict[tenant_id, set[chunk_id]]` filters before scoring (`rag.py:212-217`). Qdrant path uses `patentmind_{tenant_id}` collections (`rag.py:257-258`).
11. **Tests cover the right invariants** — `tests/integration/test_compat_endpoints.py` already has `test_audit_append_rejects_forgery_with_422`, `test_audit_append_acl_blocks_foreign_case_id`, `test_audit_append_paralegal_role_gated` as load-bearing assertions.
12. **Sentry `send_default_pii=False`** on both backend (`observability.py:43`) and frontend (`sentry.jsx:22`). The lambda `before_send` adds service tag and nothing else.

---

## Hardening sprint plan — 4 parallel chunks suitable for spawning tonight

Each chunk is sized to ~2-4 hours and minimally overlaps the others' file scope.

### Chunk A: "Lock the front door" (Critical C-1, C-2, C-4 + High H-8) — ~4 h
**Scope.** Add credentialed login, internal-only AI Engine, tighten JWT guardrail.
**Files touched.** `backend/gateway/main.py` (login), `backend/gateway/auth.py` (`_USERS` add `password_hash`), `backend/ai_engine/main.py` (add internal-token middleware), `backend/shared/config.py` (`INTERNAL_TOKEN`, JWT guardrail), `.env.example`, `scripts/start_backend.sh` (generate JWT_SECRET + INTERNAL_TOKEN at boot), `tests/integration/test_auth.py` (new).
**Dependencies.** None (atomic).
**Acceptance.** `/v1/auth/login` requires password OR X-Demo-Secret; `/v1/parse_oa` from non-gateway caller returns 401; JWT placeholder refused in all modes.

### Chunk B: "Fix the ACL bypass + audit error path" (Critical C-3 + High H-7) — ~3 h
**Scope.** Make case_id ACL enforcement reliable; write audit row on every exit path including errors.
**Files touched.** `backend/gateway/auth.py` (gut `_cached_body` path), `backend/gateway/main.py` (`/v1/oa/analyze` + `/v1/oa/upload` wrap in try/finally that always writes audit; explicit `authorize_case_access(user, body.case_id)` after Pydantic parse), `tests/integration/test_acl_bypass.py` (new), `tests/integration/test_audit_error_path.py` (new).
**Dependencies.** None — disjoint files from Chunk A's login changes.
**Acceptance.** POST `/v1/oa/analyze` *without* X-Case-Id, with case_id in body for a case outside ACL → 403. Rate-limit-exceeded analyze call → audit row with `policy_decisions.error=True`.

### Chunk C: "Headers, body caps, role gates" (High H-1, H-2, H-6 + Medium M-1, M-9) — ~3 h
**Scope.** Defense-in-depth web hardening.
**Files touched.** `backend/gateway/main.py` (SecurityHeadersMiddleware, CORS env-driven, role checks on `/v1/oa/*`, change `uvicorn.run` default to 127.0.0.1), `backend/ai_engine/main.py` (same uvicorn host change), `backend/shared/models.py` (add `Field(..., max_length=...)` to AnalysisRequest, `extra="forbid"` on every BaseModel), `backend/shared/config.py` (`CORS_ALLOWED_ORIGINS`, `LISTEN_HOST`), `tests/integration/test_role_gates.py` (new), `tests/integration/test_headers.py` (new).
**Dependencies.** None.
**Acceptance.** All security headers present in response of every endpoint. 50 MB body POST returns 413 before parsing. Paralegal POST `/v1/oa/upload` returns 403.

### Chunk D: "Tenant isolation hardening" (High H-3, H-4 + Medium M-3, M-6, M-7, M-8) — ~4 h
**Scope.** Plug remaining cross-tenant + redaction edge cases.
**Files touched.** `backend/ai_engine/rag.py` (salt mock embeddings with tenant_id), `backend/gateway/audit.py` (add `verify_global_chain`, surface in `/v1/audit/verify?scope=global`), `backend/gateway/main.py` (auditor-only flag for global verify), `backend/gateway/masking.py` (NFKC normalize before regex), `backend/gateway/cache.py` (include `redaction_version` in `hash_prompt`), `backend/gateway/rate_limit.py` (cost fallback returns 0 + `cost_provenance` flag), `tests/unit/test_masking_unicode.py` (new), `tests/integration/test_cross_tenant.py` (new).
**Dependencies.** Chunk B should land first (audit writer signature stable). Otherwise disjoint from A and C.
**Acceptance.** Fullwidth phone numbers redacted. Two tenants indexing same patent get distinct vectors. Global audit verify detects a row with a fabricated tenant_id.

---

## References / context

- **CLAUDE.md §4** — the 8 design invariants this audit validates against (lines 71-86 of project root CLAUDE.md). Invariants #3 (redaction mandatory), #4 (audit row on every request), #6 (case_id on every request), #7 (confidential→local) are the ones with active findings above.
- **Compat Refactors (in `.claude/worktrees/`)**:
  - Refactor 2 (`agent-a1fbb1362539d3caf` and ~6 sibling worktrees) adds `/v1/redact` (first-class) and `/v1/audit/append` with `extra="forbid"`, length caps, role gating, and explicit ACL re-check. This branch is the right template for the H-2 / H-6 / C-3 fixes — its test file `tests/integration/test_compat_endpoints.py` already encodes most of the assertions Chunk B and C need.
  - Refactor 3 (claimed "x-user-id / x-tenant-id upstream trust") — grep returns zero matches across all worktrees and main. Either it hasn't landed yet or the branch is named differently; if/when it does land, **DO NOT trust those headers** — treat any upstream-supplied identity claim as untrusted unless signed by a known mTLS peer cert. The pattern is a classic confused-deputy vulnerability.
- **Refactor 1** — appears to be the Redis cache work, which has already merged as `655625e Day 7A`. Code quality of `backend/gateway/redis_cache.py` is good (lazy connect, graceful degradation, no pickle, JSON only) — no findings.
- **OWASP / NIST references for fixes:**
  - C-1, H-5: OWASP ASVS 4.0 V2.10 (Service Authentication), V3.5 (Token-Based Session Management). NIST SP 800-63B 5.1.1 (memorised secrets).
  - C-2: OWASP ASVS V14.4 (HTTP Security Headers — service-to-service). NIST SP 800-204 §4.2 (microservice auth).
  - C-3, H-7: OWASP ASVS V4.1 (General Access Control Design), V7.1.3 (Logging and Monitoring).
  - H-1, M-1: OWASP ASVS V14.4. MDN CSP guide.
  - H-2: OWASP API Security Top 10 2023 — API4 (Unrestricted Resource Consumption).
  - H-3, H-4, D-4: OWASP API Top 10 — API5 (Broken Function Level Authorization), Cloud Security Alliance "Multi-Tenancy Patterns".
  - M-6: Unicode TR #36 (Security Considerations).

---

*End of audit. Spawn the 4 chunks in parallel tonight; Chunks A and B are blockers for any external demo. Chunks C and D bring the system to pilot-ready.*
