# 專利師系統 — 領域知識地圖（總索引）

> **這份是什麼**：把 2026-06-13 四個並行研究 agent 的產出綜合成「一張地圖」。給開發團隊用。
> 上層回答「專利師到底怎麼工作、系統每一塊對應到哪個實務環節、下一步該補什麼」。
> 細節在各分冊；本索引只做**串接 + 跨文件的行動清單**。
>
> **管轄重心**：台灣 TWPO（中華民國專利法 + 經濟部智慧財產局專利審查基準）。
> **受眾**：工程團隊（把法律概念翻成資料模型/流程/守則）。

---

## 30 秒摘要

專利師的價值鏈是 **撰稿 → 審查 → OA 答辯 → 領證/再審**，其中 **OA 答辯是本系統的核心戰場**。
四個關鍵認識：

1. **這不是自由生成，是「結構化生成 + 約束檢查」**。說明書↔請求項的「支持關係」、OA 的「逐請求項 × 逐法條」核駁矩陣、答辯引用的「接地集合」——全都是可被機器檢查的**圖/矩陣**結構。確定性 lint 應先於 LLM。
2. **引用接地（grounding）是答辯場景的命脈**，幻覺零容忍。引錯前案、把美國法搬進台灣申復書，是會出事的法律錯誤，不是品質瑕疵。系統用 `verify_citations` 硬牆 + 獨立 verifier 第二模型雙重防線。
3. **專利師簽核責任不可被自動化取代**。系統做到 draft → 人類審閱 → sign-off；range 決策、argue/amend、送件，永遠 human-in-the-loop。
4. **機密性是架構的第一性約束**。機密案不可離機/離境 → 驅動「雲端控制平面 + 多地端資料平面」的分散式拓樸與 per-tenant 隔離。

---

## 分冊地圖

| # | 分冊 | 一句話 | 主要對應系統模組 |
|---|------|--------|------------------|
| [01](01_TW專利申請撰稿實務.md) | TW 專利申請撰稿實務 | 委託→送件全流程、說明書/請求項結構、§26 支持要件、撰稿痛點 | `claim_tree.py`、`element_table.py`、`prompts/`、（缺）spec/claim 生成與 §26 lint |
| [02](02_TW_OA核駁答辯實務.md) | TW OA 核駁答辯實務 | OA 三種文書、**核駁理由型態學**、進步性深拆、答辯工作流、程序救濟 | `oa_analyzer.py`、`element_table.py`、`deadline.py`、`data/oa_samples/` |
| [03](03_RAG技術_專利應用.md) | 專利 RAG 技術 | 為何難、chunking、embedding 選型、hybrid+rerank、接地防幻覺、落地路線 | `rag.py`、`oa_analyzer.py`、`retrieval_eval.py` |
| [04](04_分散式架構.md) | 分散式架構 | 有狀態/無狀態盤點、水平擴展、機密性拓樸、多分所、可靠性與 DR | `gateway/*`、`audit*.py`、`rate_limit.py`、Qdrant/Redis/PG/MinIO |
| [05](05_實驗記錄.md) | 實驗記錄 | 本輪自動實驗：改了什麼、測了什麼、量到什麼 | 見該檔 |
| [06](06_RAG優化_方向一_實作計畫.md) | RAG 優化(方向一)實作計畫 | 檢索品質的分階段計畫 + filing_date 接線/eval 擴充起手式 | `rag.py`、`retrieval_eval.py`、`main.py`、orchestrator |

---

## 一、專利師工作流全景（地圖主幹）

