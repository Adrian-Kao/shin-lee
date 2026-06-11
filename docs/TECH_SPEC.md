# PatentMind AI — 專案技術規格書（完整版）

> 本文件為工程級完整技術說明：架構、模組、請求生命週期、安全機制、
> 整合細節、設定參數、測試與部署，全部對應實際程式碼位置。
> 非技術讀者請改看 `docs/系統說明書.md`；決策脈絡見 `docs/DECISIONS.md`。
>
> 最後更新：2026-06-11（交付驗證全綠版本）

---

## 目錄

1. [專案定位與問題](#1-專案定位與問題)
2. [整體架構](#2-整體架構)
3. [使用者角色與完整操作流程](#3-使用者角色與完整操作流程)
4. [一個 analyze 請求的生命週期（13 步）](#4-一個-analyze-請求的生命週期)
5. [安全業務閘道（gateway :8010）模組詳解](#5-安全業務閘道模組詳解)
6. [AI 推論引擎（ai_engine :8011）模組詳解](#6-ai-推論引擎模組詳解)
7. [LLM 路由與四種推論模式](#7-llm-路由與四種推論模式)
8. [digiRunner 整合細節](#8-digirunner-整合細節)
9. [Dify 整合細節](#9-dify-整合細節)
10. [前端架構](#10-前端架構)
11. [資料與儲存](#11-資料與儲存)
12. [八大設計不變式](#12-八大設計不變式)
13. [API 端點總表](#13-api-端點總表)
14. [設定參數（環境變數）總表](#14-設定參數總表)
15. [測試與驗證](#15-測試與驗證)
16. [部署與啟動](#16-部署與啟動)
17. [已知限制與路線圖](#17-已知限制與路線圖)

---

## 1. 專案定位與問題

**一句話**：專利 OA（Office Action，審查意見通知函）答辯自動擬稿系統 —
上傳公文 PDF，系統自動分類核駁理由、檢索前案證據、產出繁中申復書草稿與
法定期限；機密資料全程不出事務所；律師逐句簽核後才能匯出。

**問題量化**：
- 台灣專利申請量約 71,965 件/年（2025）
- 申請後平均 8 個月收到首次 OA；收文後法定 2 個月內答辯，逾期失效
- 每案人工前置（讀公文、查前案、寫草稿）4–8 小時

**為什麼不能直接用 ChatGPT**（對應四個系統設計）：

| 風險 | 對應設計 |
|---|---|
| 機密進公有模型 | 可逆遮罩 + 機密強制地端 + egress guard |
| 捏造引用（專業責任事故） | 引證驗證硬牆（不可繞過） |
| 無稽核、無法究責 | append-only 雜湊鏈稽核 |
| 期限算錯不可復原 | 多管轄區期限引擎 + 假日順延 |

---

## 2. 整體架構

```
┌────────────────────────────────────────────────────────────┐
│  瀏覽器 SPA — React 18 + Vite (:5173)                        │
│  Login / Analyze 三欄工作台 / DraftEditor 簽核 / AuditView    │
└──────────────────────────┬─────────────────────────────────┘
                           │ /dgrc/<path>（經 digiRunner）或 /api（直連）
                           ▼
┌────────────────────────────────────────────────────────────┐
│  digiRunner OSS dgrv4 (:18080) — 前線 API 閘道（TPIsoftware） │
│  路由/反向代理 · 身分信任標頭(HMAC) · 流量治理 · SSO 接點     │
└──────────────────────────┬─────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────┐
│  安全業務閘道 gateway (FastAPI :8010) — 所有業務狀態          │
│  auth → rate_limit(配額預扣) → masking → cache → orchestrator│
│  → audit(雜湊鏈) ；signoff / revocation / backup / metrics   │
└──────────────────────────┬─────────────────────────────────┘
                           │ INTERNAL_TOKEN 內部認證
                           ▼
┌────────────────────────────────────────────────────────────┐
│  AI 推論引擎 ai_engine (FastAPI :8011) — 無業務狀態           │
│  parse_oa → retrieve(RAG) → draft → verify(硬牆) → deadline  │
│  llm_client 多模型路由 + egress guard + 降級                  │
└───────┬───────────────────────────────┬────────────────────┘
        ▼                               ▼
┌─────────────────┐        ┌────────────────────────────────┐
│ 向量庫           │        │ LLM 後端（LLM_MODE 路由）        │
│ memory / Qdrant │        │ mock｜anthropic｜local(Ollama)  │
│ per-tenant 隔離  │        │ ｜dify→Ollama qwen2.5:7b（交付）│
└─────────────────┘        └────────────────────────────────┘

基礎設施容器：Qdrant :6333 ｜ Redis :6379 ｜ Postgres :15432
（本機 5432 被其他專案占用，故映射 15432）
Dify CE (:8088, 12 容器) ｜ Ollama (:11434)
```

**前後端分離原因**（gateway / ai_engine 拆兩個服務）：
1. 安全邊界 — 業務狀態與推論隔離；AI 層被攻破拿不到業務資料
2. 機密升級路徑 — 機密案件只需把 AI 層換成地端，業務層不動
3. 獨立擴縮 — 推論吃 GPU、業務吃 IO，資源型態不同

---

## 3. 使用者角色與完整操作流程

### 角色（`backend/gateway/auth.py` — `UserRole` + `_USERS`）

| 帳號 | 角色 | tenant | 可存取案件 | 介面差異 |
|---|---|---|---|---|
| alice | 律師 attorney | tenant_a | CASE-2025-001/002/003 | 完整分析+簽核+匯出 |
| bob | 助理 paralegal | tenant_a | CASE-2025-001/002 | 輸入整理，不可簽核 |
| carol | IT 管理 | tenant_b | — | 配額/服務狀態 |
| audit_dave | 稽核員 auditor | tenant_a | —（看不到案件內容） | 只看稽核鏈 |

### 律師主流程（端到端）

1. **登入** — 點角色卡或密碼（demo-alice）→ `POST /v1/auth/login` 簽發
   JWT（user_id/tenant/role/exp）。登出寫入撤銷表（revocation.py），
   token 立即失效。
2. **填案件** — 案件編號 + 本案專利號。case_id 之後一律放 header/body，
   永不放 URL（防 log/proxy 洩漏）。
3. **上傳 OA** — 拖放 PDF/DOCX（≤30MB）三拍流程：
   - 選檔（狀態 `file-selected`）→ 按「上傳」
   - `POST /v1/oa/upload`：PyMuPDF 萃取文字層；單頁字元數低於門檻自動
     落入 Tesseract OCR（`ocr_local.py`，純地端）；回傳頁數/字元數/
     OCR 頁數/圖式元件表（element_table：圖號→元件說明）
   - 預覽萃取文字 → 按「**使用此文字**」填入表單
   - 或直接貼全文（切換「改貼文字」）
4. **（可選）預覽遮罩** — 「預覽 redaction」顯示哪些片段會被替換成代碼。
5. **分析** — 按「分析 OA」→ 第 4 節 13 步流程，實機 25–28 秒。
6. **閱讀結果** — 中欄：答辯策略 + 逐核駁草稿（引用 pill 可點開
   ReferenceModal 看來源原文）；右欄：審查官引證 + 檢索命中前案；
   期限卡：法定期限 + 建議完成日。
7. **逐句簽核** — 每句標示 AI/律師（line provenance），逐句 Accept/Edit；
   勾「我已逐項確認」。
8. **匯出** — `POST /v1/oa/export`；**未完成簽核後端回 409**
   （signoff.py 簽核閘）。匯出時遮罩代碼於地端還原。

### 稽核員流程

登入 audit_dave → Audit 頁 → 每筆請求一列（時間/人/案件/model_used/
命中遮罩規則/tokens/成本/延遲）→ 按「驗證」`GET /v1/audit/verify`
重算整條雜湊鏈 → 顯示 verified 筆數與 broken 清單（正常為空）。

---

## 4. 一個 analyze 請求的生命週期

`POST /dgrc/v1/oa/analyze`（經 digiRunner）：

| # | 站點 | 程式位置 | 行為 |
|---|---|---|---|
| 1 | digiRunner | :18080 | `/dgrc/*` 反向代理至 :8010；可附身分信任標頭（HMAC 共享密鑰），偽造一律 401 |
| 2 | JWT 認證 | gateway/auth.py | 驗簽章/效期；查撤銷表 |
| 3 | 案件 ACL | gateway/auth.py | 逐請求比對 case_id ∈ 使用者案件集，否則 403 |
| 4 | RPM 限流 | gateway/rate_limit.py | 每分鐘請求數上限 |
| 5 | **配額預扣** | gateway/rate_limit.py | `check_quotas()` 以估算 tokens **先佔**每日額度（防並發超扣）；回傳預留句柄 |
| 6 | 成本斷路器 | gateway/rate_limit.py | 當日 LLM 成本 ≥ $100 → 熔斷拒絕 |
| 7 | 遮罩 | gateway/masking.py | PII 規則 + 租戶詞庫 → 語意代碼；映射寫地端 SQLite |
| 8 | 快取 | gateway/cache.py | key=`tenant:user:case:sha(遮罩文+專利號)`；命中→直接回（成本0），釋放預扣，仍寫稽核 |
| 9 | 編排 | gateway/orchestrator.py | HTTP 呼叫 ai_engine（timeout 60s；dify 模式放大為 DIFY_TIMEOUT_SEC+30） |
| 10 | AI 五步 | ai_engine/oa_analyzer.py | parse→retrieve→draft→verify→deadline（見 §6）；saga 容錯：單核駁失敗標記後續行 |
| 11 | 配額結算 | gateway/rate_limit.py | `record_usage(reserved_tokens=…)` 按實際用量結算差額；**錯誤路徑亦釋放**（try/except 包裹） |
| 12 | 稽核寫入 | gateway/audit.py | 一請求一列（含快取命中與錯誤）：model_used/tokens/成本/遮罩規則/policy 決策；`prev_row_hash→row_hash` 鏈 |
| 13 | 回應 | — | `{request_id, oa{rejections[]}, drafts[], related_prior_art[], deadline_summary, claim_tree, redaction_summary, cost_meta}` |

---

## 5. 安全業務閘道模組詳解

### auth.py — 認證與案件 ACL
- JWT HS256（`JWT_SECRET`；啟動時偵測 placeholder 直接拒絕開機）
- `_USERS` 內建四角色；`_CASE_ACL` 案件白名單；**每請求重查**
- 上游信任標頭模式：digiRunner 驗證後以 HMAC 簽名標頭傳遞身分；
  缺共享密鑰或簽名不符 → 401（防偽造）；上游 role 標頭被忽略，
  本地 `_USERS` 為準（防越權）
- stub IdP：`/auth/oidc/*`、`/auth/saml/*`、`/auth/magic`（簽章密鑰
  出廠值 "-do-not-ship" 在非 mock 模式拒絕開機）

### rate_limit.py — 限流、配額、成本斷路器
- 三層：RPM → 每日 token 配額（**預扣/結算**原子模型）→ 每日成本上限
- `CACHE_BACKEND=redis` 時配額計數走 Redis EVAL 原子操作

### masking.py — 可逆遮罩
- `PII_RULES`：email、台灣手機/市話、身分證、統編等正則
- `TENANT_DICTIONARIES`：每租戶 JSON 詞庫（`data/tenant_dicts/<id>.json`）
  — 客戶代號（如 CL-EVC012）、內部案號格式（APEX-…）
- 替換為語意代碼（`〔當事人A〕`、`〔案號1〕`），同值同代碼（一致性）
- 映射表：`data/redaction_mapping.db`（SQLite，**永遠地端**）
- 還原僅發生在匯出/顯示時的事務所端

### cache.py / redis_cache.py
- in-memory（預設）或 Redis；**key 含 user_id** — 同 tenant 不同律師
  不共享（答案是特權資訊）；per-tenant 上限 1000 條

### orchestrator.py — 厚閘道編排
- 唯一對 ai_engine 的出口（AIEngineClient.call）
- **Egress Guard 掛在這個出口**：遞迴掃描 outbound payload 所有字串，
  命中原始 PII 規則 → `EgressGuardError` 擋下 + error 級告警
  （`EGRESS_GUARD_ENABLED`，預設開，mock 模式也開）

### audit.py / audit_outbox.py / audit_archive.py
- append-only SQLite（`data/audit.db`）；每列 `prev_row_hash → row_hash`
  （SHA-256），**per-tenant 鏈**
- `verify_chain`：重算全鏈，回報 broken 列
- outbox：at-least-once 投遞緩衝（斷線不丟稽核）
- archive：Merkle root 批次封存（WORM 形態；S3 Object Lock 目標待接）

### signoff.py — 簽核閘
- 逐句 provenance（AI/人工）+ 全數確認檢查；未確認 export → 409

### revocation.py — token 撤銷
- 登出即失效；Redis 後端時帶 TTL 自動清理

### backup.py — 備份
- 打包 audit.db / redaction_mapping.db / 設定；含還原演練腳本

### shared/metrics.py — Prometheus
- `GET /metrics`：請求數、延遲直方圖、token 用量、降級次數等

---

## 6. AI 推論引擎模組詳解

### oa_analyzer.py — 五步管線
1. **parse_oa**：spotlight 提示結構 — 系統指令與外部內容嚴格分離，
   OA 內文包在「不可信內容」標記內（`injection_guard.py`，防提示注入）；
   輸出核駁清單：type（102 新穎性/103 進步性/112 明確性/缺先行詞…）、
   affected_claims、cited_prior_art、examiner_argument、confidence
2. **retrieve**：逐核駁 RAG 檢索（asyncio.gather 並行）
3. **draft**：逐核駁草擬；引用**只能**以 `[GROUNDED_REF_N]` 佔位符
   指向檢索命中（grounded citations）
4. **verify**：**引證驗證硬牆** — 逐一比對佔位符是否存在於檢索集；
   查無實據 → 剝除 + 在 UI 標示；驗證模型與草擬模型**強制不同**
   （`assert_verifier_independence()`）；**不外包給 Dify**
5. **deadline**：見 deadline.py

saga 容錯：單一核駁的檢索/草擬丟例外 → log + 標記 failed_rejection_ids，
其餘核駁繼續（不整單失敗）。

### rag.py — 檢索
- 切塊：階層式（標題/段落）+ **請求項樹**（`claim_tree.py` 解析
  independent/dependent 依附關係，樹結構隨 chunk 保留）
- `VECTOR_BACKEND=memory|qdrant`；Qdrant 為 **per-tenant collection**
  物理隔離；upsert 前全批驗證向量維度（原子性，zip strict=True）
- `EMBEDDING_BACKEND=mock|bge-m3`：mock 為 SHA-256 確定性嵌入
  （384 維，含 tenant 鹽，demo 可重現）；bge-m3 為 sentence-transformers
  真嵌入（`scripts/prefetch_bge_m3.py` 預下載）
- `retrieval_eval.py`：召回率評測腳本（data/eval 標註集）

### deadline.py — 期限引擎
- 六管轄區規則：TW/US/JP/EP/CN/KR（`SUPPORTED_JURISDICTIONS`）
- 行事曆：`data/calendars/*.json`（`scripts/fetch_holidays.py` 抓取更新；
  程式內 `_FALLBACK_HOLIDAYS` 僅為安全網）
- 規則：公文日期 + 法定期間 → 落假日自動順延 → 另給內部建議完成日
- `HolidayProvider` 抽象（可掛快取/遠端來源）

### pdf_parser.py / ocr_local.py
- PyMuPDF（fitz）萃取文字層；逐頁字元數檢查，低於門檻 → Tesseract OCR
  （地端，未安裝則標示 ocr_unavailable 警告）
- 圖式元件表萃取（element_table）；Vision 模型圖式理解為 TODO

### prompt_loader.py + prompts/*.yaml
- 所有系統提示詞單一來源（YAML 版控）；
  `setup_dify.py` 由同一份 YAML 生成 Dify workflow DSL → 兩邊永不漂移

---

## 7. LLM 路由與四種推論模式

`llm_client.py` — `route_model(intent)` 依任務選模型，`LLM_MODE` 選後端：

| 模式 | 後端 | 特性 |
|---|---|---|
| mock | 確定性規則引擎 | 零依賴、輸出可讀繁中、測試與降級備援 |
| anthropic | Claude API | 草擬用 Sonnet 級、驗證強制 Haiku（不同模型） |
| local | Ollama OpenAI 相容端點 | 全地端；本機模型 qwen2.5:7b |
| **dify** | Dify workflow → Ollama | **交付鏈路**；解析+草擬走 workflow |

跨模式機制：
- **機密強制地端**：case_id 帶 `-CONF` → 路由強制 local
  （`LOCAL_LLM_FOR_SECURITY_LEVELS`）；`DIFY_EGRESS_LOCAL=false` 時
  機密走 Dify 直接 RuntimeError 拒絕
- **canary**：新模型按比例放量
- **降級**：Dify 不可達 → 自動退 mock；模型名標
  `dify/qwen2.5:7b-DEGRADED-mock` 寫入稽核；前端 DraftsPane 偵測
  `-DEGRADED-` 顯示琥珀警示橫幅（role=alert）— **絕不冒充真實分析**
- **驗證器獨立**：`LLM_MODEL_VERIFIER` 必 ≠ `LLM_MODEL_REASONING`

---

## 8. digiRunner 整合細節

- 映像：tpisoftwareopensource/digirunner-open-source（dgrv4）
- 埠：:18080；代理格式 `http://localhost:18080/dgrc/<原路徑>`
- H2 in-memory DB → 路由不持久；`scripts/start_digirunner.sh` 每次
  啟動以 AC REST API 自動重灌（約 5 秒）：
  1. `POST /dgrv4/tptoken/oauth/token`（密碼 base64）取 AC token
  2. `AA0311` 註冊 12 條 API 路由（rtn 1100=新建、1353=已存在＝冪等）
  3. `AA0303` 啟用
- 身分信任標頭：digiRunner 驗證後以共享密鑰簽名的標頭傳遞身分；
  gateway 驗 HMAC；無密鑰偽造 → 401；上游 role 標頭一律忽略
- Admin console：`/dgrv4/login`（帳密在 `.env` 的 `DGR_ADMIN_*`）
- 前端切換走 digiRunner：
  `VITE_API_TARGET=http://localhost:18080 VITE_API_PATH_PREFIX=dgrc npm run dev`
- 煙霧測試：`scripts/smoke_digirunner.sh`（7 點：console、路由查詢、
  經代理登入+分析、直連備援、信任標頭、偽造拒絕）

---

## 9. Dify 整合細節

- Dify CE 1.14.2，docker compose（12 容器）於 `D:\patentmind-infra\dify`
- `scripts/setup_dify.py` **冪等一鍵建置**：
  1. admin 初始化 → console 登入（cookie + CSRF）
  2. 安裝 Ollama plugin → 註冊 qwen2.5:7b 模型
  3. 由 `backend/ai_engine/prompts/*.yaml` **生成 DSL 0.6.0** 匯入
     workflow `patentmind-analyze-oa` → 發布
  4. 建 API key 回寫 `.env`（`DIFY_API_KEY_ANALYZE`）
- 執行期：ai_engine 的 `DifyLLM` 以 API key 呼叫 workflow；
  workflow 內呼叫本地 Ollama → **機密不出機器**
- 引證驗證**不在** Dify 內 — 防幻覺硬牆留在本系統程式碼
- E2E 證明：`data/dify_e2e_proof.json`（完整鏈路 27.2s 真模型繁中草稿）
- 煙霧測試：`scripts/smoke_dify.sh`（驗 model_used=dify/qwen2.5:7b）

---

## 10. 前端架構

- React 18 + Vite；TanStack Query（api/queries.js）；react-i18next
  （zh-TW/en 完整雙語）；Tailwind；RWD（桌面三欄/行動分頁）
- 主要元件：
  - `Login.jsx` — 角色卡登入
  - `Analyze.jsx` + `analyze/InputPane|DraftsPane|ReferencesPane|
    ClaimTree|ReferenceModal` — 三欄工作台
  - `OAUpload.jsx` — 拖放上傳狀態機
    `idle→file-selected→uploading→server-extracting→success`；
    PDF 預覽、萃取預覽、元件表、「使用此文字」
  - `DraftEditor.jsx` — line provenance 逐句簽核
  - `AuditView.jsx` — 稽核表 + 鏈驗證
  - `StackStatus.jsx` — 頁尾四燈（gateway/ai_engine/digiRunner/Dify）
  - `AppShell.jsx` — 頂部安全狀態列（遮罩開啟/資料本地）、深色模式
- 降級可見性：cost_meta.model 含 `-DEGRADED-` → 琥珀警示橫幅
- Vite proxy：`/api` → :8010（埠不寫死於 client.js）

---

## 11. 資料與儲存

| 資料 | 位置 | 形態 |
|---|---|---|
| 稽核鏈 | data/audit.db | SQLite append-only + 雜湊鏈 |
| 遮罩映射 | data/redaction_mapping.db | SQLite，**僅地端** |
| 向量索引 | memory / Qdrant :6333 | per-tenant collection |
| 租戶詞庫 | data/tenant_dicts/*.json | 每租戶上傳 |
| 行事曆 | data/calendars/*.json | 6 管轄區 |
| 示範案件 | data/cases（80 synthetic）+ patent_db/seed.py（7 件） | demo |
| OA 樣本 | data/oa_samples（US/TW/CN/EP/KR + PDF） | 測試/demo |
| 評測集 | data/eval, data/eval_results | RAG 召回/品質評測 |

---

## 12. 八大設計不變式

1. 閘道永不直接呼叫 LLM（一切經 ai_engine）
2. ai_engine 不保存業務狀態（除 RAG 向量）
3. 任何使用者文字進 AI 前必經遮罩（egress guard 技術強制）
4. 每個 gateway 請求恰寫一列稽核（含快取命中、含錯誤）
5. 草稿引用必來自 grounded 檢索集（verify_citations 硬牆）
6. 每請求檢查 case_id ACL，無路可繞
7. 機密案件自動路由地端模型（程式層拒絕外送）
8. token 配額檢查先於 LLM 呼叫（預扣/結算原子模型）

---

## 13. API 端點總表（gateway :8010）

| 方法 | 路徑 | 用途 |
|---|---|---|
| POST | /v1/auth/login | JWT 登入 |
| POST | /v1/auth/logout | 撤銷 token |
| GET/POST | /v1/auth/oidc/* /saml/* /magic | stub IdP |
| POST | /v1/oa/upload | PDF/DOCX 萃取（+OCR fallback） |
| POST | /v1/oa/analyze | 主分析管線 |
| POST | /v1/oa/export | 匯出（簽核閘 409） |
| POST | /v1/redaction/preview | 遮罩預覽 |
| GET | /v1/quota | 配額/用量快照 |
| GET | /v1/audit | 稽核列表（角色限定） |
| GET | /v1/audit/verify | 雜湊鏈驗證 |
| GET | /v1/health | 健康+快取+斷路器狀態 |
| GET | /metrics | Prometheus |

（ai_engine :8011 對外僅 /v1/health 與內部 token 保護的推論端點）

---

## 14. 設定參數總表（.env / 環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| LLM_MODE | mock | mock/anthropic/local/dify |
| LLM_MODEL_REASONING / _VERIFIER | — | 兩者強制不同 |
| LLM_MODEL_LOCAL | qwen2.5:7b | Ollama 模型名 |
| DIFY_API_KEY_ANALYZE | setup 自動寫入 | workflow 金鑰 |
| DIFY_TIMEOUT_SEC | — | gateway timeout 自動 +30 |
| DIFY_EGRESS_LOCAL | true | false 時機密走 Dify 直接拒絕 |
| EGRESS_GUARD_ENABLED | true | 出口 PII 掃描 |
| VECTOR_BACKEND | memory | memory/qdrant |
| EMBEDDING_BACKEND | mock | mock/bge-m3 |
| CACHE_BACKEND | memory | memory/redis |
| JWT_SECRET / INTERNAL_TOKEN / DEMO_LOGIN_SECRET | 自動生成 | placeholder 拒絕開機 |
| OIDC/SAML_STUB_SIGNING_SECRET | 自動生成 | 出廠值拒絕開機 |
| DGR_ADMIN_* / DIFY_ADMIN_* | .env | 平台管理帳密 |
| HOLIDAY_SOURCE | data/calendars | 行事曆來源 |
| MAPPING_DB_PATH | data/ | 遮罩映射（強制地端） |

---

## 15. 測試與驗證（2026-06-11 基線）

| 套件 | 結果 |
|---|---|
| 後端 pytest（單元+整合） | **1,232 passed**, 2 skipped（可選 OCR） |
| 前端 Playwright E2E（含視覺回歸/深色/行動） | **73 passed** |
| verify.sh（20 不變式端到端） | ALL CHECKS PASSED |
| smoke_digirunner.sh | 7/7 |
| smoke_dify.sh | model_used=dify/qwen2.5:7b |
| smoke_demo.sh（含真 PDF 上傳） | ALL GREEN |
| 全鏈路實機 analyze | 25–28s，正確抓出請求項 9 缺先行詞 |
| 程式品質 | ruff 全 repo 零違規；prettier/eslint 全綠 |

不變式有對應測試：繞過遮罩的端點、跨用戶快取、配額重複計數、
稽核鏈竄改、驗證器同模型 — 都會被測試抓出。

---

## 16. 部署與啟動

```bash
# 一鍵交付環境（docker infra + 後端×2 + 前端 + 外部 hop 探測）
bash scripts/start_delivery.sh

# 個別
bash scripts/start_digirunner.sh      # digiRunner + 自動路由重灌
cd /d/patentmind-infra/dify/docker && docker compose up -d
PYTHONUTF8=1 python scripts/setup_dify.py   # 冪等
bash scripts/start_demo.sh            # 後端+前端+seed（首次自動生成密鑰）

# 驗證
bash scripts/verify.sh && bash scripts/smoke_demo.sh
bash scripts/smoke_digirunner.sh && bash scripts/smoke_dify.sh
```

埠總表：5173 前端｜18080 digiRunner｜8010 gateway｜8011 ai_engine｜
8088 Dify｜11434 Ollama｜6333 Qdrant｜6379 Redis｜15432 Postgres。

Windows 注意：subprocess 一律 `encoding="utf-8"`（cp950 環境）；
中文輸出腳本帶 `PYTHONUTF8=1`；Git Bash 會改寫 `/dgrc` 開頭路徑。

---

## 17. 已知限制與路線圖

**仍是 stub / 待辦**：
- 圖式 Vision 理解（pdf_parser.py 標記 TODO；目前僅元件表）
- 真實企業 IdP（OIDC/SAML 為 stub 簽章流程，介面已就緒）
- 稽核庫 SQLite → Postgres；封存目標接真 S3 Object Lock
- Grafana dashboard JSON（/metrics 已就緒）
- 備份升級為串流複寫（上線前必做）

**路線圖**：接真實 SSO → Postgres 稽核 → GPU 地端大模型（70B 級）→
多事務所多租戶上線 → 律師接受率回饋迴圈（quality_eval.py 已有骨架）。
