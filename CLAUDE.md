# CLAUDE.md — handoff to Claude Code

> 這份是給 Claude Code agent 看的接手文件。讀完這份就能繼續開發。
> 人類請看 `README.md`。

## 1. Repo overview (ground truth in 30 seconds)

```
patentmind-poc/
├── README.md / README.zh-TW.md — overview for humans
├── HANDOFF.md            — session-by-session 開發史 (Day 1–14, 含 Day 14 實機交付)
├── docs/
│   ├── DECISIONS.md      — 20 reasoning Q&A 的最終決策表 (READ FIRST)
│   ├── QUESTIONS.md      — 20 題的詳細選項分析
│   ├── ARCHITECTURE.md   — 每個 Q 對應到哪份 code (READ SECOND)
│   ├── DELIVERY_RUNBOOK.md — 真 digiRunner + Dify 全 stack 起停手冊（雙語）
│   ├── PHASE3_MIGRATION.md — digiRunner/Dify 落地計畫
│   ├── observability/    — Q19 /metrics 說明 + Grafana wiring
│   └── (另有 SECURITY_AUDIT / UX / market / legal 等研究文件 ~15 份)
├── backend/
│   ├── shared/           — models.py + config.py (所有 env knobs)
│   │                       + metrics.py (Q19 Prometheus) + observability.py (Sentry)
│   ├── gateway/          — FastAPI :8010  (厚 Gateway, Q1; 可由真 digiRunner :18080 前置)
│   │   ├── auth.py       — Q12 JWT + case ACL + upstream-header auth (digiRunner)
│   │   ├── rate_limit.py — Q18 RPM + quota + cost circuit breaker (memory | redis)
│   │   ├── masking.py    — Q10 PII + per-tenant uploadable dict (data/tenant_dicts/)
│   │   ├── audit.py      — Q13 append-only SQLite + hash chain (+ global verify)
│   │   ├── audit_archive.py / audit_outbox.py — Q13 WORM 封存 + write-ahead outbox
│   │   ├── cache.py / redis_cache.py — Q9 CACHE_BACKEND=memory | redis
│   │   ├── revocation.py — H-5 JWT jti 撤銷 (memory | redis)
│   │   ├── signoff.py    — Q16 sign-off / provenance / export-gate helpers
│   │   ├── backup.py     — Q20 snapshot / restore / DR drill / GDPR erasure
│   │   ├── quality_eval.py — Q19 attorney-acceptance 品質報告
│   │   ├── orchestrator.py — Q1+FU 厚 Gateway 流程
│   │   └── main.py       — FastAPI wire-up (+ /auth/{oidc,saml,magic}/*, /metrics)
│   ├── ai_engine/        — FastAPI :8011  (single-step inference)
│   │   ├── llm_client.py — Q15 router: mock | anthropic | local(Ollama) | dify; Q11 canary
│   │   ├── rag.py        — Q6 chunking; Q7 VECTOR_BACKEND=memory|qdrant (per-tenant
│   │   │                   collections); EMBEDDING_BACKEND=mock|bge-m3
│   │   ├── oa_analyzer.py— Q11 spotlight, Q14 grounded citations + verifier
│   │   ├── pdf_parser.py / ocr_local.py — Q8 PDF/DOCX 萃取 + Tesseract 地端 OCR
│   │   ├── claim_tree.py / element_table.py — claim 結構解析
│   │   ├── injection_guard.py — prompt-injection 偵測
│   │   ├── prompt_loader.py + prompts/*.yaml — prompts 外部化 (Dify DSL 的 single source)
│   │   ├── deadline.py   — Q17 multi-jurisdiction; 假日表載入 data/calendars/*.json
│   │   ├── retrieval_eval.py — RAG 檢索評測
│   │   └── main.py
│   ├── minimal/main.py   — 單 process 精簡版 (scripts/start_minimal.sh)
│   └── patent_db/seed.py — demo patents
├── frontend/             — Q4 product SPA (Vite + React + Tailwind build + i18n + dark mode)
│   ├── src/api/          — client.js + queries.js (TanStack Query)
│   ├── src/lib/          — i18n / theme / toast / sentry / utils
│   └── src/components/   — AppShell (trust band), Login, Analyze (3-pane → analyze/*),
│                           DraftEditor (Q16), AuditView (Q13), OAUpload (drag-drop PDF),
│                           StackStatus (digiRunner/Dify 四燈), ui/
├── data/
│   ├── oa_samples/       — sample_oa_{us,tw,cn,ep,kr}.txt + pdf/
│   ├── cases/            — 80 個合成案例 (CASE-DEMO-001..080)
│   ├── calendars/        — Q17 versioned holiday JSONs (TW/US/JP/CN/EP/KR)
│   ├── tenant_dicts/     — Q10 per-tenant mask dictionaries
│   └── (audit.db, redaction_mapping.db, backups/ generated at runtime — gitignored)
├── dify_workflows/ + digirunner/ — Phase 3 artefacts (workflow DSL, route/oidc/model templates)
├── presentation/         — 簡報產生器 + 17 張 render
└── scripts/              — start/smoke/setup/eval scripts — see §2
```

