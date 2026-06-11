# PatentMind AI — POC（中文）

> **安全、自動化的專利 Office Action（OA）答辯分析平台**
> NCCU GDGoC × Computex 2026 ｜ [English README](README.md)
>
> 這個 repo 是 PatentMind AI 的 POC：完整 frontend + backend，把架構決策驗證到能跑端到端。
> Production hardening 清單見 `CLAUDE.md`。

## 為什麼存在

律師事務所做專利 Office Action 答辯：
- 看 OA、找 prior art、寫答辯狀，現在純人工，**1 件案 8–12 小時**
- 引用法源容易抄錯（幻覺風險）
- 期日算錯就完蛋
- 客戶資料絕對不能外流

PatentMind 把這個流程半自動化，律師仍對最終 draft 負完全責任。

## 三件事這個 POC 已驗證可行

1. **`scripts/verify.sh` 全綠** — 從 login → redaction → RAG → grounded draft → verifier → deadline → audit chain 完整跑通。
2. **20 題架構 reasoning 都有對應的可執行 code**。grep `# Q\d+:` 看每個決策的落地點。
3. **Frontend 可看到** AI draft、grounded citation、律師逐句簽核 (Q16)、audit 不可竄改驗證 (Q13)，並支援 zh-TW / EN 切換與暗色模式。

## 快速開始

```bash
# 0. 一鍵 demo（後端 + 前端 + seed + 自動產 secrets）
bash scripts/start_demo.sh

# 0a. 交付版全 stack（Docker infra + digiRunner/Dify 探測，可跑 LLM_MODE=dify 真模型）
bash scripts/start_delivery.sh

# 1. 後端（完整 POC）— 啟動 gateway :8010 + ai_engine :8011，並 seed demo patent
bash scripts/start_backend.sh

# 1a. 後端（最小 MVP）— 單一 process、單一 /v1/oa/analyze API
bash scripts/start_minimal.sh

# 2. 驗證（完整 POC）— 應印 "ALL CHECKS PASSED"
bash scripts/verify.sh

# 3. 前端
cd frontend && npm install && npm run dev   # http://localhost:5173
```

> Demo 登入密碼為 `demo-{帳號}`（例如 `demo-alice`），詳見 `.env.example`。

## 依架構決策對應的試玩腳本

| 試玩 | 動作 | 觀察重點 |
|------|------|----------|
| Q12 case ACL | 用 Carol 登入 → 嘗試分析 CASE-2025-001 | 403 被擋（Carol 不在這 case 名單） |
| Q10 Redaction | Alice 登入 → 在分析頁按「預覽 redaction」 | email/phone/案件編號被換成 placeholder |
| Q14 Grounded | 跑分析後看 `[GROUNDED_REF_1]` pill | 點開顯示來源 patent + section + 原文；未通過驗證的引用顯示為已移除 |
| Q16 律師簽核 | 在 draft 區域逐句 Accept/Edit | 紫底 = AI、綠底 = 律師改寫；全簽完才能匯出 |
| Q13 Audit | Dave 登入 → Audit 頁 | 看到 mask rules 紀錄 + 「驗證 hash chain」綠燈 |
| Q15 機密路由 | Case_id 結尾 `-CONF` 重跑分析 | audit row 的 model_used 變地端模型 |
| Q9 Cache | 同樣 OA + 同 case 連按兩次「分析」 | 第二次 audit row model_used=`cache`，token=0 |
| Q17 Deadline | 在分析頁看期日 → 點「計算依據」 | 期日落在週末/假日會自動 roll forward，並可展開計算依據 |

## 架構速覽

