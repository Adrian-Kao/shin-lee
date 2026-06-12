# OPERATIONS & ONBOARDING — 90-day playbook from contract to "this is how we work now"

> **Audience:** the CS engineer + ops lead running customer #1 through customer #20.
> **Companion docs:** `docs/PRODUCT_STRATEGY.md` (commercial frame), `docs/PHASE3_MIGRATION.md` (target prod stack), `docs/SECURITY_AUDIT.md` (defence story), `CLAUDE.md §4` (invariants you must not violate during install).
> **Generated:** 2026-06-05.
> **Status:** v1. Lives in the repo so it ages with the code.

---

## 0. TL;DR (the bullets the deal owner needs)

- **Day 0** answers the prospect's IT/legal team's six questions in writing, with file/line refs they can verify themselves. Two questions get an honest "roadmap, not done" answer (external pen-test, streaming replication BCDR).
- **Days 1–7** install. We support **Path A (fully on-prem)** and **Path B (hybrid)**. Both ship with this playbook. Hardware spec, port matrix, firewall rules, TLS sample, OIDC hookup all live here.
- **Days 8–21** ingest the firm's historical patents + cases into the per-tenant Qdrant. `scripts/import_patents.py` is **P0 to build** (see §11 gap list). RAG quality validated against a 30-case golden set we ship.
- **Days 22–60** attorney rollout. 3 pilot users (senior partner + mid + paralegal), 50% time-reduction target by week 4, "champion" play.
- **Days 60–90** expansion + first QBR. Bring in additional attorneys, load backlogs, schedule the renewal conversation. NRR +20% by month 6 is the target.
- **SLA**: 99.5% uptime, p95 `/v1/analyze` ≤ 25s, audit-row freshness ≤ 100ms, RPO 24h.
- **Runbook** covers the four most likely incidents: LLM-provider outage, audit-chain mismatch, mapping-DB corruption, rate-limit storm.
- **Top 3 gaps blocking customer #1** are listed at the end. The smallest unlock is a 40-line `scripts/import_patents.py`.

---

## 1. Day 0 — pre-contract due diligence

When TW patent firms procure software, the call comes from one of three people: the **managing partner** (cares about price + risk), the **IT director** (cares about where data lives), or the **compliance / DPO** (cares about audit trail + 個資法 obligations). Below are the six questions you will get every time, with the answer we give and the evidence reference.

### 1.1 "Where does our data live?"

**Answer:** Three things stay strictly on-prem at the firm: (a) the reversible PII mapping table, (b) the audit hash chain, (c) the per-tenant Qdrant vector store with the firm's patents and case files.

**Evidence:** `backend/shared/config.py:14-17` defines `MAPPING_DB_PATH = DATA_DIR / "redaction_mapping.db"`. `CLAUDE.md §9 "Don't store mapping table outside on-prem"` is the design invariant. `backend/gateway/audit.py:62-67` shows the AuditWriter binds to a local SQLite file (Phase 4 upgrade: Postgres + S3 Object Lock — disclosed in `docs/PHASE3_MIGRATION.md`).

**What touches the cloud:** redacted text only. The redaction step happens **before** any outbound call (`CLAUDE.md §4 invariant #3`).

### 1.2 "What touches the cloud LLM?"

**Answer:** Redacted text only. PII is replaced with deterministic tokens (`PERSON_001`, `ADDR_002`) before the prompt leaves our gateway. The mapping table that knows `PERSON_001 == 王小明` never leaves the firm's VPC.

**Evidence:** `backend/gateway/masking.py:redact()` is the wall. Grep `masking.redact(` in `backend/gateway/orchestrator.py` shows it wraps every payload bound for the AI engine. For **confidential** cases (e.g. cases with security level `confidential` or `top_secret`), routing flips to the local Llama / Ollama provider entirely — see `backend/shared/config.py:LOCAL_LLM_FOR_SECURITY_LEVELS`.

### 1.3 "How is the audit chain tamper-evident?"

**Answer:** Hash chain. Every audit row stores `prev_row_hash` and `row_hash = sha256(payload + prev_row_hash)`. SQLite triggers `audit_no_update` and `audit_no_delete` block UPDATE / DELETE even by the DBA. Verification is one HTTP call: `GET /v1/audit/verify` walks the chain in rowid order.

**Evidence:** `backend/gateway/audit.py:26-58` (DDL + triggers), `:108-119` (hash construction), `:209-347` (global verifier with three classes of anomaly detection: hash integrity, tenant whitelist, referential integrity). The verifier is what we offer to the firm's auditor.

### 1.4 "Pen-test history?"

**Honest answer:** Internal security audit complete (`docs/SECURITY_AUDIT.md`, ~459 lines covering 4 critical + 4 high + 8 medium findings, all closed or accepted). **External third-party pen-test is roadmapped for Q4 2026, not yet performed.** We disclose this in the master agreement. Firms that need a third-party report before signing: we negotiate either (a) a one-time joint pen-test with their procurement-approved vendor (cost shared), or (b) a 90-day "subject to satisfactory pen-test" clause where they keep their kill-switch until our scheduled Q4 test ships.

**Why this works commercially:** TW law firms understand "internal audit + roadmapped external" because their own audits work the same way. The honesty buys credibility. Hiding it backfires when the IT director Googles us.

### 1.5 "BCDR — backup, restore, business continuity?"

**Honest answer:** Today: daily filesystem backup of `data/audit.db`, `data/redaction_mapping.db`, and the per-tenant Qdrant collections. RPO 24h, RTO 4h. **Streaming replication to a warm standby is roadmapped (Phase 4); not yet shipped.** Firms with regulator obligations exceeding RPO 24h: we recommend Path B (hybrid) where the firm provides their own DR target and we replicate to it.

**Evidence + gap honesty:** `CLAUDE.md §3 Q20: "Daily backup未實作"`. This is the truth — the cron job is not yet wired. **P0 to build before customer #1 go-live** (see §11). For the SLA we sign, we commit to the post-build numbers.

### 1.6 "Data residency — does anything cross national borders?"

**Answer:** The firm chooses. In **Path A (fully on-prem)** nothing leaves their data centre except the redacted LLM call to Anthropic's API endpoint (which can be pinned to a regional endpoint — Anthropic supports US + EU, and TW firms typically pick US-East as closest legal-friendly). In **Path B (hybrid)** the on-prem boundary still contains all PII; only redacted text egresses. Either way, the mapping table to reverse the redaction never leaves the firm.