## 2. How to run (verify nothing broke)

```bash
# 最常用 — 一鍵 demo (ai_engine :8011 + gateway :8010 + vite :5173；mock LLM，
# 首次啟動自動產 secrets；偵測到 ANTHROPIC_API_KEY 自動切 LLM_MODE=anthropic)
bash scripts/start_demo.sh

# 交付版全 stack — docker infra (qdrant :6333 / redis :6379 / postgres :15432)
# + 上面三個 process；另 probe digiRunner :18080 與 Dify :8088（不擋啟動）。
# LLM_MODE=dify 走真模型 (Dify CE → Ollama qwen2.5:7b)。
bash scripts/start_delivery.sh

# 驗證（另開 terminal）
bash scripts/verify.sh            # e2e invariants — should print ALL CHECKS PASSED
bash scripts/smoke_demo.sh        # health → login → analyze → upload happy path
bash scripts/smoke_digirunner.sh  # 經 digiRunner :18080 的全鏈路（需先 start_digirunner.sh）
bash scripts/smoke_dify.sh        # LLM_MODE=dify 真模型路徑（需 Dify up + setup_dify.py + Ollama）

# 個別啟動（仍可用）
bash scripts/start_backend.sh               # 只起兩個 backend service
cd frontend && npm install && npm run dev   # http://localhost:5173

# 測試 suites（2026-06-11 基準：pytest 1232 passed / 2 skipped；Playwright 73 passed）
python -m pytest
cd frontend && npx playwright test
```

If `verify.sh` doesn't pass, **stop and fix that first** before adding features.
The 20 architectural decisions are baked into that test; if it goes red, an
invariant has broken.

## 3. Hardening status (Day 8–14 sprints implemented most of the original stubs)

### 3a. Done — implemented + tested (env knob that enables each)

