# PatentMind AI — Build vs Buy vs Partner Decision Matrix

> Audience: CTO / founding eng. Decisions in this doc dictate where engineering hours go (vs. cheque-writing) and where lock-in risk lives. Every line of `backend/shared/config.py` ends up here.
> Convention: "NOW" = Phase 1 (POC + first 3 customers, ~6 months). "LATER" = Phase 3 (20+ customers, ≥1 tier-1 firm under contract, ~18-30 months). Lock-in score: 0 = swap in a sprint, 10 = swap is a strategic project.
> Companion docs: [DECISIONS.md](./DECISIONS.md) (the 20 Qs), [PHASE3_MIGRATION.md](./PHASE3_MIGRATION.md) (digiRunner+Dify landing plan), [PRODUCT_STRATEGY.md](./PRODUCT_STRATEGY.md) (pricing benchmark).

---

## Master comparison table

| # | Component | Q-link | Current state | NOW recommendation | LATER recommendation | Lock-in | Notes |
|---|---|---|---|---|---|---|---|
| 1 | LLM provider | Q15 | `LLM_MODE=mock`/`anthropic` via `llm_client.py` Q15 router | **Anthropic** (Sonnet 4.6 reason, Haiku 4.5 verifier) + **Ollama** local for confidential | **Anthropic + on-prem vLLM Llama 3.3 70B** for confidential; OpenAI as commercial fallback | 4 | router abstracts swap; prompt-shape lock-in is the real risk |
| 2 | Local-LLM hosting | Q15 | `OLLAMA_BASE_URL` Ollama path stubbed | **Ollama** (single-node, dev simplicity) | **vLLM** behind LiteLLM router on a 1×H100 or 2×A100 box | 3 | both OpenAI-compatible; swap is a config flip |
| 3 | Embeddings | Q7 | `EMBEDDING_BACKEND=bge-m3` default; mock fallback | **BAAI bge-m3 self-host** | **bge-m3 self-host** + Voyage AI for English-heavy US OAs | 2 | re-embedding a corpus is the real cost — ~1-2 days at 1M chunks |
| 4 | Vector DB | Q5,Q7 | `VECTOR_BACKEND=memory` (numpy); Qdrant target | **Qdrant self-host (Docker)** | **Qdrant Hybrid Cloud** OR scaled self-host on K8s | 5 | filter-payload API is portable; collection per tenant is a Qdrant idiom |
| 5 | Cache | Q9 | `CACHE_BACKEND=memory`; Redis target | **In-memory** (POC), **Redis OSS 7.2** for HA | **Valkey** (open BSD fork; no SSPL trap) | 2 | Redis SSPL/AGPL relicense is the LATER trigger |
| 6 | Audit storage | Q13 | `AUDIT_BACKEND=sqlite` `audit.db` hash chain | **SQLite** (POC), **Postgres** for first paying customer | **Postgres + S3 Object Lock archive** | 7 | hash chain shape couples to schema; migration needs replay |
| 7 | Audit archival | Q13 | None (CLAUDE.md §3 TODO) | **None** (SQLite local) | **AWS S3 Object Lock Compliance Mode** + GCS for second region | 3 | hourly archiver is a cron job |
| 8 | API gateway | Q1 | hand-rolled `gateway/main.py` (digiRunner mock) | **digiRunner Enterprise Standalone** (partner) | **digiRunner HA** + Kong OSS as edge ingress | 8 | partner play, see TPIsoftware section |
| 9 | Workflow orchestration | Q1,Q2 | `orchestrator.py` 6-step DAG (Dify mock) | **Native Python orchestrator** (POC) | **Dify 1.6+ self-host** (partner) for non-eng prompt iteration | 6 | DSL shape lock-in moderate; HTTP nodes portable |
| 10 | Identity / SSO | Q12 | JWT `_USERS` dict + upstream-header path | **digiRunner OIDC → built-in IdP** OR **Keycloak self-host** | **Keycloak HA** in front of firm IdP (Entra/Okta) federation | 3 | upstream-header abstraction means swaps are invisible to backend |
| 11 | OCR | Q8 | Tesseract stub | **Tesseract** + Claude Vision fallback | **Azure Document Intelligence** for scanned legal docs + Tesseract on-prem for confidential | 4 | per-page pricing; quality cliff for scanned patents |
| 12 | PDF text extraction | Q8 | `pdf_parser.py` (likely pdfplumber) | **PyMuPDF** | **PyMuPDF** + **Marker** (GPU) for complex layouts | 1 | trivial swap, library API similar |
| 13 | Frontend hosting | Q4 | Vite SPA on dev nginx | **On-prem nginx** behind digiRunner | **On-prem nginx** (firm clients refuse SaaS edge) + **Cloudflare Pages** for marketing site | 1 | static assets, fully portable |
| 14 | Observability | Q19 | JSON logs + stubs | **Sentry Team** ($29/mo) + Prometheus self-host | **Prometheus + Grafana + Loki** self-host; Sentry stays | 3 | OpenTelemetry exporters keep portability |
| 15 | Logging | Q19 | JSON stdout | **stdout → Loki self-host** | **Loki + Grafana** OR **Elastic self-host** for >100GB/day | 4 | PII risk = MUST stay on-prem |
| 16 | Error tracking | Q19 | None | **Sentry Team** (cloud or self-host) | **Sentry self-host** when audit committee demands it | 2 | DSN swap |
| 17 | Background jobs | Q1 (impl) | None yet (sync) | **arq** (Redis-based, asyncio-native) | **Temporal self-host** for multi-step OA pipelines + retries | 5 | Temporal is sticky |
| 18 | App metadata DB | Q5,Q13 | SQLite | **Postgres 16** (first paying customer) | **Postgres 16 HA** (Patroni) OR **MariaDB** if TPIsoftware bundles it | 6 | schema migration is doable; ORM-agnostic SQL helps |
| 19 | Docketing integration | (new) | None | **CSV export** + **Anaqua DAS connector** stub | **Anaqua AQX API** (acquired Patrix Nov 2024) + **CPi/CPA Global** webhook + Townes import | 7 | partner-driven; each firm picks one |
| 20 | SAST/DAST | (sec) | None | **Semgrep OSS** + **Bandit** in CI | **Semgrep AppSec Platform** + **Snyk for SCA** | 2 | CI plugins, swappable |
| 21 | Pen-test | (sec) | None | **DEVCORE** (TW) one-shot audit before first paying customer | **DEVCORE annually + NCC Group** before tier-1 firm onboard | 1 | services, no lock-in |
| 22 | PDF redaction (visible) | Q10 | Text-level only | **PyMuPDF redaction annotations** (free) | **Foxit PDF SDK** ($9/mo+ commercial, AI Smart Redact) | 3 | swap is a function-call refactor |
| 23 | Patent data sources | Q6,Q7 | TIPO/USPTO seed (30 demos) | **TIPO + USPTO bulk** (free) + **Google Patents BQ** | + **EPO OPS** (paid tier) + **Lens.org** + **IFI CLAIMS** for premium customers | 4 | re-indexing is days, not weeks |
| 24 | Translation | (FU) | None | **DeepL API** ($5.49/mo + $25/M chars) for TW↔EN OA cross-jurisdiction | + **GPT-4o** for legal-style; Azure as commodity fallback | 2 | trivial swap |

---

## Component deep dives

### 1. LLM provider — Q15

**Current state.** `backend/shared/config.py` lines 92-97 define `LLM_MODE` (mock/openai/anthropic/local), `LLM_MODEL_REASONING=claude-sonnet-4-6`, `LLM_MODEL_CHEAP=claude-haiku-4-5-20251001`, `LLM_MODEL_VERIFIER=claude-haiku-4-5-20251001`. The router in `backend/ai_engine/llm_client.py` already abstracts provider per intent. `LOCAL_LLM_FOR_SECURITY_LEVELS=("confidential","top_secret")` (line 137) is the load-bearing flag for confidential routing.

**Build option.** Wire your own multi-provider client with retry/backoff/usage logging. ~3 weeks for a senior eng; quality risk = streaming nuances, prompt-caching headers, JSON-mode contract differences across vendors.

