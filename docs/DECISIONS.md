# PatentMind AI — 架構決策表（CTO 簽核版）

> 這份文件是 20 題 reasoning 的最終決策。POC 程式碼按這份建。
> 後續所有 PR / RFC 都應該回頭引用這份的決策編號。

| # | 題目 | 選項 | 對 POC 的影響 |
|---|------|------|----------------|
| Q1 | API Gateway 角色 | **厚 Gateway**（含業務邏輯路由） | Gateway 編排多步流程，自寫 orchestrator |
| Q2 | AI Engine 形態 | **Dify 外層 + 自寫 tool**（混合） | POC 用 FastAPI 模擬 Dify，介面對齊 OpenAI-compatible |
| Q3 | 文件上雲邊界 | **Hybrid**：原文留地端、retrieval 結果經 redact 後上雲 | 加 redaction layer 在 Gateway → LLM 之間 |
| Q4 | 前端 | **兩個 app**：產品 SPA + 官網 SSR 分開 | POC 只實作產品 SPA（Vite） |
| Q5 | 租戶隔離 | **Single-tenant data + multi-tenant control** | DB schema 帶 `tenant_id`，但 POC 跑單 namespace |
| Q6 | Chunking | **Hierarchical + Claim-tree** 混合 | spec 階層切 + 每 claim 一 chunk 帶依附項 |
| Q7 | Vector DB | **Milvus / Qdrant self-host** | POC 用 Qdrant docker（介面抽象，可換） |
| Q8 | 多模態 | **OCR + Vision LLM 混合** | OCR 必跑、Vision LLM 介面 stub |
| Q9 | Cache | **Embedding + per-user response cache** | key 帶 `tenant:user:case:hash` |
| Q10 | Data Masking | **PII + 客戶識別碼** | regex + dictionary，placeholder + mapping table |
| Q11 | Prompt Injection 防禦 | **全套四層** | spotlight + harden + output filter + 權限隔離 + canary |
| Q12 | Auth | **三者都支援** | JWT 統一介面，POC 用簡化 token，正式版接 Keycloak |
| Q13 | Audit log | **DB append-only + archive 到 WORM** | SQLite + trigger 阻 update/delete |
| Q14 | 幻覺防禦 | **全套**：UI source + grounded citation + verifier model | 兩段式：generator + verifier |
| Q15 | LLM 選型 | **多模型 + 機密案件強制走地端** | Router by `case.security_level` |
| Q16 | Human-in-the-loop | **逐句律師標記接受/改寫** | UI 每句帶 provenance metadata |
| Q17 | Deadline | **多國 + 多時區 + 官方 holiday API 同步** | POC 做台灣 + US 兩國，介面留多國 |
| Q18 | 成本控制 | **全套**（per-user/tenant/request + cost circuit breaker） | token bucket + 降級 router |
| Q19 | Observability | **全套四層**（系統 + AI 品質 + 業務 + 成本） | Prometheus 指標 stub + JSON log |
| Q20 | DR / RPO | **每日備份**（POC 階段，正式版再升級） | cron job 範例，先不接 S3 |
| FU | Orchestration 放哪 | **混合**：Gateway 高階流程、Dify 純 AI sub-workflow | Gateway 有 `orchestrator.py` 主導流程 |

## 衝突與取捨（給未來自己）

1. **Q1 厚 Gateway × Q2 Dify 混合**：透過 Follow-up「Gateway 做高階流程、Dify 做 AI sub-workflow」化解。明確界線：**Gateway 不打 LLM，Dify 不存業務狀態**。
2. **Q5 single-tenant data × Q7 Milvus self-host**：每開新客戶要起 Qdrant cluster。需要部署自動化（Helm chart + GitOps），這是維運最大投資。
3. **Q15 多模型混合 × Q11 全套防禦**：機密案件走地端 → 地端模型品質差 → 需要更強的 verifier。POC 把 verifier 做成可獨立替換的 component。
4. **Q20 每日備份 × Q13 WORM × Q19 全套監控**：Q20 是「成本暫時性退讓」，但 audit log 即使在 POC 也要 append-only。**正式上線前 Q20 必須升到 B**。