| Q  | What landed | How to enable / where |
|----|-------------|------------------------|
| Q2 | Real Dify CE workflow (`DifyLLM`; parse_oa + draft_response 走 Dify → Ollama qwen2.5:7b；verifier 留本地當 Q14 硬牆) | `LLM_MODE=dify` + `python scripts/setup_dify.py` |
| Q3 | Cloud-egress 顯式聲明：anthropic 模式有 egress guard；Dify hop 在地性由 knob 宣告，false 時 `-CONF` 硬拒 | `DIFY_EGRESS_LOCAL` (`backend/shared/config.py`) |
| Q5 | Per-tenant Qdrant collections + tenant-salted mock/lexical embeddings (H-3) | `VECTOR_BACKEND=qdrant`（`rag.py` `_coll(tenant_id)`） |
| Q7 | Real Qdrant store（docker-compose 容器；空批次 upsert bug 已修） | `VECTOR_BACKEND=qdrant` |
| Q8 | PDF/DOCX 上傳 + 萃取（`pdf_parser.py` PyMuPDF）+ Tesseract 地端 OCR（`ocr_local.py`，機密案不離機）+ Claude Vision OCR fallback | `/v1/oa/upload`；Tesseract 為 optional dep |
| Q9 | Redis cache（graceful degradation；JSON 序列化） | `CACHE_BACKEND=redis`（另有 `RATE_LIMIT_BACKEND` / `REVOCATION_BACKEND=redis`） |
| Q10 | Per-tenant uploadable JSON dictionary（file drop + reload，不用重啟） | `data/tenant_dicts/<tenant_id>.json` + `reload_tenant_dictionary()` |
| Q12 | `/auth/oidc/begin` + `/auth/oidc/callback`、`/auth/saml/acs`、`/auth/magic/request` + `/consume` + JWT 撤銷（`revocation.py`）。OIDC 可走**真 Keycloak**（discovery + code→token + JWKS 驗章 + role/tenant claim 映射，`backend/gateway/oidc_keycloak.py`；realm 匯入檔 `keycloak/realm-patentmind.json`，compose 服務 :8081） | `OIDC_MODE=stub\|keycloak`；smoke: `bash scripts/smoke_keycloak.sh` |
| Q13 | WORM archiver（`audit_archive.py`：sealed segments + Merkle root chain，本地 Object-Lock 語意）+ write-ahead outbox（`audit_outbox.py`，invariant #4 backstop） | 自動；驗證走 `verify_archive` |
| Q14 | Verifier 是獨立第二 model call（`assert_verifier_independence()`；anthropic 模式 = Haiku） | `LLM_MODEL_VERIFIER`（必 ≠ REASONING） |
| Q15 | 真地端 LLM：Ollama OpenAI-compat endpoint | `LLM_MODE=local` + `LLM_MODEL_LOCAL`（這台機器用 `qwen2.5:7b`，**無** llama3.1:8b） |
| Q17 | Holiday producer（`scripts/fetch_holidays.py`：TW data.gov.tw / US 法定規則 / JP 内閣府）+ versioned `data/calendars/*.json`；deadline.py 讀檔，硬編表僅 fallback | `HOLIDAY_SOURCE=bundled|jsonfile|remote` |
| Q19 | Prometheus `/metrics`（gateway + ai_engine，text exposition v0.0.4，`backend/shared/metrics.py`）+ 品質報告 pipeline（`quality_eval.py`）+ eval harness（`scripts/eval_cases.py` / `eval_compare.py`） | `docs/observability/README.md` |
| Q20 | `backup.py`：snapshot / restore / **DR drill**（restore 後驗 audit chain）/ GDPR erasure | `BACKUP_DIR`、`BACKUP_RETENTION_KEEP` |

### 3b. Still stubbed (your job to harden)

程式碼裡剩餘的 `TODO(claude-code)` 只有一處（`pdf_parser.py:476`）；其他項目是架構層缺口。
（`docs/ARCHITECTURE.md` 內的 TODO 標記是早期敘述，多數已實作 — 對照本表為準。）

| What's stubbed | What real impl needs |
|----------------|----------------------|
| Q4 — No SSR landing page | Build separate Next.js app (out of POC repo) |
| Q8 — Vision figure-region extraction returns `[]` | `pdf_parser.py:476` TODO — real figure callout extraction |
| Q12 — SAML IdP 是 stub（OIDC 已接真 Keycloak ✅，`OIDC_MODE=keycloak`） | SAML 換 python3-saml + 真 ADFS/Azure AD；OIDC 換企業級 IdP 只需改 issuer/client（`digirunner/oidc.yaml` 模板已對齊 realm `patentmind`） |
| Q13 — WORM 封存目標是本地唯讀目錄 | 換成真 S3 Object Lock / Azure Immutable Blob bucket |
| Audit DB 仍是 SQLite | Postgres 容器已在 compose（:15432）但 audit 未遷移 |
| Q19 — Grafana dashboard JSONs 未出 | `docs/observability/README.md` 只有 wiring 說明 |
| Q20 — cron 排程未接 | `backup.py` 是 cron job 的 body；**must upgrade to streaming replication before prod** |

## 4. Design invariants — never violate these