```
   發明人/客戶                    TWPO 審查官                    專利師（本系統使用者）
       │                              │                                │
       ▼                              │                                ▼
  ① 技術揭露 ──────────────────────────────────────────▶  撰稿階段（分冊 01）
       │                              │                     ├─ 先前技術檢索   ◀── RAG（分冊 03）
       │                              │                     ├─ 專利性評估（go/no-go）
       │                              │                     ├─ 說明書撰稿     ◀── §26 支持要件
       │                              │                     ├─ 請求項佈局（上/下位、附屬樹）
       │                              │                     └─ 圖式/摘要/送件 ◀── 簽核(human)
       │                              ▼                                │
       │                         實體審查                              │
       │                              │                               │
       │                    ② 審查意見通知函 / 核駁先行通知 ───────────▶ OA 答辯階段（分冊 02）★核心
       │                              │                     ├─ OA 拆解：逐請求項×逐法條 核駁矩陣
       │                              │                     ├─ 讀引證前案     ◀── RAG 檢索 + 日期過濾
       │                              │                     ├─ argue / amend 決策（human）
       │                              │                     ├─ 答辯理由書 + claim 修正對照表
       │                              │                     │     ◀── 接地引用硬牆 + 獨立 verifier
       │                              │                     └─ 送件 ◀── sign-off / provenance
       │                              ▼                                │
       │                   ③ 再 OA / 核駁審定 ──────────────────────────┤
       │                              │                     ├─ 再審查 / 訴願 / 行政訴訟
       │                              ▼                     └─（系統邊界：更正、舉發答辯為另一程序）
       │                         ④ 領證
       └──────────────────────────────────────────────────────────────┘
   全程：期限管理(分冊02 deadline) · 稽核(分冊04) · 機密路由(分冊04) · PII遮罩
```

**讀法**：系統最有價值的著力點集中在兩個方框——撰稿階段（成熟度較低，缺生成與 §26 lint）與
**OA 答辯階段（成熟度較高，是既有系統的重心）**。RAG 與分散式是橫貫兩者的基礎設施。

---

## 二、每塊對應到哪個系統模組（含成熟度）

| 工作流環節 | 系統模組 | 成熟度 | 關鍵不變量 |
|-----------|---------|--------|-----------|
| 先前技術檢索 | `rag.py`（chunk + 向量 store + retrieve） | 🟡 中文切塊✅ / 前案日期過濾✅ / hybrid(BM25+dense)✅;待 bge-m3 + rerank + qdrant sparse | 引用須來自 grounded set（#5） |
| OA 拆解分類 | `oa_analyzer.py`（spotlight） | 🟢 成熟 | 逐請求項×逐法條矩陣 |
| claim 結構解析 | `claim_tree.py`、`element_table.py`（純 regex） | 🟢 成熟 | 確定性優先於 LLM |
| 引用接地/防幻覺 | `oa_analyzer.verify_citations` + 獨立 verifier | 🟢 成熟，待加管轄感知 | 硬牆 + 第二模型獨立（#5、Q14） |
| 答辯期限 | `deadline.py`（多管轄 + 假日表） | 🟡 TW 用 60 天固定（簡化，見下） | 版本鎖定 calendar |
| 簽核/provenance | `signoff.py`（Q16） | 🟢 成熟 | human-in-the-loop sign-off |
| 機密路由 | `llm_client.py` `LOCAL_LLM_FOR_SECURITY_LEVELS` | 🟢 成熟 | 機密案 auto-route 地端（#7） |
| 稽核鏈 | `audit.py` + `audit_archive.py` + `audit_outbox.py` | 🟢 成熟 | 一請求一稽核列（#4）；per-tenant 鏈 |
| 撰稿生成 | （缺） | 🔴 缺口 | 生成後須人類簽核 |
| §26 支持度 lint | `claim_support.py`（純解析） | 🟢 v1（確定性 lint,未接端點） | 說明書↔claim 支持圖;human-in-the-loop |

---

## 三、跨文件的可行動缺口（綜合四份 agent 的發現，依「法律正確性 > 品質 > 規模」排序）

### A. 法律正確性級（最優先，錯了會出事）