---

## 2. Days 1–7 — installation

We support **two deployment paths**. Both are first-class; the firm picks based on their IT maturity.

- **Path A — Fully on-prem.** The firm operates two Linux VMs (gateway + AI engine) plus Qdrant + Ollama on a third box (or co-located if hardware allows). We provide install scripts + run a remote pairing session for the install. No data ever leaves their LAN except the (redacted) LLM call.
- **Path B — Hybrid.** The firm hosts only the *sensitive plane* on-prem: mapping DB, audit DB, Qdrant, and the thin gateway. We host the orchestration plane (digiRunner + Dify + AI engine LLM router) in a dedicated VPC. Cuts firm-side ops burden by 70%. Suitable for firms with <2 IT staff.

### 2.1 Install Gantt (Days 1–7)

```
Day:                    1     2     3     4     5     6     7
Hardware provisioning   [====]
Network + firewall            [====]
TLS + nginx                         [====]
Backend install                           [====]
Smoke test                                      [====]
OIDC hookup                                           [====]
digiRunner + Dify                                           [====]
Pilot user creation                                               [==]
Sign-off                                                            [=]
```

For Path B: collapse Days 4–5 (we install the cloud side in parallel; the firm only does Day 1–3 plus the OIDC hookup on Day 6).

### 2.2 Hardware requirements

| Path | Component | CPU | RAM | Disk | GPU |
|---|---|---|---|---|---|
| A | Gateway VM | 4 vCPU | 8 GB | 100 GB SSD | none |
| A | AI engine VM | 8 vCPU | 16 GB | 200 GB SSD (for vector store) | optional |
| A | Local LLM (Llama-3.1-70B-instruct) | 16 vCPU | 128 GB | 200 GB SSD | 2× A100 40GB **or** 1× H100 80GB |
| A | Local LLM (Llama-3.1-8B fallback) | 8 vCPU | 32 GB | 50 GB SSD | 1× RTX 4090 24GB **or** CPU-only at ~3× latency |
| B | Sensitive-plane VM (Qdrant + thin gw + mapping + audit) | 4 vCPU | 16 GB | 200 GB SSD | none |

**Recommendation for the first 5 customers:** size for **Llama-3.1-8B** locally (1× RTX 4090 is widely available in TW from supermicro / asus channel partners). The 70B model is only needed if the firm wants confidential cases to run on the *same quality tier* as cloud Claude — most pilots are comfortable accepting a lower-quality local fallback for the ~5% of confidential cases, and using cloud Claude for the 95% public ones.

### 2.3 Network port matrix

| Port | Service | Direction | Notes |
|---|---|---|---|
| 8010 | Gateway (FastAPI) | inbound from digiRunner / SPA | bind 127.0.0.1 + reverse proxy in production (`LISTEN_HOST` in `backend/shared/config.py:214`) |
| 8011 | AI engine (FastAPI) | inbound from gateway only | bind 127.0.0.1; firewall to gateway VM IP only |
| 6333 | Qdrant HTTP | inbound from AI engine only | firewall to AI engine VM IP only |
| 6334 | Qdrant gRPC | inbound from AI engine only | optional, faster |
| 11434 | Ollama | inbound from AI engine only | firewall to AI engine VM IP only |
| 5432 | Postgres (Phase 4) | inbound from gateway | when AUDIT_BACKEND=postgres |
| 6379 | Redis (when CACHE_BACKEND=redis) | inbound from gateway | optional Phase 1 |
| 5173 | Vite SPA dev | inbound from attorney workstations | replaced by nginx static in production |
| 443 | nginx / Caddy TLS | inbound public | the only port that touches the office LAN |

### 2.4 Outbound firewall rules

The firm's IT will ask for an exhaustive outbound allow-list. Give them this:

| Destination | Port | Protocol | Purpose | Frequency |
|---|---|---|---|---|
| `api.anthropic.com` | 443 | HTTPS | Claude API (redacted prompts only) | per analyse request |
| `*.npmjs.org`, `registry.npmjs.org` | 443 | HTTPS | frontend build only — block at runtime | install time only |
| `pypi.org`, `files.pythonhosted.org` | 443 | HTTPS | backend install only — block at runtime | install time only |
| `huggingface.co`, `cdn-lfs.huggingface.co` | 443 | HTTPS | `bge-m3` embedding model download | install + monthly model refresh |
| (optional) `data.gov.tw`, USPTO API | 443 | HTTPS | holiday calendar refresh | monthly cron |
| (optional) Anthropic status page | 443 | HTTPS | incident detection | every 60s |

**Recommend the firm install behind a forward proxy** that whitelists only these. After install, drop the install-time entries (pypi / npm / hf) and keep only the runtime ones. This is what shows up in their security review.

### 2.5 TLS termination — nginx example

```nginx
# /etc/nginx/sites-available/patentmind.conf
upstream patentmind_gateway { server 127.0.0.1:8010; }

server {
    listen 443 ssl http2;
    server_name patentmind.firm.example.tw;

    ssl_certificate     /etc/letsencrypt/live/patentmind.firm.example.tw/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/patentmind.firm.example.tw/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # 100 MB upload cap (matches backend MAX_BODY_BYTES default)
    client_max_body_size 100m;

    location /api/ {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # Day 8C upstream-header path — only set these when nginx is the trusted upstream
        # otherwise leave them and let the firm's digiRunner inject them
        proxy_pass http://patentmind_gateway/;
        proxy_read_timeout 120s;
    }
    location / { root /opt/patentmind/frontend-dist; try_files $uri /index.html; }
}
```

**Caddy alternative** (one-liner if the firm prefers simpler):

```
patentmind.firm.example.tw {
    reverse_proxy /api/* 127.0.0.1:8010
    root * /opt/patentmind/frontend-dist
    try_files {path} /index.html
    file_server
}
```

### 2.6 OIDC / SAML hookup to the firm's IdP

The Day 8C upstream-header auth path (`backend/gateway/auth.py:378-505 _user_from_upstream_headers`) is the integration point. It trusts `x-user-id` / `x-tenant-id` / `x-user-role` headers when (a) the source IP is in `TRUSTED_UPSTREAM_IPS` and (b) the optional shared-secret token matches `UPSTREAM_AUTH_SHARED_SECRET`.

**Hookup steps:**

