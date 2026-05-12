# PatentMind AI — POC

> **Secure & Automated Patent Office Action (OA) Analysis Platform**
> NCCU GDGoC × Computex 2026
>
> 這個 repo 是 PatentMind AI 的 POC：完整 frontend + backend，把架構決策驗證到能跑端到端。
> 預期下一步交給 Claude Code 接手做 production hardening（清單見 `CLAUDE.md`）。

## 為什麼存在

律師事務所做專利 Office Action 答辯：
- 看 OA、找 prior art、寫答辯狀，現在純人工，**1 件案 8-12 小時**
- 引用法源容易抄錯（幻覺風險）
- 期日算錯就完蛋
- 客戶資料絕對不能外流

PatentMind 把這個流程半自動化，律師仍對最終 draft 負完全責任。

## 三件事這個 POC 已驗證可行

1. **`scripts/verify.sh` 全綠** — 從 login → redaction → RAG → grounded draft → verifier → deadline → audit chain 完整跑通。
2. **20 題架構 reasoning 都有對應的可執行 code**。grep `# Q\d+:` 看每個決策的落地點。
3. **Frontend 可看到** AI draft、grounded citation hover、律師逐句簽核 (Q16)、audit 不可竄改驗證 (Q13)。

## 快速開始

```bash
# 1. 後端（完整 POC）
bash scripts/start_backend.sh
# 會啟動 gateway + ai_engine，並 seed demo patent

# 1a. 後端（最小 MVP）
bash scripts/start_minimal.sh
# 單一 process、單一 /v1/oa/analyze API，適合快速驗證核心流程

# 2. 驗證（完整 POC）
bash scripts/verify.sh
# 應該印 "ALL CHECKS PASSED"

# 3. 前端
cd frontend
npm install
npm run dev
# 開 http://localhost:5173
```

## 依架構決策對應的試玩腳本

| 試玩 | 動作 | 觀察重點 |
|------|------|----------|
| Q12 case ACL | 用 Carol 登入 → 嘗試分析 CASE-2025-001 | 403 被擋（Carol 不在這 case 名單） |
| Q10 Redaction | Alice 登入 → 在分析頁按「預覽 redaction」 | email/phone/案件編號被換成 placeholder |
| Q14 Grounded | 跑分析後 hover `[GROUNDED_REF_1]` pill | tooltip 顯示來源 patent + section + 原文 |
| Q16 律師簽核 | 在 draft 區域逐句 hover → Accept/Edit | 紫底 = AI、綠底 = 律師改寫；全簽完才能簽核 |
| Q13 Audit | Dave 登入 → Audit 頁 | 看到 mask rules 紀錄 + 「驗證 hash chain」綠燈 |
| Q15 機密路由 | Case_id 結尾 `-CONF` 重跑分析 | audit row 的 model_used 變 `llama-mock`（地端） |
| Q9 Cache | 同樣 OA + 同 case 連按兩次「分析」 | 第二次 audit row model_used=`cache`，token=0 |
| Q17 Deadline | 在分析頁看 DeadlineCard | 期日落在週末/假日會自動 roll forward |

## 架構速覽

```
Vite SPA  ──/api──▶  Gateway :8000 (digiRunner mock, 厚)
                       │
                       ├─ Auth (Q12)         │ JWT + case_id ACL
                       ├─ RateLimit (Q18)    │ RPM + quota + circuit breaker
                       ├─ Mask (Q3+Q10)      │ regex + dict + reversible
                       ├─ Cache (Q9)         │ tenant:user:case scoped
                       ├─ Orchestrator (Q1)  │ 6-step business flow
                       └─ Audit (Q13)        │ append-only + hash chain
                       │
                       ▼ HTTP
                  AI Engine :8001 (Dify mock)
                       ├─ parse_oa (Q11 spotlight)
                       ├─ retrieve (Q6+Q7 hierarchical+claim-tree)
                       ├─ draft   (Q14 grounded)
                       ├─ verify  (Q14 verifier)
                       └─ deadline (Q17 multi-jurisdiction)
                       │
                       └─ llm_client (Q15 router + Q11 canary)
```

完整 Q→code 對應請見 `docs/ARCHITECTURE.md`。

## 文件導覽

- **`docs/DECISIONS.md`** — 20 題的最終決策表
- **`docs/QUESTIONS.md`** — 每題的選項分析（reasoning trace）
- **`docs/ARCHITECTURE.md`** — 每個決策對應到哪份 code、為什麼
- **`CLAUDE.md`** — 給 Claude Code agent 的接手文件（含 TODO list）

## Demo 帳號

| User | Role | Tenant | 看得到的 case | 用途 |
|------|------|--------|---------------|------|
| `alice` | attorney | tenant_a | CASE-2025-001~003 | 跑分析、簽核 |
| `bob` | paralegal | tenant_a | CASE-2025-001~002 | 看分析（受限） |
| `carol` | it_admin | tenant_b | (無) | 看儀表板、配額 |
| `audit_dave` | auditor | tenant_a | * (全 tenant_a) | 審計、驗 chain |

## 已知未實作（POC 範圍外）

- 真實 LLM 後端（目前 mock；改 `LLM_MODE=anthropic` 切換）
- 真實 Qdrant（目前 numpy in-memory）
- 真實 Redis cache（目前 in-process dict）
- OIDC / SAML / magic link 三種 IdP（只有 built-in JWT）
- S3 Object Lock audit archive（目前只有本地 SQLite）
- Dify webhook 實接（目前 ai_engine 是 mock）
- 每小時 streaming replication backup（目前無，Q20 退讓）
- Prometheus metrics endpoint（Q19 layer 1 沒實作）
- 真 PDF 上傳（只接受文字輸入）
- 真 Vision LLM 圖示分析（Q8 stub）

> 完整 TODO 看 `CLAUDE.md` § 3 「What's stubbed」表。

## License

POC 內部專案，未公開授權。