1. **前案日期未當硬過濾**（分冊 03）。`rag.retrieve()` 只用 jurisdiction 過濾,chunk 內已有 `pub_date` 卻沒拿來擋「晚於申請日的前案」。前案必須早於申請/優先權日——這是法律正確性,不是品質。→ **能力 + live 接線皆完成**:`filing_date` 經 `AnalysisRequest`→`/v1/retrieve_prior_art`→orchestrator 帶下去,本案自身豁免(見分冊 05/06)。
2. **答辯期限 TW 規則過度簡化**（分冊 02）。`deadline.py` `RULES["TW"]` 用固定 60 天,**未區分本國（2 月）/ 國外（3 月）申請人**、未用日曆月、未處理展期重算。屬法律敏感,且既有測試斷言 60 天——**不可在無專利師確認下逕改**;本輪以「待專利師確認」記錄,不動預設值（見分冊 05 §決策）。
3. **跨管轄引用洩漏**（分冊 02）。`verify_citations` 把 `35 U.S.C. § 103` 當「可驗證法條」白名單保留,但在 **TW 申復書**中引美國法是法律錯誤。→ **本輪實驗 3 加管轄感知白名單(opt-in)（見分冊 05）**。

### B. 檢索品質級

4. **中文說明書切塊塌陷**（分冊 03）。`rag.py` `_SECTION_HEADINGS` 全英文正則,TW/CN/JP 說明書 fall back 成單一 BODY chunk,喪失節結構 → 檢索變差。直接傷害 TW 重心。→ **本輪實驗 1 已修（見分冊 05）**。
5. **dense-only 檢索不夠**（分冊 03）。專利檢索需 hybrid（BM25 + dense）+ reranker;元件編號/化學式/專有名詞靠精確詞彙。→ **hybrid(BM25 + dense via RRF)v1 已實作**(`RETRIEVAL_MODE=hybrid`,memory store;mock 下 recall@5 0.350→0.750,見分冊 06)。**仍待**:qdrant sparse 向量(production hybrid)+ `bge-reranker-v2-m3` 重排。
6. **切 bge-m3 後上調 CI 門檻**（分冊 03）。`retrieval_eval.py` 的 gate 目前 0.10,bge-m3 後應棘輪到 ~0.70 並補 span 級回溯。

### C. 規模/可靠性級

7. **audit Postgres 僅每日快照,RPO ~24h**（分冊 04）。對律所合規是合約終止級風險,prod 前須上 streaming replication（Patroni）。
8. **RPM 限流仍 in-memory**（分冊 04）。多副本下 RPM 上限被放大 N 倍,須 redis 化（`check_rpm`）。
9. **audit 全域單鏈擋跨地寫入**（分冊 04）。建議改 per-tenant 分鏈 + 中央 verify-only;contol-plane 只收 Merkle root（純 hash 不含內容,schema 天然隱私安全）。

### D. 功能缺口

10. **撰稿側缺生成與 §26 lint**（分冊 01）。答辯側成熟,撰稿側缺「spec/claim 生成 prompt」與「§26 支持度 lint」兩個明確擴充點。→ **§26 lint v1 已實作**(`claim_support.py`,確定性、無 LLM,見分冊 05 實驗5);spec/claim 生成仍缺。

---

## 四、三條設計原則（貫穿四份文件）

1. **確定性優先於 LLM**。能用 regex/parser/圖檢查的（claim 樹、§26 支持、引用接地、期限）就不要交給 LLM。LLM 負責生成草稿與「第二意見」,不負責守門。
2. **接地與管轄是硬牆,不是建議**。引用必來自 grounded set;前案必早於申請日;TW 案不引美國法。這些是 fail-closed 的 invariant,不是可調參數。
3. **機密性決定拓樸**。資料落地/落境邊界先於效能與便利;機密案整鏈在地端完成,只有不含內容的稽核摘要可越邊界做全域驗證。

---

## 五、待查證彙整（四份文件的法律/技術未定項）

法律（分冊 01/02）：TW 答辯指定期間天數（本國/國外）與展期上限重算、多重附屬項形式與規費、§22 進步性基準最新版次、最後通知判準、舉發/訴願期間、§34 分割時點、新型技術報告代碼定義。

技術（分冊 03/04）：專利專用 embedding（PatenTEB/PatentSBERTa）多語可用性、Qwen-3 Embedding 專利實測、BGE-M3 sparse+ColBERT 在 Qdrant 落地、Qdrant 大量 per-tenant collection 上限、RPM redis 化方案、PG SERIALIZABLE 稽核寫入吞吐。

> 各分冊內每個「待查證」都附當下查證來源或標註；上線前需專利師/法遵覆核法律項,SRE 覆核技術項。