**Buy options (commercial).**
- **Anthropic** Claude Sonnet 4.6 ($3/M input, $15/M output), Haiku 4.5 ($1/M in, $5/M out), Opus 4.7 ($5/M in, $25/M out) — 1M context standard on Sonnet/Opus per [BenchLM.ai pricing tracker](https://benchlm.ai/blog/posts/claude-api-pricing) and [official Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). Best reasoning quality on long patent text per our internal eval; prompt caching cuts ~90% on system prompts that don't change ([Finout 2026 guide](https://www.finout.io/blog/anthropic-api-pricing)).
- **OpenAI** GPT-4o/o3 — comparable price point; weaker than Sonnet on Chinese patent claims in our 30-case eval; useful as a commercial-tier fallback.
- **Google Gemini 2.5 Pro** — strongest 2M-context window; vendor risk around legal-vertical commitments; useful for the figure-vision sub-workflow.

**Open-source options.**
- **Llama 3.3 70B Instruct** (Meta license, "Llama 3 community license" — commercial use OK but >700M MAU clause) — strongest open weights at 70B class; needs a 1×H100 or 2×A100.
- **Mistral Large 2** (open weights with research clause for some sizes; Mistral commercial license required for prod) — strong on European languages.
- **Qwen 2.5 72B** — Alibaba license; the only credible open model on traditional Chinese patent reasoning; trust posture is the question for US clients.

**Partner option.** TPIsoftware's digiRunner AI gateway can act as the LLM key broker. Useful for centralised cost tracking but doesn't itself host models.

**NOW recommendation.** Anthropic for cloud (Sonnet for `parse_oa`/`draft_response`, Haiku for `verify_citations`) + Ollama-hosted Llama 3.1 8B for confidential-flagged cases. Total budget: ~$5-10/day at first-3-customers volume per our HANDOFF §13.3.

**LATER recommendation.** Same Anthropic cloud path; swap Ollama-8B → vLLM Llama 3.3 70B Q4 when confidential-case volume justifies the H100. Add OpenAI as a router fallback for when Anthropic has an outage (we've seen 30-90 min outages quarterly). Keep Qwen 2.5 72B as the in-house traditional-Chinese fallback for paranoid TW tier-1 firms.

**Migration cost NOW → LATER.** ~1 sprint. The Q15 router shape doesn't change; we add a vLLM endpoint and update `LLM_MODEL_LOCAL`. Reranking the verifier model is a prompt-yaml edit.

**Lock-in.** 4/10. Anthropic-specific features (extended thinking, computer use, prompt caching headers) creep into prompts and become small re-engineering tasks at swap time.

**Revisit trigger.** Anthropic price hike ≥30%, or a Claude generation that regresses on patent-claim reasoning vs our eval harness.

---

### 2. Local-LLM hosting — Q15 (implementation layer)

**Current state.** `config.py` lines 100-101 reference Ollama (`OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_SEC=600`).

**Build option.** Roll your own FastAPI wrapper around `transformers` + `accelerate`. Don't. PagedAttention and continuous batching are non-trivial and inventing them costs months.

**Buy / OSS options.**
- **Ollama** — Apache 2.0. Single binary, dev-friendly. Best for POC and Apple-Silicon engineer laptops. Throughput is the catch.
- **vLLM** (Apache 2.0) — ~2.3× higher throughput than Ollama at 8 concurrent users and ~8-9× aggregate tokens per H100 vs Ollama on the same quantization per [tech-insider 2026 benchmark](https://tech-insider.org/vllm-vs-ollama-2026/). The production answer.
- **TGI** (Apache 2.0) — Hugging Face's option, **in maintenance mode since 11 Dec 2025** per [the same benchmark](https://tech-insider.org/vllm-vs-ollama-2026/). Don't greenfield onto it.
- **Together AI** / **Anyscale** — managed vLLM. Pay-per-token. Loses "data never leaves on-prem" Q3 invariant — disqualified for confidential cases.

**NOW.** Ollama. Single docker container, OpenAI-compatible at `/v1`, fits our `OLLAMA_BASE_URL` config. Burn rate near zero.

**LATER.** vLLM behind a LiteLLM proxy. The HF-published Llama 3.3 70B FP8 on a single H100 at ~$1,800/mo all-in is the going rate per [Medium self-hosting guide](https://abhinand05.medium.com/self-hosting-llama-3-1-70b-or-any-70b-llm-affordably-2bd323d72f8d).

**Migration cost.** 1-2 sprints incl. quantization tuning. Both expose `/v1/chat/completions`.

**Lock-in.** 3/10. OpenAI-compatible APIs make it close to a config flip.

**Revisit trigger.** vLLM project stagnation (low risk; it's the de-facto standard now) or a new SGLang-class entrant with 2× throughput.

---

### 3. Embeddings — Q7

**Current state.** `EMBEDDING_BACKEND=mock` default, `EMBEDDING_MODEL=BAAI/bge-m3` (config lines 116-117); `EMBEDDING_DIM=384` for mock, 1024 reported by bge-m3.

**Build option.** Don't. Training embeddings from scratch is a research project.

**Buy options.**
- **Cohere embed v3** ($0.10/M tokens, multilingual edge per [reintech 2026](https://reintech.io/blog/embedding-models-comparison-2026-openai-cohere-voyage-bge)).
- **OpenAI text-embedding-3-large** ($0.13/M tokens, 3072 dims). Easiest to wire; mediocre Chinese.
- **Voyage AI voyage-3** ($0.18/M tokens; MTEB 67.8 — top of the table per [reintech](https://reintech.io/blog/embedding-models-comparison-2026-openai-cohere-voyage-bge)).

**Open-source options.**
- **BAAI bge-m3** (MIT) — multilingual incl. zh-TW + zh-CN + EN, 8192 token context. The patent-text workhorse. Already wired in `EMBEDDING_BACKEND`.
- **E5-mistral-7b** (MIT) — bigger, slower, marginal MTEB gain.
- **jina-embeddings-v3** (Apache 2.0) — newer multilingual contender.

**NOW.** bge-m3 self-host (`sentence-transformers`). Zero per-call cost. ~150 ms/query on CPU acceptable for our POC throughput.

**LATER.** Keep bge-m3 as the on-prem default for Chinese-heavy customers; offer Voyage-3 as an opt-in for US firms paying for the quality delta. Run them side-by-side on the same Qdrant collection (separate vector fields).

**Migration cost.** **Re-embedding the corpus is the cost** — at 1M patent chunks, ~1-2 days on a single GPU and ~$120 if going to Voyage's API. The code change is trivial.

**Lock-in.** 2/10. Dimensional mismatch makes hot swaps impossible but the vector store schema lets you have parallel fields.

**Revisit trigger.** A 5+ point MTEB lead from a new model, or bge-m3 maintainer abandonment (BAAI funding question).

---

### 4. Vector DB — Q5, Q7

**Current state.** `VECTOR_BACKEND=memory` (numpy in-process); `QDRANT_URL` settable; target backend is Qdrant docker per ARCHITECTURE.md Q7.

**Build option.** Don't. HNSW + filtering + persistence is months.

**Buy / OSS options.** Pricing per [MarkTechPost 2026 vector DB ranking](https://www.marktechpost.com/2026/05/10/best-vector-databases-in-2026-pricing-scale-limits-and-architecture-tradeoffs-across-nine-leading-systems/) and [LeanOps 2026](https://leanopstech.com/blog/vector-database-cost-comparison-2026/):
- **Qdrant** (Apache 2.0) — self-host free; Qdrant Cloud ~$65/mo at 10M vectors. Best filter API. Rust core, low ops burn. **Current target.**
- **Weaviate** (BSD-3) — $200-400/mo at 10M vectors (AU-hours model). Modules ecosystem nicer than Qdrant; cost less predictable.
- **Pinecone** (managed-only) — ~$70/mo at 10M serverless, climbing fast to $700+/mo at 100M. **Disqualified** for confidential cases — managed cloud breaks Q3.
- **Milvus** (Apache 2.0) — open-source, scale-out. Heavier ops (etcd, MinIO, Pulsar) than Qdrant; pick if going billion-scale.
- **pgvector** (Postgres) — collapses one piece of infra into Postgres; fine until ~5M vectors, slow at 50M+.
- **Chroma** — POC-quality, not production.

**NOW.** Qdrant self-host docker, one process per environment. Already what `VECTOR_BACKEND=qdrant` wires.

**LATER.** Qdrant Hybrid Cloud (control-plane SaaS, data-plane in customer VPC) — keeps Q3 invariant (vectors stay on-prem, only metadata pings their control plane), removes ops burden. Or stay self-host on K8s with a 3-node cluster if firm refuses any SaaS control plane.

**Migration cost.** Zero for self-host → Hybrid Cloud. From Qdrant to Weaviate/Milvus is rewrite-collection-loaders (1-2 weeks).

**Lock-in.** 5/10. Per-tenant collection idiom is portable; payload-filter query shape less so.

**Revisit trigger.** Per-tenant Qdrant cluster ops cost hits 30% of opex (the Q5 cost flagged in DECISIONS.md §2). Then we move to a multi-tenant Qdrant collection with row-level filter — which forfeits Q5's physical isolation guarantee and requires customer sign-off.

---

### 5. Cache — Q9

**Current state.** `CACHE_BACKEND=memory` default; `REDIS_URL` config-only stub.

**Buy / OSS options.** Per [Cachee.ai 2026 cache comparison](https://cachee.ai/cache-comparison-2026) and [Singh's benchmark](https://singhajit.com/redis-vs-dragonflydb-vs-keydb/):
- **Redis 8** (AGPLv3 since May 2025 — **copyleft trap for closed-source SaaS**). Most ecosystem support. Per-vendor managed services pricey.
- **Valkey** (BSD-3, Linux Foundation, AWS/Google/Oracle-backed) — the fork. Drop-in for Redis 7.2 clients. **The default for any new project in 2026.**
- **KeyDB** (BSD-3) — multithreaded Redis fork, 2-5× higher throughput on multi-core. Active replication. Smaller community.
- **DragonflyDB** (BSL → Apache 2.0 path) — 25× throughput claims, 80% lower memory. Newest of the four; some clients have edge cases.

**NOW.** In-memory `dict` (current `CACHE_BACKEND=memory`). Adequate for first 3 customers. We already have `MAX_CACHE_ENTRIES_PER_TENANT` FIFO eviction.

**LATER.** **Valkey 8.0** (not Redis). Avoid AGPL contamination on the gateway image. Self-host on the same Postgres host or dedicated; cluster mode only if multi-AZ.

**Migration cost.** ~1 sprint to add `CACHE_BACKEND=valkey` (Redis client library works unchanged). Tenant-isolation key prefix already in `cache.py`.

**Lock-in.** 2/10. All four speak the Redis wire protocol.

**Revisit trigger.** Cache miss rate >40% (means we need bigger fleet) or memory >$1k/mo (DragonflyDB wins on cost-per-GB).

---

### 6. Audit storage — Q13

**Current state.** `AUDIT_BACKEND=sqlite`; hash chain in `data/audit.db` per `backend/gateway/audit.py`; Postgres URL in config (lines 121-124) but no implementation yet.

**Build option.** We already build it. The hash chain is our IP.

**Buy / OSS storage options.**
- **Postgres 16** (PostgreSQL license, BSD-like) — the default for any compliance-grade audit storage. JSONB columns hold our event payload; row triggers enforce append-only. Per [DEV.to TimescaleDB write-up](https://dev.to/polliog/why-i-chose-postgres-timescaledb-over-clickhouse-for-storing-10m-logs-1e18), Postgres handles >10M rows comfortably for our shape.
- **TimescaleDB** (Apache 2.0 community / TSL for some enterprise features) — Postgres extension; 90-95% compression on time-series rows per the same source. Pick once chain exceeds ~50M rows / tenant.
- **ClickHouse** (Apache 2.0) — overkill at our scale. The append-only sweet-spot model per [oneuptime ClickHouse audit guide](https://oneuptime.com/blog/post/2026-03-31-clickhouse-audit-trail-data-changes/view), but the operational model differs from Postgres and our schema migration costs more.
- **AWS QLDB** — **deprecated as of 31 Jul 2025**, disqualified.
- **immudb** (Apache 2.0) — cryptographic verification baked in. Tempting but we already have hash chain; double-layered semantics complicate audit forensics.

**NOW.** Keep SQLite for POC. Switch to Postgres 16 on day-1 of the first paying customer (HA needed for SLA). Schema migration is the existing chain-row INSERTs replayed; ~2 days.

**LATER.** Postgres 16 HA via Patroni + streaming replication (closes Q20 properly per DECISIONS.md row Q20). Add TimescaleDB extension when single-tenant chain exceeds ~50M rows.

**Migration cost.** SQLite → Postgres: 2 days. Postgres → TimescaleDB: extension install, 0 schema change.

**Lock-in.** 7/10. The hash chain shape is coupled to row ordering and timestamp precision. A backend swap that changes timestamp resolution invalidates verification across the gap.

**Revisit trigger.** Any compliance review demanding stronger guarantees than `append-only-via-trigger` (e.g. cryptographic notarization to a blockchain — overkill but tier-1 firms might ask).

---

### 7. Audit archival — Q13

**Current state.** None. CLAUDE.md §3 flags `Q13` as "Add S3 Object Lock hourly archiver" TODO.

**Buy options.**
- **AWS S3 Object Lock Compliance Mode** — SEC 17a-4, CFTC, FINRA assessed by Cohasset per [AWS S3 Object Lock page](https://aws.amazon.com/s3/features/object-lock/). The regulator-facing answer. Compliance mode means *not even root* can delete. $0.023/GB/mo Standard tier; Glacier Deep Archive at $0.00099/GB/mo for cold audit.
- **Azure Immutable Blob Storage** — time-based retention + legal holds. Comparable price band. Pick when firm runs on Azure tenancy.
- **GCS Bucket Lock** — comparable; thinner third-party compliance attestations.
- **WORM tape** (LTO-9) — overkill unless firm has a tape robot in their datacentre. Some TW manufacturing partners do.

**Open-source / build.** MinIO with object-lock support — runs in customer DC if cloud egress is forbidden. Not as well-attested for SEC 17a-4 but enough for non-US regulators.

**NOW.** None. SQLite local is the only audit copy. Acceptable risk per DECISIONS.md Q20 caveat.

**LATER.** S3 Object Lock Compliance Mode for cloud-OK customers + MinIO for on-prem-only customers. Hourly cron archiver from Postgres → object store.

**Migration cost.** ~3 days to write + test the archiver.

**Lock-in.** 3/10. Tar-gzipped append-only files; portable across object stores.

**Revisit trigger.** A regulator audit revealing our hourly RPO is insufficient (then move to per-row streaming archive).

---

### 8. API gateway — Q1

**Current state.** Hand-rolled `backend/gateway/main.py` mocks digiRunner.

**Buy options (pricing per [Zuplo 2026 comparison](https://zuplo.com/learning-center/api-gateway-pricing-comparison-2026)).**
- **digiRunner Enterprise** (TPIsoftware, partner) — quote-only per [Capterra digiRunner](https://www.capterra.com/p/10015814/digiRunner/); on-prem standalone or HA; OIDC, mTLS, AI gateway feature with managed Anthropic key per [TPIsoftware product page](https://www.tpisoftware.com/en/products/digirunner). **Already the chosen path** per `docs/PHASE3_MIGRATION.md`.
- **Kong Enterprise** — ~$5,350/year for 5M req + 50 services (entry tier). RBAC, OIDC, dev portal. Strong K8s native.
- **Apigee** — $10k+/mo entry. Tier-1 enterprise only.
- **AWS API Gateway** — $1/M REST calls + data transfer. ~$3k/mo at 100M calls/day. **Disqualified for confidential customers** (managed AWS edge).
- **Tyk** — free OSS / Cloud from $500/mo. Good mid-market option.
- **Zuplo** — programmable, Cloudflare-Worker-style.

**Open-source.**
- **Kong OSS** (Apache 2.0). Free; missing the enterprise OIDC + dev portal we'd need.
- **APISIX** (Apache 2.0). Closest OSS competitor to Kong; gaining ground.
- **Krakend** (Apache 2.0). Stateless, simpler model.

**Partner option.** TPIsoftware digiRunner is **the** integration story. They are our partner since we chose Dify on top. There is no rational reason to swap.

**NOW.** digiRunner Enterprise Standalone (per PHASE3_MIGRATION.md §10 SKU selection). Their AI gateway feature replaces our `rate_limit.py` enforcement. Anthropic key vaulted in digiRunner.

**LATER.** digiRunner HA. Add Kong OSS as the edge ingress only if multi-firm SaaS scaling demands it (multi-region presence).

**Migration cost.** Already planned 4-week migration in PHASE3_MIGRATION.md. Mostly config + thin-gateway carve-out.

**Lock-in.** 8/10. Once digiRunner mints JWTs and our backend trusts upstream headers, swapping to Kong needs a parallel auth path + traffic split.

**Revisit trigger.** TPIsoftware partnership breaks down OR digiRunner roadmap stalls on AI-gateway features (e.g. fails to add provider X we need).

---

### 9. Workflow orchestration — Q1, Q2

**Current state.** Native Python `orchestrator.py` (6-step DAG). Dify mock via `EXPOSE_PROMPT_API`.

**Buy options.**
- **Dify** (Apache 2.0 + commercial cloud; partner via TPIsoftware) — built for LLM workflows. Self-host OR Dify Cloud. v1.6 two-way MCP support per [Dify blog](https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support). **The chosen path.**
- **Langfuse** (MIT) — observability + prompt versioning + LLM workflow stub. Lighter than Dify; pair-able.
- **Temporal** — durable workflow engine. Overkill for our LLM-pipe but excellent if we later add long-running OA pipelines (await human attorney review).
- **Airflow** — wrong tool. DAG paradigm not interactive enough.
- **n8n** (fair-code SUL) — workflow-first not LLM-first. Per [HostAdvice n8n vs Dify](https://hostadvice.com/blog/ai/automation/n8n-vs-dify/) — if you start with "I want to chain SaaS triggers", n8n. If you start with "I want an AI workflow", Dify. We're the latter.

**Open-source.** Dify itself is OSS; LangGraph as a Python-native alternative.

**NOW.** Keep `orchestrator.py` native Python — it's 150 lines and stable. Run Dify in shadow per PHASE3_MIGRATION.md §3.1 against 30 eval cases. **Do not cut over before the >=28/30 shadow gate passes.**

**LATER.** Dify 1.6+ self-host (partner relationship via TPIsoftware). Native Python orchestrator becomes the AI-engine `verify_citations` + `retrieve_prior_art` HTTP nodes that Dify calls.

**Migration cost.** 1-2 sprints once shadow gate passes. PHASE3_MIGRATION.md §6 ships the workflow JSONs.

**Lock-in.** 6/10. Dify DSL is not standardized; export to vanilla JSON is workable but each workflow node ID rewrites on upgrade per Dify Discussion #8090.

**Revisit trigger.** Dify maintainer abandons the project, or v2.x breaks our workflow JSON shape badly.

---

### 10. Identity / SSO — Q12

**Current state.** Built-in JWT (`_USERS` dict in `auth.py`); upstream-header path (`x-user-id` / `x-tenant-id`) from trusted IPs (Day 8C) ready for digiRunner.

**Buy options (per [Keycloakpro 2026 cost comparison](https://keycloakpro.com/blog/keycloak-vs-auth0-vs-keycloak-cost-comparison)).**
- **Auth0** — $0.07/MAU after Okta's 2024 restructure; B2C Essentials at $3,500/mo for 50k MAU; SAML connections billed $100/mo each. Fastest setup.
- **Okta** — per-user-per-feature; $100k-$1.8M/yr for 10k seats depending on feature stack. Tier-1 firm story but eats the budget.
- **Microsoft Entra ID** — included in M365 E5; if firm already pays for E5, near-zero marginal cost. Strong path for firms standardised on MS.

**Open-source.**
- **Keycloak** (Apache 2.0) — free, SAML+OIDC+OAuth2+LDAP+SCIM out-of-box. At 100k users, saves $162k/yr vs Auth0 per [Keycloakpro](https://keycloakpro.com/blog/keycloak-vs-auth0-vs-keycloak-cost-comparison).
- **Authentik** (MIT) — newer, prettier admin UI, smaller community.
- **Ory Kratos** — opinionated, headless, requires you to build your own UI.

**Partner.** digiRunner ships its own OIDC machinery and federates upstream. The firm's existing IdP (Keycloak, Okta, Entra) becomes the source-of-truth; digiRunner just routes.

**NOW.** Either digiRunner's built-in OIDC OR self-host Keycloak behind it. Customer-driven choice. The thin-gateway path already trusts upstream headers, so it doesn't care which.

**LATER.** Federation pattern: customer's IdP (Entra/Okta/Keycloak) → digiRunner → upstream-header trust. We never own primary identity.

**Migration cost.** Zero on our side post-PHASE3.2. digiRunner config + upstream firm IdP coordination.

**Lock-in.** 3/10. Upstream-header abstraction means our backend code is identity-vendor-agnostic.

**Revisit trigger.** A firm demands SAML-only and digiRunner can't pass through it (unlikely per their docs).

---

### 11. OCR — Q8

**Current state.** Tesseract stub, no real upload path yet (CLAUDE.md §3).

**Buy options (per [aiproductivity 2026 OCR comparison](https://aiproductivity.ai/blog/document-ai-cost-comparison/)).**
- **AWS Textract** — $0.0015/page basic; $0.065/page forms-and-tables. Best at structured forms; **disqualified for confidential** (cloud upload).
- **Azure Document Intelligence** — $1.50/1k pages basic; $0.53/1k pages at 1M+ commitment tier. Strong on legal docs. Best free tier (500 pages/mo ongoing).
- **Google Document AI** — comparable; thinner free tier.
- **Mistral OCR 3** — $0.001-0.002/page, the new cheapest option per the same source.

**Open-source.**
- **Tesseract** (Apache 2.0) — free, on-prem, decent on clean print, weak on scans. The confidential-path workhorse.
- **PaddleOCR** (Apache 2.0) — Baidu's, multilingual incl. zh-CN; quality > Tesseract on Chinese text.
- **Surya / docTR** — newer ML-based, GPU-friendly.

**Partner.** TPIsoftware does not bundle OCR.

**NOW.** Tesseract on-prem default; Claude Sonnet vision as the "if Tesseract fails, retry with vision" fallback per current `ocr_page.workflow.json` design. PaddleOCR install for zh-CN-heavy customers.

**LATER.** Azure Document Intelligence for non-confidential US OA pipeline (US firms care less about cloud egress for already-public OAs); Tesseract/PaddleOCR stays as the confidential path. Per-page costs at our volume (~1000 OAs/mo × ~30 pages each = 30k pages/mo) ≈ $45/mo on Azure — trivial.

**Migration cost.** OCR layer is already abstracted in `extract_pdf.workflow.json` design.

**Lock-in.** 4/10. Quality cliff between OCR vendors means you re-tune downstream parsers per provider.

**Revisit trigger.** OCR accuracy <90% on our internal patent OA corpus.

---

### 12. PDF text extraction — Q8

**Current state.** `backend/ai_engine/pdf_parser.py` — likely pdfplumber per HANDOFF.

**Open-source options.** Per [pdfmux 200-PDF benchmark](https://pdfmux.com/blog/pdfmux-vs-pymupdf-vs-marker-vs-docling/) and the [arXiv comparative parsing study](https://arxiv.org/pdf/2410.09871):
- **PyMuPDF / fitz** (AGPL — commercial license available, ~$10k+/yr for closed-source SaaS) — 8-12× faster than pdfplumber on text. The fastest pure-Python option. **License is the gotcha** for a SaaS.
- **pdfplumber** (MIT) — slower, no OCR, fine for clean PDFs, weak on complex layouts. License-clean.
- **pdfminer.six** (MIT) — slower than both above; reference implementation.
- **Marker** (GPL-3.0) — deep-learning layout detection, GPU needed; 5-10× slower without. The arXiv benchmark says **patent documents specifically need ML-based parsers** — all rule-based parsers underperformed on Scientific + Patent categories.
- **pypdfium2** (Apache 2.0 + BSD-3) — wraps Google's PDFium. Permissive license + fast.

**Buy.** Marker AI hosted, Llamaparse, Unstructured.io managed.

**NOW.** **PyMuPDF for speed** (we ship as enterprise — buying the commercial PyMuPDF license is $10k/yr ballpark per Artifex). If we want to stay 100% MIT/Apache: pypdfium2.

**LATER.** Add Marker for complex layouts (scanned spec drawings, multi-column claim formatting). Run as fallback after PyMuPDF fails confidence threshold.

**Migration cost.** Library API is similar across all options; ~3 days incl. fixture re-tuning.

**Lock-in.** 1/10. Function-level swap.

**Revisit trigger.** PyMuPDF Artifex license cost passes $20k/yr; or a TW firm legal review flags AGPL even with our split runtime.

---

### 13. Frontend hosting — Q4

**Current state.** Vite SPA dev server.

**Buy options (per [DevToolReviews 2026](https://www.devtoolreviews.com/reviews/vercel-vs-netlify-vs-cloudflare-pages-2026)).**
- **Cloudflare Pages** — $5/mo Pro, free bandwidth. Best bandwidth economics; 1TB/mo = $0 vs $150 on Vercel.
- **Vercel** — $20/mo Pro; Enterprise ~$45k/yr median. Pro BAA at $350/mo.
- **Netlify** — $20/mo, reduced free tier (100 build min) in 2026.

**Open-source / self-host.** Nginx serving `dist/` from the gateway box.

**NOW.** **On-prem nginx** inside the gateway VPC. Firm clients refuse to have their SPA frame hosted on a public CDN edge — auditors flag it. POC verify.sh already runs this way.

**LATER.** Same on-prem nginx. Marketing site (separate Next.js app per Q4 + DECISIONS.md) on Cloudflare Pages — that one has no confidentiality concern.

**Migration cost.** Zero — static asset bundles are fully portable.

**Lock-in.** 1/10.

**Revisit trigger.** A customer asks for global multi-region SPA load — then Cloudflare Pages for the SPA shell, on-prem for the API.

---

### 14. Observability — Q19

**Current state.** JSON logs + Prometheus stub per DECISIONS.md Q19.

**Buy (per [Better Stack 2026 Datadog vs Sentry](https://betterstack.com/community/comparisons/datadog-vs-sentry/) and [Spendhound](https://www.spendhound.com/marketplace/honeycomb-pricing)).**
- **Datadog** — avg SMB plan $104k/yr. Broadest capabilities, eat-your-budget pricing.
- **Honeycomb** — avg SMB $24k/yr. Best for high-cardinality (per-`case_id` tracing).
- **New Relic** — comparable to Datadog.
- **Signoz** — open-source Datadog clone.

**Open-source.**
- **Prometheus + Grafana** (Apache 2.0) — the default. Operational lift moderate.
- **Loki** (AGPL but client-friendly) for logs.
- **Tempo** for traces.
- **OpenTelemetry** SDK for vendor-portability.

**NOW.** OpenTelemetry instrumentation in our gateway/ai-engine + Sentry Team ($29/mo per [Sentry pricing](https://comparetiers.com/tools/sentry)) for error tracking. Prometheus + Grafana self-host once first paying customer is on.

**LATER.** Prom + Grafana + Loki self-host (all on the same K8s cluster as Postgres). Sentry stays. Honeycomb opt-in for the customer who pays for per-case tracing depth.

**Migration cost.** OpenTelemetry exporters mean changing vendor is a config flip.

**Lock-in.** 3/10 (if we instrument via OTel from day one).

**Revisit trigger.** Datadog acquires Sentry and bundles them at <Sentry standalone price (unlikely but watch).

---

### 15. Logging — Q19

**Current state.** JSON stdout.

**Per CLAUDE.md §3 PII concern**: shipping logs off-prem violates Q3.

**Buy.** Datadog Logs / Better Stack / Splunk — **all disqualified** for confidential customers (logs leave the box).

**Open-source / self-host.**
- **Loki** (AGPL) + Grafana. Cheap, K8s-native. Default.
- **Elastic** (Elastic License 2.0 / SSPL) — heavier but search-rich. Pick at >100GB/day.
- **VictoriaLogs** (Apache 2.0) — new entrant, lower memory.

**NOW.** stdout → docker logs → Loki self-host. Single node fine.

**LATER.** Loki cluster on the K8s. Elastic only if the legal team needs SIEM-grade audit search at scale.

**Migration cost.** Logger config + dashboards.

**Lock-in.** 4/10 (dashboards are vendor-specific).

**Revisit trigger.** Any cloud logging vendor adds a "stays-in-customer-VPC" deployment that beats self-host TCO.

---

### 16. Error tracking — Q19

**Current state.** None.

**Buy.** **Sentry** ($29/mo Team, $80/mo Business) — published per-event pricing. Self-host option (Apache 2.0 OSS edition or BSL Source-Available). Bugsnag, Rollbar comparable. Sentry wins on Python+React first-class SDK.

**NOW.** Sentry cloud Team plan ($29/mo). DSN env var, one SDK init line, done.

**LATER.** Sentry self-host when an audit committee asks "where do exceptions go?" The OSS image is fine for our scale.

**Migration cost.** DSN swap.

**Lock-in.** 2/10.

**Revisit trigger.** Sentry SaaS-prices double or self-host becomes too operationally heavy.

---

### 17. Background jobs — Q1 implementation

**Current state.** None (all sync HTTP).

**Buy / OSS options (per [Judoscale Python task queue guide](https://judoscale.com/blog/choose-python-task-queue) and [Medium dramatiq 2026](https://medium.com/@Nexumo_/reliable-python-queues-7-celery-dramatiq-rq-choices-266ac544a4a5)).**
- **Celery** (BSD) — mature, feature-heavy, complex ops. Battle-tested.
- **Dramatiq** (LGPL-3) — simpler API; ~10× faster than RQ in benchmarks.
- **arq** (MIT) — asyncio-native; fits our FastAPI async paradigm best. Redis-only broker.
- **RQ** (BSD) — simplest; slowest.
- **Temporal** — durable workflows. Different category — picks up where queues end (multi-step, long-running, human-in-loop).

**NOW.** **arq** (Redis-based, asyncio-native, ~200 LoC to integrate). Wire on top of Valkey (when we add it).

**LATER.** Temporal self-host for long-running OA pipelines that involve attorney review steps (the Q16 human-in-loop story). Keep arq for fire-and-forget jobs.

**Migration cost.** 1 sprint. Temporal SDK adds ~500 LoC.

**Lock-in.** 5/10 for Temporal once workflows are written in its SDK.

**Revisit trigger.** arq maintainer goes quiet (it's a small project — real risk).

---

### 18. App metadata DB — Q5, Q13

**Current state.** SQLite (`patentmind.db`, `audit.db`, `redaction_mapping.db`).

**Buy / OSS.**
- **PostgreSQL 16** (BSD-like) — the universally-correct answer.
- **MariaDB** — relevant because TPIsoftware bundles MariaDB in some digiData / digiSpace stack pieces. Lower friction inside a TPIsoftware-shop customer.
- **MySQL 8** — Oracle owns; many firms still run it.
- **SQLite** — current; fine for POC, not for multi-tenant prod.

**NOW.** SQLite per POC; switch to Postgres 16 on day-1 of first paying customer (HA SLA demands replication, which SQLite can't do).

**LATER.** Postgres 16 with Patroni HA + streaming replication. Consider MariaDB if customer firm already runs TPIsoftware bundle and wants stack consolidation.

**Migration cost.** SQL dialect is mostly portable for our schema; SQLite→Postgres in ~2 days with `pgloader`.

**Lock-in.** 6/10. Postgres extension-driven features (pgvector, TimescaleDB) deepen lock once adopted.

**Revisit trigger.** A customer's IT shop is MySQL-only and forbids Postgres install.

---

### 19. Docketing integration — new

This is the **partner-leverage** axis. Patent firms rarely abandon their docketing system; we must integrate.

**Market shape (per [Anaqua](https://www.anaqua.com/) press + [Black Hills Anaqua connectors](https://blackhills.ai/ip-automation/automated-ip-integrations/anaqua/)).**
- **Anaqua AQX** — dominant. Acquired Patrix (~400 customers added) in late 2025. Has acquired FoundationIP, AcclaimIP, Lecorpio. API: limited and policy-restrictive — they explicitly resist third-party best-of-breed integrations per [Black Hills](https://blackhills.ai/ip-automation/automated-ip-integrations/anaqua/) write-up. We integrate via CSV export + their published office connectors.
- **CPA Global / Clarivate** — large EU/global presence.
- **Townes / IPzen / Patrix (now Anaqua)** — boutique to mid-market.
- **Computer Packages Inc. (CPi) IP Manager** — US firm strong.

**TW market.** Most TW firms run mix of CPi / Townes / homegrown Access DBs. There is no dominant SaaS docketing in TW. **This is opportunity:** we can be the API-first layer attached to whatever they have.

**NOW.** **CSV import/export** + **manual webhook receiver** for each first-3 customer. No vendor integration code. Each customer has a different docketing setup; let them export and we'll parse.

**LATER.** Anaqua AQX connector (their API is the bottleneck per Black Hills); CPi webhook; Townes import. Build a small integration framework (~1 month per integration after the first).

**Migration cost.** N/A — additive per customer.

**Lock-in.** 7/10 on the customer side. Once we've ingested their docket, they don't want to re-onboard somewhere else.

**Revisit trigger.** Anaqua opens their API (would unlock a much bigger TAM).

---

### 20. SAST/DAST — security

**Buy / OSS (per [Konvu Semgrep vs CodeQL](https://konvu.com/compare/semgrep-vs-codeql) and [DEV.to Snyk pricing](https://dev.to/rahulxsingh/snyk-pricing-in-2026-free-plan-team-business-and-enterprise-costs-breakdown-5e88)).**
- **Semgrep OSS** (LGPL) free; AppSec Platform $30/contributor/mo.
- **GitHub CodeQL** — free for public, $49/contributor/mo private (GHAS).
- **Snyk** — $25/contributor for OSS, Code separately. Best SCA.
- **Bandit** (Apache 2.0) — Python-specific, cheap to add.

**NOW.** Bandit + Semgrep OSS in CI. Free.

**LATER.** Semgrep AppSec Platform (managed rules) + Snyk for SCA. ~$55/contributor/mo combined — fine for a 5-eng team.

**Migration cost.** CI YAML edits.

**Lock-in.** 2/10.

**Revisit trigger.** A vulnerability we should've caught makes it to prod.

---

### 21. Pen-test partners

**Buy.**
- **DEVCORE** (TW, [devco.re](https://devco.re/en/)) — TW's strongest offensive sec firm; deep 0-day track record per [Stingrai 2026 ranking](https://www.stingrai.io/blog/best-penetration-testing-companies-2026). Local language, local insight.
- **NCC Group** — global; UK HQ since 1999; standardised across UK/Europe/NA/APAC.
- **Bishop Fox** — strong red-team brand; US-centric.
- **Trail of Bits** — best for cryptographic + smart-contract; overkill for us.

**NOW.** DEVCORE one-shot before first paying customer. ~$30-60k for a 2-3 week engagement.

**LATER.** DEVCORE annually for the TW story; NCC Group before onboarding any US tier-1 firm (US firms have heard of NCC, often haven't of DEVCORE).

**Migration cost.** N/A.

**Lock-in.** 1/10.

**Revisit trigger.** A pentest finding pattern that one firm misses but another catches.

---

### 22. PDF redaction (visible-mark + searchable)

**Current state.** Text-level redaction only (`backend/gateway/masking.py`). We do **not** ship redacted PDFs.

**Why this matters.** Many firms need to file with the patent office or share OA correspondence externally with visible black-bar redaction (vs our placeholder swap-in). This is a real product gap if customers ask.

**Buy options (per [G2 Foxit SDK reviews](https://www.g2.com/products/foxit-pdf-sdk/reviews)).**
- **Foxit PDF SDK** — from $9/mo per seat; AI Smart Redact at 99% PII detection per their docs. Best-in-class.
- **iText 8** — AGPL or commercial; redaction add-on extra.
- **Aspose.PDF** — commercial library, comparable feature set, complex licensing.
- **Adobe Acrobat SDK** — server license $$$$.

**Open-source.**
- **PyMuPDF redactions** — `add_redact_annot` + `apply_redactions` works fine for our text-level use. License caveat (AGPL).
- **PDFBox** (Apache 2.0) — Java, integration friction.

**NOW.** **PyMuPDF redactions**, covered already by the PyMuPDF text extraction decision.

**LATER.** Foxit PDF SDK once a customer asks for "submit redacted PDF to TIPO". $9/mo per seat plus commercial license.

**Migration cost.** ~1 sprint to wire Foxit alongside our existing masking output.

**Lock-in.** 3/10.

**Revisit trigger.** First customer files a redacted PDF and our PyMuPDF output gets criticised for cosmetic quality.

---

### 23. Patent data sources — Q6, Q7 (corpus seeding)

**Current state.** 30 synthetic demo cases per `data/cases/`.

**Buy / public.**
- **TIPO** (Taiwan IP Office) — free XML/JSON bulk data; via [data.gov.tw](https://data.gov.tw). The TW corpus baseline.
- **USPTO bulk** ([data.uspto.gov](https://data.uspto.gov/)) — free, comprehensive, well-documented API per [USPTO Open Data Portal](https://data.uspto.gov/apis/bulk-data/search).
- **EPO OPS** — RESTful API, structured patent data from EPO + INPADOC + national offices. Free tier limited; paid for volume.
- **Google Patents Public Datasets** — BigQuery, CC BY 4.0 via IFI CLAIMS collaboration per [Top 4 Patent Search APIs](https://projectpq.ai/best-patent-search-apis-2025/).
- **IFI CLAIMS Direct** — commercial, premium normalized data, quote-only.
- **PatBase / Derwent (Clarivate)** — premium professional search, $$$$.
- **PATSTAT** — EPO statistical database, ~€1,250/yr for 2 editions per [WIPO manual](https://wipo-analytics.github.io/manual/databases.html).
- **Lens.org API** — free for research/non-commercial; commercial pricing varies.

**NOW.** TIPO bulk + USPTO bulk + Google Patents public BQ. Pure free. Covers 95% of what TW firms file or cite.

**LATER.** Add EPO OPS (paid tier ~€2-5k/yr) for European prior art; IFI CLAIMS Direct for tier-1 firms paying premium ($$$$, quote-only); PatBase for the tier-1 firm that demands "what your competitors found in their professional search". Lens.org as an additional CC source.

**Migration cost.** Each new source = ~3 days ingestion code + bge-m3 re-embedding. Additive, not migration.

**Lock-in.** 4/10. We are at the mercy of source-data schema changes.

**Revisit trigger.** Google Patents BQ scheme deprecation; or USPTO bulk format change.

---

### 24. Translation (FU)

**Current state.** None.

**Why we need it.** Per Q15 cross-jurisdiction: a TW firm handling a US OA wants the OA shown in zh-TW AND the response drafted in EN. We currently rely on Claude itself to translate during prompt eval. Dedicated translation API improves quality, cuts cost.

**Buy (per [BuildMVPFast 2026 translation API comparison](https://www.buildmvpfast.com/api-costs/translation)).**
- **DeepL API Pro** — $5.49/mo base + $25/M chars. Best European quality. Privacy guarantees called out as a legal-docs differentiator.
- **Google Cloud Translation** — $20/M chars NMT; $10 in + $10 out per million chars LLM mode.
- **Azure Translator** — $10/M chars; largest free tier (2M chars/mo). Half the price of Google NMT.
- **GPT-4o / Claude direct prompt-as-translator** — most flexible, ~$3-15/M tokens depending on direction. Useful for "translate this in legal style".

**NOW.** **Claude direct** for the few cross-jurisdiction draft requests we'll see. Zero additional integration.

**LATER.** **DeepL API** for bulk OA-text translation (privacy + EU quality) + **Claude** for the legal-style rewriting layer. Combine: DeepL for raw, Claude for style. Azure as commodity fallback for high-volume non-confidential.

**Migration cost.** Negligible — single function wrapper.

**Lock-in.** 2/10.

**Revisit trigger.** A 30%+ price hike from DeepL or a new model with materially better legal-zh-TW quality.

---

## Cross-cutting view

### Three highest lock-in risks (and how we hedge)

1. **API gateway = digiRunner (8/10).** Going all-in on the partnership is a *bet* on TPIsoftware as a vendor. **Hedge:** keep our thin-gateway design (PHASE3_MIGRATION.md §8). Every endpoint that digiRunner fronts also accepts direct calls with upstream-header auth disabled. The migration plan explicitly retains the legacy login path in code (deleted only in §3.4 after 5 consecutive green CI runs). If TPIsoftware partnership collapses, we re-enable native auth in ~1 week and front-end on Kong OSS in ~3 weeks.
2. **Audit storage = Postgres + hash chain (7/10).** Once 6 months of regulator-facing hash-chain rows exist, swapping DB engines is a months-long replay project. **Hedge:** keep schema vendor-neutral (no Postgres-specific features in core audit table — no JSONB-path queries on chain rows, no pg-specific triggers). Archive every row to S3 Object Lock weekly so a worst-case rebuild can replay from object store.
3. **Workflow orchestration = Dify (6/10).** Dify DSL is not standardized. **Hedge:** the LLM prompts are externalised as YAML files in `backend/ai_engine/prompts/`. The orchestration logic lives in our native Python orchestrator until the >=28/30 shadow gate per PHASE3_MIGRATION.md §3.1. We never delete `orchestrator.py` — it becomes the "rollback to native" path. Same applies to Q14 verifier: stays as our HTTP node, never moves *into* a Dify code node, per [SECURITY_AUDIT.md "What's done well" item #4](./SECURITY_AUDIT.md).

### Three highest delta-cost components (% of monthly opex)

1. **LLM provider (Anthropic API)** — currently ~$5-10/day per HANDOFF; scales linearly with volume. At 20 customers ≈ $200-500/day = $6-15k/mo. **The dominant variable cost.** Prompt caching + per-tenant token budget (Q18 already done) keep this in check.
2. **Local-LLM hosting (vLLM on H100)** — ~$1,800/mo for a single dedicated H100. Fixed cost — only triggers if confidential-case volume justifies it. Until then, an Ollama node on existing compute is ~$0 marginal.
3. **Vector DB self-host scaling** — per Q5 single-tenant data principle, each new customer = new Qdrant cluster. At $30-100/mo per single-node cluster × 20 customers = $600-2k/mo just on RAM. Hedge: Qdrant Hybrid Cloud once over 10 customers; or per-tenant collection inside a shared cluster if customer signs off on the isolation downgrade.

### Q-mapping (each component → architectural Q)

| Q | Component(s) |
|---|---|
| Q1 Gateway | 8 API gateway, 9 orchestration |
| Q2 Dify | 9 orchestration |
| Q3 Hybrid egress | 1 LLM provider (confidential routing), 15 logging |
| Q4 Two frontends | 13 frontend hosting |
| Q5 Single-tenant data | 4 vector DB, 18 metadata DB |
| Q6 Chunking | 3 embeddings, 23 patent data sources |
| Q7 Vector DB | 4 vector DB, 3 embeddings |
| Q8 Multi-modal | 11 OCR, 12 PDF extraction |
| Q9 Cache | 5 cache |
| Q10 Masking | 22 PDF redaction |
| Q11 Prompt injection | 1 LLM provider (verifier model isolation) |
| Q12 Auth | 10 SSO, 8 API gateway |
| Q13 Audit | 6 audit storage, 7 audit archival |
| Q14 Grounded cites | 1 LLM provider (verifier) |
| Q15 LLM router | 1 LLM provider, 2 local-LLM hosting, 24 translation |
| Q16 HITL | 17 background jobs (Temporal) |
| Q17 Deadlines | 23 patent data sources (holiday feeds) |
| Q18 Cost control | 1 LLM provider, 8 API gateway (AI gateway feature) |
| Q19 Observability | 14 observability, 15 logging, 16 error tracking |
| Q20 DR / RPO | 6 audit storage, 7 audit archival, 18 metadata DB |
| FU Orchestration split | 8 API gateway, 9 orchestration |

### "Lean opex" stack (first 3 customers — minimise burn)

| Component | Lean choice | Monthly cost |
|---|---|---|
| LLM | Anthropic Sonnet + Haiku | $200-500 |
| Local LLM | Ollama on existing box | $0 |
| Embeddings | bge-m3 self-host | $0 |
| Vector DB | Qdrant docker, single node | $0 (hardware amortized) |
| Cache | in-memory dict | $0 |
| Audit | SQLite | $0 |
| Audit archive | (skip) | $0 |
| API gateway | digiRunner Enterprise Standalone | quote — assume $1k-2k/mo annualized |
| Workflow | native Python orchestrator (Dify in shadow) | $0 |
| SSO | Keycloak self-host | $0 |
| OCR | Tesseract | $0 |
| PDF | pypdfium2 | $0 |
| Frontend | on-prem nginx | $0 |
| Observability | Sentry Team + Prometheus self-host | $29 |
| Logs | Loki self-host | $0 |
| Errors | (covered by Sentry) | — |
| Background jobs | arq | $0 |
| Metadata | SQLite → Postgres on first paying | $20 (managed Postgres dev tier) |
| Docketing | CSV manual | $0 |
| SAST | Semgrep OSS + Bandit | $0 |
| Pen-test | DEVCORE one-shot | $40k one-shot, amortise |
| PDF redact | PyMuPDF | $0 (or $10k/yr commercial license at scale) |
| Patent data | TIPO + USPTO bulk | $0 |
| Translation | Claude direct | (rolled into LLM line) |
| **Total run-rate** | | **~$250-550/mo + $40k one-shot + digiRunner license** |

### "Enterprise opex" stack (tier-1 firm under contract)

| Component | Enterprise choice | Monthly cost |
|---|---|---|
| LLM | Anthropic Sonnet+Haiku + OpenAI fallback + Qwen-on-prem | $6-15k |
| Local LLM | vLLM Llama 3.3 70B on H100 | $1,800 |
| Embeddings | bge-m3 + Voyage-3 optional | $200-500 |
| Vector DB | Qdrant Hybrid Cloud OR 3-node K8s | $500-1,500 |
| Cache | Valkey 8 HA | $200 |
| Audit | Postgres 16 HA (Patroni) | $400 |
| Audit archive | S3 Object Lock Compliance | $100 |
| API gateway | digiRunner HA | quote — assume $5-10k |
| Workflow | Dify 1.6 self-host | $400 (infra) |
| SSO | Keycloak HA federated to firm IdP | $200 |
| OCR | Azure Document Intelligence (non-conf) + PaddleOCR (conf) | $100 |
| PDF | PyMuPDF commercial + Marker | $850 (Artifex amortized) |
| Frontend | on-prem nginx | $0 |
| Observability | Prom + Grafana + Honeycomb opt-in + Sentry Business | $500-2,000 |
| Logs | Loki cluster OR Elastic self-host | $500 |
| Errors | Sentry self-host OSS | $200 (infra) |
| Background jobs | arq + Temporal self-host | $300 |
| Metadata | Postgres 16 HA (shared with audit) | (shared) |
| Docketing | Anaqua AQX + CPi + Townes connectors | $0 (eng amortized) |
| SAST | Semgrep AppSec + Snyk SCA | $300 (5 contributors) |
| Pen-test | DEVCORE annual + NCC Group pre-onboard | $80-150k/yr amortized |
| PDF redact | Foxit PDF SDK | $200 |
| Patent data | TIPO + USPTO + EPO OPS + Lens + IFI CLAIMS | $1-3k |
| Translation | DeepL Pro + Azure fallback | $50-200 |
| **Total run-rate** | | **~$25-50k/mo + pen-test amortization** |

---

## TPIsoftware-bundled-or-adjacent products (the partner-leverage axis)

TPIsoftware's public portfolio per [tpisoftware.com/en/products](https://www.tpisoftware.com/en/products) and the [PRNewswire COMPUTEX 2026 announcement](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html):

| TPIsoftware product | What it does | Maps to our component |
|---|---|---|
| **digiRunner** | API + AI gateway, OIDC, mTLS, managed AI key vault, rate limiting, observability per [TPIsoftware product page](https://www.tpisoftware.com/en/products/digirunner) | #8 API gateway, #10 SSO (built-in OIDC) |
| **digiLism** (iPaaS Middle Platform) | Replaces ESB; data transformation, protocol change for legacy mainframe → modern API per [digiLism page](https://www.tpisoftware.com/en/products/digilism) | #19 docketing integration (if we lean on it for legacy-system protocol bridges) |
| **digiLogs** | Tracing + EDR + RCA + hybrid alerts on massive log data | #14 observability, #15 logging — could displace Prom+Loki if TPIsoftware bundle includes it |
| **digiMars** | MongoDB Community enhancement: metrics, monitoring, backup/restore | (we don't use MongoDB; n/a) |
| **Dify** (TPIsoftware partner — not own IP) | LLM workflow editor | #9 orchestration |

**Implication.** The "partner column" of the master table is materially populated for components #8, #9, #10, #14, #15. That's **five of 24** components where a partner provides the stack. This reduces our engineering burden AND has a GTM benefit — we are the patent-vertical layer on top of their horizontal AI-enterprise platform, which is exactly the story they pitched at COMPUTEX 2026 ("All-in-One Solutions for Enterprise AI Adoption").

**What we DON'T see in their portfolio (and could be opportunity).** No vector DB. No OCR. No Postgres-replacement audit. No identity vault (Keycloak-class). No embeddings model. No PDF SDK. These remain our build/buy decisions independent of the partnership.

---

## End report — the three components where wrong choice kills us, three to swap immediately, one surprising partner play

### Three components where the WRONG choice would kill us

1. **API gateway (#8).** Going all-in on digiRunner is a partner bet; if TPIsoftware deprioritises us or their AI-gateway roadmap slips, every other security control we built (Q18 rate limit, Q12 SSO, Q11 prompt-injection at the edge) becomes our problem on a short timeline. **Mitigation discipline:** thin-gateway carve-out must remain working in code (PHASE3_MIGRATION.md §8) and 5 consecutive CI green runs are not optional before legacy-path deletion.
2. **Audit storage (#6).** Once a regulator hash-walks our chain and rejects it, the company is over. Any backend swap that breaks chain reproducibility is fatal. **Mitigation:** never use vendor-specific SQL in the audit insert path; archive every row to S3 Object Lock from week one of paid (yes, before SQLite-to-Postgres migration); write the chain verifier as a single-file Python script with no framework dependencies so it remains runnable in 10 years.
3. **LLM provider routing for confidential cases (#1, #2).** If a confidential OA leaks to Anthropic's cloud — even once — we lose the customer and probably the firm. **Mitigation:** the `LOCAL_LLM_FOR_SECURITY_LEVELS` assert in `llm_client.py` stays in code, defense-in-depth, even after Dify IF/ELSE branch adds the same check; audit row records `policy_decisions.local_lm_used=true` so we can verify cross-check (per PHASE3_MIGRATION.md §9 critical risk row).

### Three components to swap immediately for cost/quality

1. **Cache → Valkey** (not Redis). Redis went AGPLv3 in May 2025; we're a closed-source SaaS. Even though we don't ship Redis as part of our product, the AGPL footprint on our infra raises legal questions during firm procurement review. Valkey is the BSD-licensed fork backed by AWS/Google/Oracle/Linux Foundation. Migration is a config flip. **Do it before first paying customer.**
2. **PDF extraction → pypdfium2** (instead of pdfplumber or PyMuPDF AGPL). pypdfium2 is fast (PDFium-backed), Apache 2.0 + BSD-3 licensed, no commercial-license trap. PyMuPDF AGPL is a footgun for a closed-source SaaS unless we pay Artifex's ~$10k/yr. **Do it as part of the PDF upload feature ship.**
3. **TGI removed from any roadmap** (replace consideration with vLLM). Hugging Face's TGI went into maintenance mode 11 Dec 2025 — if "TGI" appears in any planning doc as a serious option, it's stale. **vLLM is the production answer**, full stop.

### One surprising "we should partner" opportunity

**Anaqua docketing as a wedge** — but flipped. Conventional read: Anaqua is the gatekeeper, we integrate as a tool. Surprising read: Anaqua explicitly **resists** best-of-breed integrations per [Black Hills' Anaqua connectors page](https://blackhills.ai/ip-automation/automated-ip-integrations/anaqua/), which means *firms using Anaqua are stuck with no AI OA-response option inside their docketing UI*. We can offer **PatentMind-inside-Anaqua-via-CSV** as the first AI tool that plays nice with Anaqua's policy — and pitch it to the ~half-of-top-100-US-patent-filers who use Anaqua AQX. That's a 50-customer pipeline opened by accepting Anaqua's restrictive integration model rather than fighting it. Equally, on the TW side, **TPIsoftware partnership** is the obvious one already in the plan — but the under-rated partner is **TIPO itself**: TIPO publishes free bulk data and would benefit reputationally from a TW-built AI assistant that demonstrably grounds its claims in TIPO XML. A co-marketing arrangement (no money) where TIPO mentions us as a "TIPO-data-grounded responder" would be worth more than any paid channel.

---

## Sources

- [Anthropic official pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [BenchLM Claude API pricing 2026](https://benchlm.ai/blog/posts/claude-api-pricing)
- [Finout 2026 Anthropic guide](https://www.finout.io/blog/anthropic-api-pricing)
- [MarkTechPost 2026 vector DB ranking](https://www.marktechpost.com/2026/05/10/best-vector-databases-in-2026-pricing-scale-limits-and-architecture-tradeoffs-across-nine-leading-systems/)
- [LeanOps 2026 vector DB cost comparison](https://leanopstech.com/blog/vector-database-cost-comparison-2026/)
- [TPIsoftware digiRunner product page](https://www.tpisoftware.com/en/products/digirunner)
- [TPIsoftware digiLism iPaaS](https://www.tpisoftware.com/en/products/digilism)
- [TPIsoftware product portfolio](https://www.tpisoftware.com/en/products)
- [TPIsoftware COMPUTEX 2026 announcement](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html)
- [digiRunner Capterra](https://www.capterra.com/p/10015814/digiRunner/)
- [Reintech embedding models 2026](https://reintech.io/blog/embedding-models-comparison-2026-openai-cohere-voyage-bge)
- [PE Collective embedding model specs 2026](https://pecollective.com/tools/text-embedding-models-compared/)
- [Keycloakpro Auth0 vs Okta cost 2026](https://keycloakpro.com/blog/keycloak-vs-auth0-vs-okta-cost-comparison)
- [Better Stack Datadog vs Sentry 2026](https://betterstack.com/community/comparisons/datadog-vs-sentry/)
- [Sentry pricing comparison](https://comparetiers.com/tools/sentry)
- [Spendhound Honeycomb pricing 2026](https://www.spendhound.com/marketplace/honeycomb-pricing)
- [aiproductivity Document AI cost 2026](https://aiproductivity.ai/blog/document-ai-cost-comparison/)
- [AWS Textract pricing](https://aws.amazon.com/textract/pricing/)
- [Anaqua official site](https://www.anaqua.com/)
- [Anaqua acquires Patrix](https://www.anaqua.com/resource/anaqua-acquires-patrix-what-this-means-and-why-it-matters/)
- [Black Hills Anaqua integration analysis](https://blackhills.ai/ip-automation/automated-ip-integrations/anaqua/)
- [Cachee 2026 cache comparison](https://cachee.ai/cache-comparison-2026)
- [Singh Redis vs DragonflyDB vs KeyDB 2026](https://singhajit.com/redis-vs-dragonflydb-vs-keydb/)
- [tech-insider vLLM vs Ollama 2026](https://tech-insider.org/vllm-vs-ollama-2026/)
- [Medium self-hosting Llama 3.1 70B](https://abhinand05.medium.com/self-hosting-llama-3-1-70b-or-any-70b-llm-affordably-2bd323d72f8d)
- [BuildMVPFast translation API 2026](https://www.buildmvpfast.com/api-costs/translation)
- [Konvu Semgrep vs CodeQL](https://konvu.com/compare/semgrep-vs-codeql)
- [DEV.to Snyk pricing 2026](https://dev.to/rahulxsingh/snyk-pricing-in-2026-free-plan-team-business-and-enterprise-costs-breakdown-5e88)
- [USPTO Open Data Portal](https://data.uspto.gov/)
- [WIPO Open Source Patent Analytics manual](https://wipo-analytics.github.io/manual/databases.html)
- [Top 4 Patent Search APIs](https://projectpq.ai/best-patent-search-apis-2025/)
- [Judoscale Python task queues](https://judoscale.com/blog/choose-python-task-queue)
- [pdfmux PDF extraction benchmark](https://pdfmux.com/blog/pdfmux-vs-pymupdf-vs-marker-vs-docling/)
- [arXiv PDF parsing comparative study](https://arxiv.org/pdf/2410.09871)
- [DEVCORE Taiwan offensive security](https://devco.re/en/)
- [Stingrai 2026 pen-test rankings](https://www.stingrai.io/blog/best-penetration-testing-companies-2026)
- [Zuplo API gateway pricing 2026](https://zuplo.com/learning-center/api-gateway-pricing-comparison-2026)
- [HostAdvice n8n vs Dify](https://hostadvice.com/blog/ai/automation/n8n-vs-dify/)
- [Dify v1.6 two-way MCP](https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support)
- [AWS S3 Object Lock](https://aws.amazon.com/s3/features/object-lock/)
- [oneuptime ClickHouse audit log](https://oneuptime.com/blog/post/2026-03-31-clickhouse-audit-trail-data-changes/view)
- [DEV.to TimescaleDB vs ClickHouse](https://dev.to/polliog/why-i-chose-postgres-timescaledb-over-clickhouse-for-storing-10m-logs-1e18)
- [DevToolReviews Cloudflare vs Vercel vs Netlify 2026](https://www.devtoolreviews.com/reviews/vercel-vs-netlify-vs-cloudflare-pages-2026)
- [G2 Foxit PDF SDK reviews](https://www.g2.com/products/foxit-pdf-sdk/reviews)
- [Foxit Redaction product page](https://developers.foxit.com/add-ons/redaction/)
- Internal references: [DECISIONS.md](./DECISIONS.md), [PHASE3_MIGRATION.md](./PHASE3_MIGRATION.md), [PRODUCT_STRATEGY.md](./PRODUCT_STRATEGY.md), [SECURITY_AUDIT.md](./SECURITY_AUDIT.md), [CLAUDE.md](../CLAUDE.md), `backend/shared/config.py`