1. **Gateway never directly calls an LLM.** All LLM calls go via `ai_engine`. (Q1 + FU)
2. **AI Engine holds no business state.** No DB writes from `ai_engine/` except RAG vectors. (Q1 + FU)
3. **Redaction is mandatory before any LLM call.** Search `masking.redact(` — it must wrap any text that originates from user/OA before going to AI Engine. (Q3 + Q10)
4. **Every gateway request writes exactly one audit row.** Even cache hits. Even errors (TODO). (Q13)
5. **Citations in drafts MUST come from the grounded set.** `verify_citations` is the hard wall. (Q14)
6. **`case_id` is checked on every request.** No way to bypass. (Q12)
7. **Confidential cases auto-route to local LLM.** Search `LOCAL_LLM_FOR_SECURITY_LEVELS`. (Q15)
8. **Token quota check happens BEFORE the LLM call.** Cost circuit breaker checked second. (Q18)

## 5. Suggested next features (priority order)

### P0 — production readiness
- [x] ✅ Real Anthropic client in `llm_client.py` (`LLM_MODE=anthropic`; Dify/Ollama path via `LLM_MODE=dify` / `local`)
- [ ] Replace SQLite audit with Postgres + **real** S3 Object Lock target（本地 WORM archiver 已做 ✅，見 §3a Q13）
- [x] ✅ Redis cache (`CACHE_BACKEND=redis`)
- [x] ✅ Qdrant vector store (`VECTOR_BACKEND=qdrant`)
- [x] ✅ Real PDF/DOCX OA upload（`/v1/oa/upload` + PyMuPDF + Tesseract/Vision OCR）
- [x] ✅ Real IdP integration（Keycloak）— `OIDC_MODE=keycloak`：discovery + code→token + JWKS 驗章 + role/tenant 映射，gateway 簽自己的 session JWT（`backend/gateway/oidc_keycloak.py`；`docker compose up -d keycloak` 自動匯入 realm；smoke `scripts/smoke_keycloak.sh`）。SAML 仍是 stub；Azure AD 對接留 ops

### P1 — feature gaps
- [ ] Q8 vision LLM for OA **figures**（`pdf_parser.py:476` TODO；OCR 部分已完成）
- [x] ✅ Q14 independent verifier model（`assert_verifier_independence`；anthropic 模式走 Haiku）
- [x] ✅ Q17 holiday fetcher（`scripts/fetch_holidays.py` + `data/calendars/`，`HOLIDAY_SOURCE=remote`）
- [ ] Q19 Grafana dashboard JSONs — Prometheus `/metrics` 已上 ✅（兩個 service），差 dashboards
- [x] ✅ Q19 AI quality eval pipeline（`quality_eval.py` + `scripts/eval_cases.py` / `eval_compare.py`）
- [x] ✅ Q20 backup + restore drill（`backup.py`，含 DR drill）— cron 排程留給 ops

### P2 — UX / polish
- [x] ✅ Frontend: PDF preview pane（`OAUpload.jsx` `<embed>`）— figure callouts 部分仍缺（綁 Q8 P1）
- [x] ✅ Frontend: dark mode（ThemeProvider, localStorage-backed）
- [x] ✅ Frontend: i18n（react-i18next, zh-TW default + en）
- [x] ✅ Frontend: drag-and-drop OA upload（`OAUpload.jsx`）
- [ ] Backend: rate limit middleware (right now scattered in handlers)

