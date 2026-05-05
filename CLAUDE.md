# CLAUDE.md — handoff to Claude Code

> 這份是給 Claude Code agent 看的接手文件。讀完這份就能繼續開發。
> 人類請看 `README.md`。

## 1. Repo overview (ground truth in 30 seconds)

```
patentmind-poc/
├── README.md             — overview for humans
├── docs/
│   ├── DECISIONS.md      — 20 reasoning Q&A 的最終決策表 (READ FIRST)
│   ├── QUESTIONS.md      — 20 題的詳細選項分析
│   └── ARCHITECTURE.md   — 每個 Q 對應到哪份 code (READ SECOND)
├── backend/
│   ├── shared/           — Pydantic models + Settings
│   ├── gateway/          — FastAPI port :8000  (digiRunner mock, 厚 Gateway, Q1)
│   │   ├── auth.py       — Q12 JWT + case ACL
│   │   ├── rate_limit.py — Q18 RPM + quota + cost circuit breaker
│   │   ├── masking.py    — Q10 PII + customer dictionary, reversible
│   │   ├── audit.py      — Q13 append-only SQLite + hash chain
│   │   ├── cache.py      — Q9 in-memory, key=tenant:user:case:hash
│   │   ├── orchestrator.py — Q1+FU 厚 Gateway 流程
│   │   └── main.py       — FastAPI wire-up
│   ├── ai_engine/        — FastAPI port :8001  (Dify mock, single-step inference)
│   │   ├── llm_client.py — Q15 multi-model router + Q11 canary + Q18 degrade
│   │   ├── rag.py        — Q6 hierarchical+claim-tree chunking, Q7 Qdrant-shape store
│   │   ├── oa_analyzer.py— Q11 spotlight, Q14 grounded citations + verifier
│   │   ├── deadline.py   — Q17 multi-jurisdiction + holiday roll-forward
│   │   └── main.py
│   └── patent_db/seed.py — demo patents
├── frontend/             — Q4 product SPA (Vite + React)
│   ├── src/App.jsx
│   ├── src/api/client.js
│   └── src/components/
│       ├── Login.jsx
│       ├── Analyze.jsx       — main analysis view
│       ├── DraftEditor.jsx   — Q16 line-level provenance UI
│       └── AuditView.jsx     — Q13 audit + chain verify
├── data/
│   ├── oa_samples/sample_oa_us.txt
│   └── (audit.db, redaction_mapping.db generated at runtime — gitignored)
└── scripts/
    ├── start_backend.sh
    └── verify.sh             — runs full e2e
```

## 2. How to run (verify nothing broke)

```bash
# Terminal 1 — backend
bash scripts/start_backend.sh

# Terminal 2 — verify
bash scripts/verify.sh   # should print ALL CHECKS PASSED

# Terminal 3 — frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

If `verify.sh` doesn't pass, **stop and fix that first** before adding features.
The 20 architectural decisions are baked into that test; if it goes red, an
invariant has broken.

## 3. What's stubbed (your job to harden)

Every stub is grep-able. Search for `TODO(claude-code)` to find them.

| Q  | What's stubbed | What real impl needs |
|----|----------------|----------------------|
| Q2 | Mock `_mock_*` fns in `llm_client.py` | Replace with real Dify workflow webhook |
| Q3 | Hybrid is conceptual; everything is local | Add explicit cloud egress check before LLM call |
| Q4 | No SSR landing page | Build separate Next.js app (out of POC repo) |
| Q5 | One Qdrant memory store | Per-tenant collections + RBAC |
| Q7 | numpy in-memory vector store | Qdrant container + `VECTOR_BACKEND=qdrant` |
| Q8 | OCR/Vision stubs in `oa_analyzer.py` | Tesseract for OCR, Claude Vision for figures |
| Q9 | In-memory cache | Redis with EVAL atomic ops |
| Q10 | Demo dictionaries hard-coded | Per-tenant uploadable JSON dictionary |
| Q12 | Only built-in JWT login | Add `/auth/oidc/callback`, `/auth/saml/acs`, `/auth/magic` |
| Q13 | SQLite local audit only | Add S3 Object Lock hourly archiver |
| Q14 | Verifier is mock | Real cheap-model call (Haiku / GPT-4o-mini) |
| Q15 | Local model = mock | Wire vLLM + on-prem Llama-3.1-70B |
| Q17 | Holidays hard-coded for 2025 | Cron job: pull from `data.gov.tw` + USPTO calendar |
| Q19 | JSON logs only | Wire Prometheus + Grafana dashboards |
| Q20 | Daily backup未實作 | Cron `pg_dump` + `aws s3 cp`; **must upgrade to streaming replication before prod** |

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
- [ ] Real Anthropic / OpenAI client in `llm_client.py` (set `LLM_MODE=anthropic`)
- [ ] Replace SQLite audit with Postgres + S3 Object Lock archive
- [ ] Replace in-memory cache with Redis (`CACHE_BACKEND=redis`)
- [ ] Replace numpy vector store with Qdrant (`VECTOR_BACKEND=qdrant`)
- [ ] Real PDF/DOCX OA upload (currently text only)
- [ ] OIDC integration (Keycloak in docker-compose)

### P1 — feature gaps
- [ ] Q8 vision LLM for OA figures
- [ ] Q14 actually call a different verifier model (right now mock returns canned)
- [ ] Q17 hook holiday API (`https://data.taipei` for TW, USPTO API for US)
- [ ] Q19 Prometheus metrics endpoints + Grafana dashboard JSONs
- [ ] Q19 AI quality eval pipeline (週/月律師抽樣評分)
- [ ] Q20 cron-based backup script + restore drill doc