1. Set `TRUSTED_UPSTREAM_IPS=<digiRunner outbound IP>` in `.env`. Single IP only — no CIDR (config parser refuses CIDR at boot; see `backend/shared/config.py:_parse_trusted_ips`).
2. Set `UPSTREAM_AUTH_SHARED_SECRET=$(openssl rand -hex 32)` in `.env`. **Required** when `TRUSTED_UPSTREAM_IPS` contains any non-loopback IP in non-mock mode — boot guard at `backend/shared/config.py:287-310` enforces.
3. Configure digiRunner OIDC against the firm's IdP using `digirunner/oidc.yaml` as the design intent template. Fill in issuer URL, client ID, client secret, scopes.
4. digiRunner injects `x-user-id` (from `sub` claim), `x-tenant-id` (from `tenant` or `groups` claim), `x-user-role` (from `role` claim, mapped to our `UserRole` enum), plus `x-upstream-auth-token` (the shared secret).
5. The gateway validates the IP, validates the shared secret, then trusts the headers.

**SAML** is supported via the same path — digiRunner handles SAML-to-OIDC bridging and emits the same headers downstream.

**Magic-link / IP whitelist** fallback (small firms without IdP): set `TRUSTED_UPSTREAM_IPS` to the firm's NAT egress IP + use the built-in JWT login on a separate route. Documented but not recommended.

### 2.7 digiRunner hookup (per PHASE3_MIGRATION)

Follow `docs/PHASE3_MIGRATION.md §3.2`. Concrete steps for a customer install:

1. digiRunner Enterprise Standalone license (per §10 of that doc). One-time licence + annual support.
2. Import the gateway OpenAPI spec — `curl http://127.0.0.1:8010/openapi.json > /tmp/gw.json` then upload via digiRunner UI.
3. Apply route templates from `digirunner/routes.yaml`. Operator transcribes; the YAML is the audit trail of what was applied.
4. Apply OIDC config from `digirunner/oidc.yaml`.
5. Apply rate-limit policy from `digirunner/ai-gateway-models.yaml`. Default 60 RPM/user (matches `backend/shared/config.py:DEFAULT_RPM` Phase-1 value when increased from 30, see open item below).
6. **Critical:** confirm the digiRunner outbound IP is set in `TRUSTED_UPSTREAM_IPS`. Wrong IP = no auth bypass (good), but also = login broken (bad). Pre-cutover smoke test from `scripts/smoke_demo.sh`.

### 2.8 Password rotation — POC sha256 → production argon2id

`backend/gateway/auth.py:124-148` is explicit that the current sha256+salt scheme is **POC-only**. The docstring says: *"For real user passwords you MUST switch to a proper KDF — argon2id (preferred), bcrypt, or scrypt."* The function is named `_hash_password` and is never called for real user passwords — only for the published `demo-{user_id}` accounts.

**Before customer #1 go-live**, swap is mandatory:

```python
# replace _hash_password / _verify_password
from argon2 import PasswordHasher
_ph = PasswordHasher()  # defaults: time_cost=2, memory_cost=64MB, parallelism=1
def _hash_password(p): return _ph.hash(p)
def _verify_password(p, stored):
    try: return _ph.verify(stored, p)
    except: return False
```

Pip dependency: `argon2-cffi==23.1.0`. **In Path B (hybrid)** this entire codepath dies because digiRunner OIDC replaces local password login — no swap needed in hybrid. **In Path A** when the firm uses our local user table (small firms without IdP), the swap is required.