```
Vite SPA  ──/api──▶  [可選: digiRunner OSS :18080 前線 gateway]
                       │
                       ▼
                     Gateway :8010 (厚 Gateway)
                       │
                       ├─ Auth (Q12)         │ JWT + case_id ACL + 撤銷/logout
                       ├─ RateLimit (Q18)    │ RPM + quota + circuit breaker
                       ├─ Mask (Q3+Q10)      │ regex + dict + reversible
                       ├─ Cache (Q9)         │ tenant:user:case scoped
                       ├─ Orchestrator (Q1)  │ 6-step business flow
                       └─ Audit (Q13)        │ append-only + hash chain
                       │
                       ▼ HTTP
                  AI Engine :8011 (single-step inference)
                       ├─ parse_oa (Q11 spotlight)
                       ├─ retrieve (Q6+Q7 hierarchical+claim-tree)
                       ├─ draft   (Q14 grounded)
                       ├─ verify  (Q14 verifier)
                       └─ deadline (Q17 multi-jurisdiction)
                       │
                       └─ llm_client (Q15 router: mock | anthropic | local | dify)
                       │  LLM_MODE=dify
                       ▼
                  Dify CE :8088 (patentmind-analyze-oa workflow → Ollama qwen2.5:7b)
```

**實機鏈路（2026-06-11 驗證全綠）**：SPA :5173 → digiRunner :18080（`/dgrc`）→
gateway :8010 → ai_engine :8011 → Dify :8088 → Ollama `qwen2.5:7b`，
全鏈路 analyze 約 25–28 秒。起停見 `docs/DELIVERY_RUNBOOK.md`。

完整 Q→code 對應請見 `docs/ARCHITECTURE.md`。

## 文件導覽

- **`docs/DECISIONS.md`** — 20 題的最終決策表
- **`docs/QUESTIONS.md`** — 每題的選項分析（reasoning trace）
- **`docs/ARCHITECTURE.md`** — 每個決策對應到哪份 code、為什麼
- **`docs/SECURITY_AUDIT.md`** — 安全自審報告
- **`CLAUDE.md`** — 給 Claude Code agent 的接手文件（含 TODO list）

## Demo 帳號

| User | Role | Tenant | 看得到的 case | 用途 |
|------|------|--------|---------------|------|
| `alice` | attorney | tenant_a | CASE-2025-001~003 | 跑分析、簽核 |
| `bob` | paralegal | tenant_a | CASE-2025-001~002 | 看分析、協助擬稿（受限） |
| `carol` | it_admin | tenant_b | (無) | 看儀表板、配額 |
| `audit_dave` | auditor | tenant_a | * (全 tenant_a) | 審計、驗 chain |

## 實作狀態

多數原始 stub 已在 Day 8–14 衝刺實作完成，由 env knob 切換：

- 真實 LLM 後端：`LLM_MODE=anthropic | local`（Ollama）`| dify`（Dify CE → qwen2.5:7b）
- 真實 Qdrant：`VECTOR_BACKEND=qdrant`；真實 Redis：`CACHE_BACKEND=redis`
  （rate-limit / JWT 撤銷亦可 `=redis`）
- OIDC / SAML / magic link endpoints（stub IdP）已上
- 本地 WORM audit 封存（`audit_archive.py`，Object Lock 語意）+ audit outbox
- PDF/DOCX 上傳 + Tesseract 地端 OCR + Vision OCR fallback
- Prometheus `/metrics`（兩個 service）、備份/還原/DR drill、假日行事曆 fetcher

**測試基準（2026-06-11）**：pytest **1232 passed / 2 skipped**、Playwright **73 passed**。

仍未實作（POC 範圍外）：Vision 圖示區域萃取（`pdf_parser.py:476`）、真 IdP
（Keycloak）、真 S3 Object Lock 目標、audit 遷移 Postgres、RS256、
streaming replication、Grafana dashboards。

> 完整清單看 `CLAUDE.md` §3「Hardening status」與 `docs/SECURITY_AUDIT.md`。

## 貢獻與安全

- 參與貢獻請見 [CONTRIBUTING.md](CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 回報安全漏洞請循 [SECURITY.md](SECURITY.md)（私下揭露，勿開公開 issue）。

## License

[Apache License 2.0](LICENSE) — 自由使用、修改、散布，含明確專利授權條款。

> **資料免責**：`data/cases/` 內的案件皆為合成資料。請勿將任何真實、未公開的客戶案件或可識別個資 commit 進本 repo（這正是本專案要解決的問題）。詳見 [SECURITY.md](SECURITY.md)。