### P2 — UX / polish
- [ ] Frontend: PDF preview pane with figure callouts
- [ ] Frontend: dark mode (token bar uses CSS vars already)
- [ ] Frontend: i18n (zh-TW + en); copy currently bilingual zh/en
- [ ] Frontend: drag-and-drop OA upload
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
│                  Gateway :8000  (digiRunner mock)                │
│ ┌────────┐ ┌──────────┐ ┌─────────┐ ┌───────┐ ┌──────┐ ┌──────┐ │
│ │  Auth  │→│RateLimit │→│ Mask    │→│Cache  │→│Orch. │→│Audit │ │
│ │ Q12    │ │  Q18     │ │ Q10/Q3  │ │ Q9    │ │Q1+FU │ │ Q13  │ │
│ └────────┘ └──────────┘ └─────────┘ └───────┘ └──────┘ └──────┘ │
└───────────────────────┬─────────────────────────────────────────┘
                        │ HTTP (intra-vpc)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                AI Engine :8001  (Dify mock)                      │
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
│ Vector store Q7  │       │  LLM (mock)  │
│ Qdrant per tenant│       │ Q15 routed   │
└──────────────────┘       └──────────────┘
```

## 7. Pitfalls / gotchas

1. **PyJWT 2.7 conflict on Debian 12** — install fix is `pip install --break-system-packages PyJWT`. Already in `start_backend.sh`.
2. **Vite proxy** — frontend uses `/api` prefix, vite proxies to `:8000`. Don't hardcode port in `client.js`.
3. **The `Tailwind via CDN` shortcut** — POC speed. Production should compile via PostCSS for tree-shaking.
4. **Audit chain is per-tenant** — verifier walks one tenant at a time. Cross-tenant verification needs a separate function.
5. **Mock embeddings are deterministic via SHA-256** — same query → same retrieval. This makes demo reproducible but masks real RAG quality issues. Replace before demo to prospects.

## 8. How to extend each layer

**Add a new mask rule:** `backend/gateway/masking.py` → `PII_RULES` or `TENANT_DICTIONARIES[tenant_id]`. Restart gateway.

**Add a new jurisdiction:** `backend/ai_engine/deadline.py` → add `RULES["JP"]` and `HOLIDAYS[("JP", "2025.1")]`. Add to `SUPPORTED_JURISDICTIONS` in config.

**Add a new LLM intent:** `backend/ai_engine/llm_client.py` → add to `route_model()` and `MockLLM._respond()`. Add system prompt in `oa_analyzer.py`.

**Add a new role:** `backend/gateway/auth.py` → `UserRole` enum + `_USERS` map. Add role check in endpoint.

**Add a new policy gate:** `backend/gateway/main.py` → before `orchestrate_analysis(...)` call. Record decision in `policy_decisions` dict.

## 9. Don't do this

- **Don't put case_id-bearing data in URL paths.** Always headers or body. Logs and proxies leak URLs.
- **Don't add an endpoint that bypasses redaction.** If a path takes user-supplied text and forwards to AI Engine, redaction is required.
- **Don't skip the verifier.** Even for "trusted" prompts. The verifier is also a defence against prompt injection escaping `<untrusted_input>`.
- **Don't cache responses cross-user.** The cache key includes user_id for a reason (Q9). One client's answer is privileged from another's.
- **Don't store mapping table outside on-prem.** `MAPPING_DB_PATH` lives in `data/` for a reason (Q3).