## 6. Architecture diagrams

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Vite SPA)                      │
│  Login → Analyze → AuditView    (React 18 + Tailwind via CDN)   │
└───────────────────────┬─────────────────────────────────────────┘
                        │ /api/* (vite proxy)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Gateway :8010  (thick gateway)                  │
│ ┌────────┐ ┌──────────┐ ┌─────────┐ ┌───────┐ ┌──────┐ ┌──────┐ │
│ │  Auth  │→│RateLimit │→│ Mask    │→│Cache  │→│Orch. │→│Audit │ │
│ │ Q12    │ │  Q18     │ │ Q10/Q3  │ │ Q9    │ │Q1+FU │ │ Q13  │ │
│ └────────┘ └──────────┘ └─────────┘ └───────┘ └──────┘ └──────┘ │
└───────────────────────┬─────────────────────────────────────────┘
                        │ HTTP (intra-vpc)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                AI Engine :8011  (inference)                      │
│ ┌────────────┐ ┌─────────┐ ┌────────────┐ ┌──────────────┐      │
│ │ parse_oa   │ │retrieval│ │draft_resp  │ │verify_cite   │      │
│ │ Q11        │ │Q6/Q7    │ │Q14/Q15     │ │Q14           │      │
│ └────────────┘ └─────────┘ └────────────┘ └──────────────┘      │
│       │              │           │                 │             │
│       ▼              ▼           ▼                 ▼             │
│  ┌─────────────────────────────────────────────────────┐         │
│  │  llm_client.py  (Q15 router + Q11 canary)           │         │
│  └─────────────────────────────────────────────────────┘         │
└──────────────────┬──────────────────────────────────────────────┘
                   │
        ┌──────────┴──────────────┐
        ▼                         ▼
┌──────────────────┐       ┌──────────────┐
│ Vector store Q7  │       │ LLM backends │
│ Qdrant per tenant│       │ Q15 routed   │
└──────────────────┘       └──────────────┘
```

**Live delivery chain（2026-06-11 實機驗證，全綠）：**
SPA :5173 → digiRunner OSS :18080 (`/dgrc`) → gateway :8010 → ai_engine :8011
→ Dify CE :8088 → Ollama `qwen2.5:7b`。全鏈路 analyze 約 25–28s。
LLM 後端由 `LLM_MODE` 路由：`mock | anthropic | local(Ollama) | dify`。

## 7. Pitfalls / gotchas

1. **PyJWT 2.7 conflict on Debian 12** — install fix is `pip install --break-system-packages PyJWT`. Already in `start_backend.sh`.
2. **Vite proxy** — frontend uses `/api` prefix, vite proxies to `:8010` (gateway; ai_engine is :8011). Don't hardcode port in `client.js`.
3. **The `Tailwind via CDN` shortcut** — POC speed. Production should compile via PostCSS for tree-shaking.
4. **Audit chain is per-tenant** — verifier walks one tenant at a time. Cross-tenant verification needs a separate function.
5. **Mock embeddings are deterministic via tenant-salted SHA-256** — same tenant + same query → same retrieval（H-3 修復後跨 tenant 不再同向量）。Demo 可重現，但會遮蔽真實 RAG 品質問題。要看真檢索品質用 `EMBEDDING_BACKEND=bge-m3`（sentence-transformers BGE-M3，多語言）。

## 8. How to extend each layer

**Add a new mask rule:** `backend/gateway/masking.py` → `PII_RULES` or `TENANT_DICTIONARIES[tenant_id]`. Restart gateway.

**Add a new jurisdiction:** `backend/ai_engine/deadline.py` → add `RULES["XX"]`，假日表放 `data/calendars/XX_<version>.json`（用 `scripts/fetch_holidays.py` 產生，或手寫同 schema；`_FALLBACK_HOLIDAYS` 只是 safety net）。Add to `SUPPORTED_JURISDICTIONS` in config（目前 TW/US/JP/EP/CN/KR）。

**Add a new LLM intent:** `backend/ai_engine/llm_client.py` → add to `route_model()` and `MockLLM._respond()`. Add system prompt in `oa_analyzer.py`.

**Add a new role:** `backend/gateway/auth.py` → `UserRole` enum + `_USERS` map. Add role check in endpoint.

**Add a new policy gate:** `backend/gateway/main.py` → before `orchestrate_analysis(...)` call. Record decision in `policy_decisions` dict.

## 9. Don't do this

- **Don't put case_id-bearing data in URL paths.** Always headers or body. Logs and proxies leak URLs.
- **Don't add an endpoint that bypasses redaction.** If a path takes user-supplied text and forwards to AI Engine, redaction is required.
- **Don't skip the verifier.** Even for "trusted" prompts. The verifier is also a defence against prompt injection escaping `<untrusted_input>`.
- **Don't cache responses cross-user.** The cache key includes user_id for a reason (Q9). One client's answer is privileged from another's.
- **Don't store mapping table outside on-prem.** `MAPPING_DB_PATH` lives in `data/` for a reason (Q3).