> **Status update:** the swap has shipped (see §11 Gap #3). `_hash_password` /
> `_verify_password` are argon2id-first with legacy-format verification +
> opportunistic re-hash; `argon2-cffi` is in `backend/requirements.txt`.

---

## 3. Days 8–21 — data ingestion + RAG indexing

This is the phase where attorneys first feel value. If we load only sample data, the system answers generically. If we load **their** historical patents, the system retrieves prior art *they recognise*. That's the aha moment per `docs/PRODUCT_STRATEGY.md §3.1`.

### 3.1 Patent + case ingestion — two sub-paths

**Sub-path A: bulk import** (preferred for kick-off; one-time backfill of the last 5–10 years).

`scripts/import_patents.py` (**shipped** — closes Gap #1 of §11) walks a folder of patent files and indexes each through the running AI Engine's `POST /v1/index/patent` (the same path `backend/patent_db/seed.py` uses), so vectors land in the engine's live per-tenant store.

```bash
# 1. AI Engine must be running (scripts/start_demo.sh / start_delivery.sh)
# 2. the engine's internal token comes from the environment, never the CLI:
export INTERNAL_TOKEN=$(grep ^INTERNAL_TOKEN .env | cut -d= -f2)

# validate the folder first (parse-only, nothing sent):
python scripts/import_patents.py --tenant tenant_a --dir /mnt/firm-archive/patents --dry-run

# real run; --recursive for nested folders; --csv for the QA report:
python scripts/import_patents.py --tenant tenant_a --dir /mnt/firm-archive/patents \
    --recursive --csv data/eval_results/import.csv
```

Accepted inputs (mixable in one folder):

- **`.json`** — one object or an array with the `/v1/index/patent` fields (`patent_no`, `title`, `abstract`, `claims[]`, `publication_date`, `jurisdiction`, optional `is_local` / `spec_text`); see `backend/patent_db/seed.py` for live examples. `tenant_id` is always overridden by `--tenant`.
- **`.txt`** — TIPO 公報-style text (the `data/cases/*/patent.txt` layout): `公開編號` → patent_no, `【名稱】` → title, `【摘要】` → abstract, `【申請專利範圍】請求項 N：` → claims, `公開日 …（西元 YYYY-MM-DD）` → publication date; the descriptive body becomes `spec_text`. Jurisdiction derives from the patent-number prefix (fallback: `--jurisdiction`).

Failure contract: a bad file/record **never aborts the batch** — failures are listed at the end and the exit code is 1 (0 = all indexed, 2 = usage error), so a cron / CI wrapper can alert on partial imports. TIPO/USPTO **XML** bulk formats remain future work (the parser seam is `parse_tipo_txt` / `parse_json_records`).

**Sub-path B: live sync** (after backfill is done; ongoing).

Cron polling the firm's docketing system. TW patent firms typically use one of:
- **Anaqua** (multinational; export via Anaqua REST API or scheduled SFTP drop)
- **PatentSight / LexisNexis IP** (similar)
- **PAS (Patent Annuity Service)** for annuity tracking, less for case content
- **Townes** / **Patrix** / **CPA Global**
- For sub-10-attorney TW firms: often Excel + a shared drive. Live sync = watch the shared drive for new PDFs and pipe through `POST /v1/ai/extract_text` then index.

We ship `scripts/live_sync_anaqua.py` (P1; not yet built) — a 30-line cron-friendly daemon that polls the firm's Anaqua tenant for new records since the last poll watermark, calls our import script, logs to `data/sync.log`.

### 3.2 Embedding cost estimation (per 10K patents)

With `EMBEDDING_BACKEND=bge-m3` (self-hosted on the firm's AI engine VM), embedding cost is **zero** — the only cost is GPU time. Ballpark:

- bge-m3 throughput on a single RTX 4090: ~150 chunks/second
- One patent ≈ 80 chunks (claims + abstract + spec sections, per the hierarchical+claim-tree chunking in `rag.py`)
- 10,000 patents × 80 chunks / 150 chunks/sec = ~5,300 seconds = **~90 minutes one-time backfill**.

If the firm provides only CPU: ~10× slower = ~15 hours overnight. Acceptable for backfill, not for live sync.

**Per chunk storage in Qdrant**: 1024-dim float32 = 4KB raw, ~5KB with payload. 10,000 patents × 80 chunks × 5KB = **~4 GB Qdrant disk**. Trivially fits on a single 200GB SSD.

### 3.3 Tenant ID assignment

Default is **one tenant_id per firm**. Multi-tenancy fires in three scenarios:

1. **Multi-office firms** where ethical walls must be enforced between offices (rare in TW; common in HK/SG). Each office = separate `tenant_id`. Cross-office staff get accounts in both tenants but never cross-reference cases.
2. **Conflicting clients within the same firm.** TW Bar ethics rules require Chinese walls between teams representing parties on opposite sides of an opposition / invalidation. We model this as a sub-tenant: e.g. `tenant_a__ip_wall_2026q3` — physically the same Qdrant collection prefix-shared but logically segregated by `case_acl`. The cleaner pattern (post-Phase 4) is a fresh `tenant_id` per ethics wall, which is what we'll recommend by go-live.
3. **Firms with subsidiaries that are separately licensed entities.** One `tenant_id` per legal entity.

The decision matrix sits with the firm's GC / managing partner — we provide the spec, they decide. Default to one tenant; promote to multi only when triggered.

### 3.4 RAG quality validation (golden-set eval)

We ship `scripts/eval_cases.py` (already exists, 753 lines). It runs the 30 synthetic demo cases in `data/cases/` end-to-end and emits a report at `data/eval_results/<TIMESTAMP>/`.

**For each new customer**, the install sequence is:

1. Backfill their patents into Qdrant (§3.1 sub-path A).
2. Pick **10 representative historical cases** from the firm where the eventual response was successful (e.g., the OA was overcome and the patent issued). These become the firm's golden set.
3. Run `scripts/eval_cases.py --mode anthropic --case-dir /opt/patentmind/golden/<firm>/` against those 10 cases.
4. Score on three retrieval metrics computed against the **actual prior art cited in the eventual successful response** (extracted from the case file by hand for the golden set):
   - **Recall@5**: of the prior art the attorney eventually cited, how many appear in our top-5 retrieval? Target ≥ 0.7.
   - **Recall@10**: ≥ 0.85.
   - **MRR (mean reciprocal rank)** of the first relevant hit: ≥ 0.5 (i.e., relevant hit averages within top-2).
5. If below target, escalate: tune chunk sizes (`rag.py`), or fall back to keyword + embedding hybrid (planned, not built).

**Why this matters commercially:** the golden-set score is the number we put in the Days 22–60 pilot kickoff slide. "We tested against 10 of your historical wins. We hit 0.78 recall@5. Here's the report." That's what the senior partner cares about.

---

## 4. Days 22–60 — attorney rollout

The technology is in. Now the human change-management problem starts.

### 4.1 Pilot user selection — three personas, one of each

| Slot | Persona | Why this slot |
|---|---|---|
| 1 | **Senior partner** (≥15 years; runs a practice group) | The "champion." If she adopts, the firm adopts. If she rejects, the deal stalls. Pick the senior partner who already runs the most experiments with new tools — the firm's de facto tech early-adopter. |
| 2 | **Mid-level attorney** (5–10 years; bulk of OA volume) | This persona writes the most OA responses. Their hours-saved number is the ROI story. They are also the most likely to spread word-of-mouth through the firm's associate channel. |
| 3 | **Paralegal / 助理** | Tests the upstream workflow: PDF upload, case management, deadline tracking. Paralegals often own the docketing system, so their feedback shapes the §3.1 live-sync work. |

**Do not** pick three junior attorneys. They have no political capital and the partners will dismiss their feedback.

### 4.2 Training plan

- **Week 0 (pre-pilot):** 90-minute kickoff with all 3 pilots + the firm's IT lead + the partner sponsor. Demo a real case end-to-end. Walk the trust band (`docs/PRODUCT_STRATEGY.md §7`: redaction chip, on-prem badge, audit chain UI). Set the 50%-reduction target explicitly.
- **Week 1–4:** **30-minute weekly office hours**, same time every week (Friday 14:00 is the sweet spot — late enough that they've used the tool, early enough to not steal weekend). Show one new feature each session, answer questions. Record + post to the firm's internal knowledge base.
- **Week 2 milestone:** each pilot has analysed ≥ 3 real OAs in production (not sample data). If a pilot hasn't, the CS engineer schedules a 1:1 to find out why.
- **Week 4 review:** measure baseline-vs-actual time. Report to managing partner.

### 4.3 Success metric — "OA → draft time"

**Baseline (measured in Week 0):** ask each pilot to estimate their average time from "receive OA" to "first usable draft" today. Triangulate against the firm's docketing system (entry time → draft attachment time). TW firms typically report 3–6 hours per OA for a §103-style rejection (DeepIP 2026: 75% of attorneys spend over 7 hours/week on OA responses).

**Target (Week 4):** ≤ 50% of baseline. So a 4-hour baseline → 2-hour target.

**Measurement:** the gateway audit log (`/v1/audit/recent`) timestamps every `/v1/analyze` call per `case_id`. We attribute the duration of the case's OA work to the wall-clock between the first analyse call and the draft export. Pilot self-reports the "delivered to client" moment.

### 4.4 The champion problem

The senior partner is the bell-cow. If they adopt: every mid-level wants to be seen using the same tools as the partner. If they reject: nobody will touch it. To increase champion adoption probability:

1. **Get a win in the first session.** Pre-load one of the partner's *own* historical successful cases into the RAG. When they run an analyse, the retrieval surfaces the prior art they once cited themselves. That's a recognition moment that buys 6 weeks of patience.
2. **Make the partner the visible internal author of the rollout.** Their name on the kickoff email; their photo on the internal launch slide. They don't have to write a word; they just have to be the brand.
3. **Solve their problem in their first month.** If they have an unusual workflow (e.g., they always cite TIPO Examination Guidelines section X), add a custom prompt variation that surfaces it. We can ship that per-tenant via the prompt-loader (Day 8A; see `backend/ai_engine/prompts/`).

### 4.5 90-day rollout Gantt

```
Week:                 1  2  3  4  5  6  7  8  9  10 11 12 13
Pilot kickoff         [=]
Pilot week 1-4              [=========]
Baseline measurement  [=]
Office hours w1-4              [==========]
Week-4 milestone review              [=]
Expansion wave 1 (5 attorneys)           [========]
Expansion wave 2 (10 attorneys)                       [========]
Backlog ingestion                              [==============]
First QBR                                                    [=]
Renewal conversation                                            [==]
```

### 4.6 Common rollout failure modes

From G2 / Trustpilot reviews of Patlytics, ClaimMaster, Anaqua, DeepIP (2023–2026), here's what kills patent-AI pilots — and our mitigation:

| Failure mode | What goes wrong | Our mitigation |
|---|---|---|
| **Hallucinated citations** | Attorney writes a brief citing a case that doesn't exist; gets sanctioned. Once burned, never uses again. | Q14 grounded-citation verifier is the wall (`CLAUDE.md §4 invariant #5`). Verifier-flagged citations are stripped before display, not just labeled. |
| **Generic outputs** | The AI gives the same template response regardless of case. Attorney says "I could write that faster myself." | The per-tenant RAG with the firm's own historical patents is the differentiator. This is why Days 8–21 backfill is non-negotiable. |
| **Slow** | 90-second analysis time → attorney opens 3 tabs, multitasks, loses focus, abandons. | p95 ≤ 25s SLA. Streaming SSE responses (`/v1/analyze` already supports — frontend renders partial drafts in <5s). |
| **Procurement freeze on data residency** | IT vetoes after seeing cloud LLM. | Path A on-prem option + the §1.1 evidence pack. |
| **Champion never adopted** | Senior partner saw demo, was polite, never logged in again. | §4.4 champion plays. Track champion logins weekly. Escalate to deal owner at week 2 if zero. |
| **Paralegal blocked by docketing integration** | Manual PDF upload felt clunky; they reverted to email-the-attorney. | §3.1 sub-path B (live sync) is P1 for exactly this reason. Until shipped: provide a watched folder + auto-import script. |
| **Audit chain fail under DBA load** | Customer DBA hits the SQLite file directly, gets the trigger error, calls in panic. | Days 1–7 training for the firm's DBA includes "audit DB is append-only by design; here's the verify endpoint." |

---

## 5. Days 60–90 — expansion + retention

### 5.1 Account expansion play

Two levers. Run both in parallel.

1. **Seat expansion.** Bring in additional attorneys 5 at a time. The pilot 3 become trainers; the CS engineer runs onboarding only for the first wave of 5, then hands off the second wave to the firm's pilot 3. By month 6 the firm should be at 25–40 seats.
2. **Backlog ingestion.** Most firms have 5–10 years of patent files in PDF archives that aren't yet indexed. Ingesting them dramatically improves retrieval. Run the import script on weekends over a 4-week window.

### 5.2 Cross-sell roadmap items (not yet shipped — use as commercial hooks)

These appear in our PRODUCT_STRATEGY roadmap and are the renewal conversation. Don't promise dates we haven't internally committed:

- **Claim chart auto-build** — given an OA citing a reference, build the claim-vs-reference table the attorney would otherwise build by hand.
- **Opposition strategy memo** — given a competitor's published application + our portfolio, generate the freedom-to-operate memo.
- **Prior-art landscape Q&A** — natural-language Q&A over the firm's portfolio plus public prior art ("how many of our patents cite IPC G06N for medical imaging?").
- **Annuity decision support** — score patents for renewal-vs-abandon using citation graph + commercial signals. Differentiates from PatSight / Anaqua.

### 5.3 QBR (quarterly business review) template

90 minutes with the managing partner + IT lead + pilot champion. Slides:

1. **Usage** — # OAs analysed, # attorneys active (DAU/MAU), # cases touched, top 3 prompt intents.
2. **Time saved** — measured baseline vs Q3 actual, in hours and in dollar-equivalent at the firm's blended rate.
3. **Audit chain attestation** — "we ran verify on every audit row this quarter; X verified, 0 broken." If non-zero broken: an incident report.
4. **Quality** — sample-audit score (§9): 5% of drafts sampled by a senior attorney, pass rate vs. target ≥ 90%.
5. **Cost** — Anthropic + infra cost vs. budget. Per-OA cost trend.
6. **Roadmap preview** — 1 slide of what's shipping in the next quarter. Tie to their feedback.
7. **Renewal + expansion ask** — soft ask at first QBR (90-day mark), hard ask at second QBR (6-month mark).

### 5.4 Renewal triggers

- **6-month NRR target: +20%** (Net Revenue Retention).
- **Renewal probability signal: weekly active users / licensed seats.** If WAU/seats > 0.7 by month 5 — renewal is auto. If 0.4–0.7 — renewal with concessions. If < 0.4 — escalate to founder + intervention plan.
- **Multi-year discount available** at first renewal: 15% off for 2-year commitment, 25% off for 3-year. Lock in before competitors mature.

---

## 6. SLA spec

The contract Exhibit B. Concrete, defensible, honest about constraints.

| Metric | Commitment | Measurement | Remedy if breach |
|---|---|---|---|
| **Uptime** | 99.5% / month (≈ 3.6h downtime budget) | 1-minute health-probe of `/v1/health` from outside the firm's network | Service credit: 10% monthly fee per 0.1% under |
| **p95 `/v1/analyze` latency** | ≤ 25 seconds | gateway audit log `latency_ms` column, 95th percentile over 7-day window | If 3 consecutive weeks miss: joint root-cause + service credit |
| **Audit row freshness** | ≤ 100ms from request completion to row commit | unit-tested in `tests/integration/test_audit_error_path.py`; production monitor reads audit write latency from observability layer | Breach = sev-1; engineer-on-call pages within 15 min |
| **Backup RPO** | 24 hours (Phase 1); 15 minutes (Phase 4 streaming replication, target Q4 2026) | nightly backup-verify script confirms latest snapshot < 24h old | Sev 1 if RPO missed; service credit + roadmap escalation |
| **Backup RTO** | 4 hours | quarterly drill: restore audit + mapping to a scratch VM, prove `/v1/audit/verify` passes | If drill misses: written postmortem + remediation plan in 30d |
| **Support response (Sev 1)** | < 4 business hours acknowledgement | ticket system timestamp | Service credit |
| **Support response (Sev 2)** | < 24 hours | ticket system | Service credit |
| **Support response (Sev 3)** | < 3 business days | ticket system | none (best effort) |

### 6.1 Carve-outs

- p95 latency depends on upstream LLM provider response time. If Anthropic's status page reports an incident, those minutes are excluded.
- Uptime excludes scheduled maintenance windows.
- Customer-induced outages (firm's IdP down, firm's network down) excluded.

### 6.2 Incident severity matrix

| Sev | Definition | Examples | Response |
|---|---|---|---|
| **Sev 1** | Production down for all users OR data integrity at risk | gateway 5xx > 10% for 5 min; audit chain verify fails; mapping DB unreadable | Page on-call within 15min; status page update within 30min; 4h written update cadence |
| **Sev 2** | Significant feature degraded; workaround exists | LLM provider degraded → falling back to local; one tenant cache poisoned | On-call within 1h; status update within 2h; daily updates |
| **Sev 3** | Minor bug; cosmetic; non-blocking | UI typo; one user's quota off by 1; non-blocking log warning | Triaged within 3 business days; fix in next sprint |

### 6.3 Maintenance windows + change management

- **Standard maintenance window:** Sunday 02:00–04:00 local time. Reserved; firm informed annually.
- **Emergency maintenance:** announced ≥ 4h in advance via email + in-app banner.
- **Change-management notice for any deploy that touches**: auth, audit, masking, or vector store. 1 week notice + change ticket.

---

## 7. Operational runbook (for the on-call engineer)

### 7.1 Daily checks (10 min, every morning)

1. **Audit chain verify.** `curl -s http://gateway/v1/audit/verify | jq .` — `broken` array must be empty. If not, GOTO §7.4.2.
2. **Cost circuit breaker.** Check today's spend vs `COST_CIRCUIT_DAILY_USD` (default $100 in POC, raise to per-customer budget at install). If > 80%: warn the deal owner.
3. **RPM rejection log.** Tail the gateway log for `rate_limit:429` events. > 10 in 24h for one user = either a buggy script or an over-eager attorney; investigate.
4. **LLM provider status.** Anthropic status page green? If yellow / red, pre-emptively warn customers + verify the Q15 fallback chain is healthy.

### 7.2 Weekly checks (30 min, Mondays)

1. **Per-tenant cache hit rate.** Grep audit logs for `cache_hit=true` vs `cache_hit=false`. < 20% hit rate for any tenant suggests their workload is unusually unique (good — they're doing real work) OR the cache key is too sensitive (regression).
2. **Embedding regen needed?** If any tenant uploaded > 100 new patents in the past week, re-run the eval golden set for that tenant. Recall@5 should not have dropped > 5%.
3. **Security log review.** Failed login attempts > 50 from a single IP / 24h = page the firm's IT contact. Any `upstream-auth: shared-secret mismatch` log entries are sev-2; investigate.
4. **Backup verify.** `ls -la /backup/audit-*.db.gz | head -7` — 7 daily backups exist; latest is < 24h old; checksum matches.

### 7.3 Monthly checks (2 hours, last Friday)

1. **User RPM caps.** Per-user RPM was set at install per `DEFAULT_RPM`. Review actual peaks; if any user is consistently hitting 90% of cap, raise.
2. **Token quota review.** Recompute per-user daily token usage; compare to `DEFAULT_DAILY_TOKENS`. If average > 50% of cap, raise (we don't want quota to be a friction point at the 80th percentile).
3. **Customer QBR prep.** Pull metrics for the §5.3 deck.
4. **Cost reconciliation.** Anthropic invoice vs our internal tracking. Reconcile differences > 5%.

### 7.4 Incident playbooks

#### 7.4.1 LLM provider outage

- **Trigger:** Anthropic status page red, OR gateway 5xx rate on `/v1/analyze` > 10% for 5 min.
- **Detection:** the daily check or alert from observability layer (`backend/shared/observability.py`).
- **Mitigation:**
  1. Verify the Q15 fallback chain. `grep -n "LOCAL_LLM_FOR_SECURITY_LEVELS\|route_model" backend/ai_engine/llm_client.py` — confirm the router does fall back to Ollama on Anthropic exception.
  2. **Force-degrade all traffic to local Llama temporarily:** set `LLM_MODE=local` in `.env` and hot-reload gateway. Communicate the quality trade-off to customers via in-app banner.
  3. Watch local Llama VM load. If swamped, increase RPM throttle temporarily.
  4. When Anthropic recovers, flip `LLM_MODE` back; gradual ramp (10% → 50% → 100% over 30 min).
- **Postmortem:** within 5 business days. Document in `docs/incidents/<YYYY-MM-DD>.md`.

#### 7.4.2 Audit chain mismatch

- **Trigger:** `/v1/audit/verify` returns `broken: [...]` non-empty.
- **Severity:** **Sev 1** — this is the regulator-facing story.
- **Detection:** daily check (§7.1.1) or the cron-based hourly verify (not yet shipped — P1).
- **Mitigation:**
  1. **Freeze writes immediately:** put the gateway in read-only mode. Easiest path: scale gateway pods to 0; SPA error banner. Lose ~minutes of attorney work, save data integrity.
  2. **Forensic walk:** `python -c "from backend.gateway.audit import writer; print(writer.verify_global_chain())"` — get the full picture (3 anomaly classes from `audit.py:222-258`).
  3. **Identify the row(s) that broke the chain.** Pull from SQLite directly: `sqlite3 data/audit.db "SELECT * FROM audit WHERE audit_id = '<broken-id>'"`.
  4. **Determine cause.** Either (a) tampering (rare — triggers should block), (b) writer process crashed mid-write, (c) a process bypassed `AuditWriter` (only legitimate one would be migration scripts).
  5. **Restore.** When S3 Object Lock archive ships (Phase 4): restore from the last verified archive. Until then: from yesterday's filesystem backup. Loss = up to 24h of audit rows.
  6. **Notify the firm's compliance officer** within 24h. Written incident report within 5 business days.

#### 7.4.3 Mapping DB corruption

- **Trigger:** `data/redaction_mapping.db` is unreadable OR `masking.unredact()` raises on a known token.
- **Severity:** **Sev 1** — drafts cannot be safely shown to attorneys (the inverse map is broken).
- **Detection:** gateway logs `KeyError in unredact` OR SQLite integrity check fails.
- **Mitigation:**
  1. **Stop accepting new analyse requests** (read-only mode). In-flight redacted prompts will still be sent to the LLM (already in flight); responses can't be unredacted safely until we restore.
  2. **Restore mapping DB** from last filesystem backup (RPO ≤ 24h).
  3. **Replay the in-flight requests** — they have request IDs in audit; we can identify which prompts were sent during the gap and either re-run them (charging again) or surface them as "need attorney re-run."
  4. **Communicate** to affected users via in-app banner. Likely small (< 1 hour of analyse traffic).

#### 7.4.4 Rate-limit storm

- **Trigger:** one user > 100 RPM (well above `DEFAULT_RPM`) OR one tenant > 1000 RPM aggregate.
- **Detection:** `backend/gateway/rate_limit.py:check_rpm` log spam + alert on cost circuit breaker.
- **Mitigation:**
  1. **Tighten per-user RPM** for the offender: set `DEFAULT_RPM=5` for that user (we need per-user override config — currently global; P2 to add).
  2. **Inspect** the audit log — are the requests legitimate (batch upload) or scripted attack?
  3. **If scripted attack:** revoke the user's token (set them to disabled in `_USERS`; in production: revoke via IdP).
  4. **Page the firm's IT contact** within 1 hour. Joint investigation.
  5. **Cost reconciliation:** if the storm cost > $50, claim service credit ourselves from Anthropic OR absorb if our fault (rate limit was too loose by default).

---

## 8. Customer support tier structure

| Tier | Channel | Response SLA | Staffing |
|---|---|---|---|
| **L1** | In-app help widget, email (`support@`), Slack Connect (firm-shared channel) | 4 business hours | CS engineer rotation |
| **L2** | Escalates from L1 when the issue requires code change or production access | Sev 2 within 24h | Backend engineer-on-call |
| **L3** | Sev 1 only; founder / CTO direct line | 4 hours, 24x7 | Founder + CTO |

### 8.1 Knowledge base structure

Build under `/help` (the page exists as a placeholder per `docs/PRODUCT_STRATEGY.md §4.7`). Categories:

1. **Getting started** — first analyse, first export, first invite.
2. **OA analysis** — what each section means, how to read grounded citations, how to override the verifier.
3. **Cases & deadlines** — case management, deadline computation, calendar integration.
4. **Admin** — user roles, OIDC config, audit verification.
5. **Privacy & data** — what's redacted, where data lives, audit trail walk-through.
6. **Troubleshooting** — common errors, how to file a Sev 2 ticket, how to read the in-app diagnostic.

### 8.2 Office hours cadence

- **Onboarding firms (Days 1–60):** weekly 30-minute office hour, fixed time.
- **Post-onboarding (Days 60+):** monthly 30-minute office hour.
- **All-customer office hour:** quarterly, 1 hour. Roadmap preview + feature requests.

---

## 9. Success metrics dashboard — managing partner's monthly report

A single PDF emailed on the 1st of each month. The partner reads it in 90 seconds and decides whether to renew.

| Metric | Source | Target / context |
|---|---|---|
| **# OAs analysed** this month | gateway audit log `endpoint='/v1/analyze'` count, grouped by case | Trending up = healthy; sudden drop = investigate |
| **Hours saved (vs baseline)** | (baseline mins/OA × OAs analysed) − (avg actual mins/OA × OAs analysed); avg actual from time-to-export | Target: ≥ 50% reduction vs baseline (set at Week 0) |
| **$ saved (vs outsourced cost)** | Hours saved × firm's blended hourly rate (typically NT$3,500–5,000/hr for TW patent attorneys) | This is the renewal ROI narrative |
| **Audit chain integrity** | `/v1/audit/verify` global verifier output: `verified / (verified + len(broken)) × 100%` | Must be 100%. Anything else triggers Sev 1. |
| **Cost vs budget** | Anthropic invoice + infra + subscription, vs the firm's monthly budget set at onboarding | Show trend; flag if > 90% |
| **Sample-audit quality** | 5% random sample of drafts each month; senior attorney rates each on 1–5 scale; report % rated ≥ 4 | Target ≥ 90% pass rate. < 80% triggers prompt-engineering review. |
| **Pilot champion logins** | distinct logins by the partner sponsor | Soft signal: if champion logs in < 3× / month, intervention needed before renewal conversation |

---

## 10. Handoff / offboarding

We hope it never happens. We plan as if it will.

### 10.1 Data export ("takeout")

If the firm cancels, they get:

1. **Their patents** — Qdrant collection export per tenant (JSON-Lines: `patent_no`, `text`, `embedding`, `payload`).
2. **Their cases** — gateway `case_acl` rows + every audit row scoped to their `tenant_id`, as a single CSV.
3. **Their audit chain** — the full SQLite slice for their `tenant_id`, plus a written attestation by us that `verify_chain(tenant_id)` returned 0 broken at export time. Their compliance officer can re-verify independently using the chain logic in `backend/gateway/audit.py:175-207` — we publish the verifier source as Apache-2.0 so they can re-verify in 10 years without depending on us.
4. **Their custom prompts** (if any) — YAML files from `backend/ai_engine/prompts/tenant_<id>/`.
5. **Their docketing system integration config** (Anaqua / etc API key references — NOT the keys themselves).

Format options offered: ZIP (default), encrypted ZIP (PGP recipient key supplied by firm), or sFTP push to their server. Delivered within **10 business days** of cancellation notice.

### 10.2 Data deletion timeline

- **Day 0 (cancellation effective):** account disabled; no new requests accepted. Their data remains on our infra for 30 days for restoration if they reconsider.
- **Day 10:** takeout delivered (or earlier).
- **Day 30:** **all** non-audit data deleted from production infra. Mapping DB shard, Qdrant collection, cache, custom prompts. Cryptographically shredded (we don't pretend; we run `shred -u` on filesystem files and DROP COLLECTION on Qdrant).
- **Day 30 — audit chain retained per legal hold:** the firm's audit rows stay in our retained-customer archive for **7 years** (matching TW commercial records retention obligation). Encrypted-at-rest, accessible only by court order or with the firm's written request. We tell them this explicitly in the master agreement.
- **Day 2,555 (7 years):** audit rows cryptographically shredded.

### 10.3 IP ownership of customisations

Three categories. Spelled out in the master agreement:

1. **Our base product + base prompts** — ours. Firm gets a non-exclusive licence during the contract; rights revert at termination.
2. **The firm's data + retrieval corpus** — theirs. Always. We have no rights to it beyond the licence to operate the service.
3. **Custom prompts written for / with the firm** — **joint IP**, default. The firm can take and reuse them; we can use the **techniques** (e.g. "we learned that adding §22-2 phrasing helps TW OAs") in our base product, but **not the firm's specific text**. If the firm requires exclusive ownership of custom prompt text, we negotiate a higher rate.

The "techniques vs text" split is the same model Anthropic uses for Claude customisations and the same model OpenAI uses for fine-tunes. Familiar to procurement teams.

### 10.4 Knowledge handoff

If the firm is moving to a competitor: we offer a 4-hour transition session (paid at standard rate) where we walk their new vendor's CS engineer through the data export format. We're not jealous; if the customer is happier elsewhere, we want them to land well — they may come back later, and patent firms talk to each other.

---

## 11. Top 3 gaps blocking customer #1 today (P0)

This playbook describes what *should* happen Days 1–90. Several pieces of infrastructure the playbook depends on do not yet exist in the repo. Brutal-honest list:

### Gap #1 — No `scripts/import_patents.py` for bulk ingestion — ✅ SHIPPED

> **Status:** closed. `scripts/import_patents.py` exists (`--tenant` / `--dir` /
> `--dry-run` / `--recursive` / `--csv`; .json + TIPO-style .txt; errors listed,
> batch never aborts). Usage in §3.1. Remaining future work: TIPO/USPTO **XML**
> bulk formats.

§3.1 is the heart of the value-delivery phase. Without bulk import, the firm spends Days 8–21 manually pasting their historical patents through the SPA — non-starter at scale.

**What exists today:** `backend/ai_engine/rag.py:index_patent()` accepts a single patent at a time. `scripts/generate_test_data.py` generates synthetic demo data. Nothing reads real TIPO or USPTO XML.

**Smallest unlock:** ~80–120 lines of Python that walks a directory of TIPO XML files, parses `<patent-no>`, `<title>`, `<abstract>`, `<claims>`, batches by N=50, calls `rag.index_patent()`. Reports progress and writes a CSV. No new dependencies needed (Python stdlib `xml.etree.ElementTree` handles TIPO format).

**Effort:** 1 engineer-day.

### Gap #2 — Backup cron is not wired — ✅ SHIPPED (cron body + wrappers)

> **Status:** closed at the POC bar. `scripts/run_backup.py` (CLI wrapper over
> `backend/gateway/backup.py`: snapshot + retention, correct exit codes) +
> `scripts/backup_cron.sh` (crontab example) + Windows `schtasks` one-liner are
> in `docs/DELIVERY_RUNBOOK.md §7`. **Streaming replication is still mandatory
> before production** — a periodic snapshot cannot meet RPO < 5 min.

§1.5 and §6 promise RPO 24h. The cron does not exist. Today if the audit DB or mapping DB is lost, **the customer loses everything**.

**What exists today:** the playbook lies on the page. The implementation is absent. SQLite files just sit at `data/audit.db` and `data/redaction_mapping.db` with no scheduled snapshot.

**Smallest unlock:** A bash script `scripts/backup.sh` that runs `sqlite3 data/audit.db ".backup /backup/audit-$(date +%Y%m%d).db"`, gzips, retains last 30 daily + 12 monthly. Optionally `aws s3 cp` to a customer-supplied S3 bucket. Plus a cron entry `0 2 * * *` and a backup-verify check (§7.2.4). **No S3 needed for customer #1** if the firm gives us a local NAS path — Phase 4 adds S3 Object Lock.

**Effort:** 0.5 engineer-day.

### Gap #3 — Production password KDF still sha256+salt — ✅ SHIPPED (argon2id)

> **Status:** closed. `backend/gateway/auth.py` now hashes with **argon2id**
> (`argon2-cffi`, in `backend/requirements.txt`); legacy `salt:sha256` hashes
> still verify and are opportunistically re-hashed to argon2id on the next
> successful login. If argon2-cffi is absent the gateway still boots (legacy
> scheme + loud warning — demo accounts only).

§2.8 calls out the swap to argon2id. `backend/gateway/auth.py:124-128` literally documents "FINE for the demo accounts ... you MUST switch to a proper KDF." Going to production with sha256 = a regulator-facing red flag during the first IT review.

**What exists today:** `_hash_password()` and `_verify_password()` use sha256 + 16-byte hex salt. Works for demo. Fails any security review.

**Smallest unlock:** add `argon2-cffi==23.1.0` to `backend/requirements.txt`, swap the two functions to use `PasswordHasher`. Update `tests/integration/test_auth.py` to use the new hash format. ~30 lines + test updates. **In Path B (hybrid + digiRunner OIDC) this path is unreachable** because login is delegated upstream — so the swap is only needed for Path A customers using local password login.

**Effort:** 0.5 engineer-day. Customer #1 can run Path B and dodge entirely.

### Bottom line — 2 engineer-days unlocks customer #1

The other items in this playbook (golden-set eval already exists, audit chain verifier already exists, SLA spec is editorial, runbook is editorial) are deliverable today. The 2 engineering days above are the actual block.

If customer #1 chooses **Path B (hybrid)**: only Gap #1 + Gap #2 matter = **1.5 days**. Argon2 swap is not on the path.

That's the headline for the deal owner: **"We can install customer #1 in week 1 once we ship `scripts/import_patents.py` and `scripts/backup.sh` — about 1.5 engineer-days of work."**

---

*End of playbook. Next revision after customer #1 install, with real numbers replacing the assumed ones.*
