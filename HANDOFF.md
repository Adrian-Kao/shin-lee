# PatentMind POC — Session Handoff

> 這份是給「另一個 terminal」接手用的完整 session 摘要。
> 工作目錄：`D:\patentmind-poc`（Windows, PowerShell + Git Bash）
> 分支：`feature/patentmind-poc`
> 時點：2026-05-12（session 開始時的 currentDate）

---

## 0. TL;DR

兩個階段：
- **Phase A — 已完成 ✅**：把專案中的真實 OA（`docs/初審審查意見通知函.pdf`，TW §26(2) 缺先行詞）端到端跑進 minimal MVP backend，mock 模式所有 assertion 通過。
- **Phase B — 進行中 🚧**：使用者要求「生成 30 份類似真實的案例組（專利文件 + 初審意見書，部分含複審駁回書）」。已建好任務骨架、規劃完 30 案 taxonomy，**尚未產出實際內容檔案**。

接手者只要做 Phase B 的剩餘步驟。Phase A 的程式碼修改已就位且有測試覆蓋。

---

## 1. 專案速覽（給沒讀過 CLAUDE.md 的接手者）

**PatentMind AI POC** — 律師事務所處理專利 Office Action（OA）答辯的半自動化平台。

**架構分兩個服務（mock）**：
- `gateway :8000` 厚 Gateway（Auth → RateLimit → Redaction → Cache → Orchestrator → Audit）
- `ai_engine :8001` Dify mock（parse_oa → retrieve RAG → draft → verify_citations → deadline）
- **Minimal MVP**：`backend/minimal/main.py` 是把兩者壓成單 process 跑在 `:8010` 的精簡版（無 auth、無 audit chain），用 `bash scripts/start_minimal.sh` 啟動，預設 `LLM_MODE=local` 接 Ollama `llama3.1:8b`。

**架構鐵律（不能違反）** — 詳見 `CLAUDE.md §4`：
1. Gateway 永不直呼 LLM
2. AI Engine 不存業務狀態
3. 所有 LLM call 前必 redaction
4. 每個 Gateway request 必有 audit row（即使 cache hit）
5. Citation 必須來自 grounded set（這條為了配合 TW 申復書，我已新增 statute whitelist 例外，見後）
6. case_id ACL 永遠檢查
7. 機密案件（case_id 以 `-CONF` 結尾）強制走地端 LLM
8. Token 配額在 LLM call 前先擋

**Demo 帳號**：`alice`（attorney, tenant_a）、`bob`、`carol`、`audit_dave`，皆無密碼（POC 簡化）。

**重要設定**（`backend/shared/config.py`）：
- `LLM_MODE`：`mock | anthropic | local`（minimal 預設 local）
- `EMBEDDING_BACKEND`：`mock | bge-m3`
- `VECTOR_BACKEND`：`memory | qdrant`
- `HOLIDAY_CALENDAR_VERSION`：`"2025.1"`（holidays 表硬編 2025 年）

---

## 2. 原始素材

`docs/` 下的兩個 PDF（**兩份在 2026-05-12 都已公開**，TIPO GPSS 可下載）：

| 檔案 | 實際頁數 | 狀態 |
|------|----------|------|
| `docs/專利文件.pdf` | **1 頁**（只有公開公報封面 + 摘要，不是 46 頁完整說明書） | 純掃描圖片無文字層 |
| `docs/初審審查意見通知函.pdf` | 2 頁 | 有文字層，可 pdftotext 萃取 |

**OA 案件事實**：
- 申請案號：113141617，發文日 民國 114 (2025) 年 5 月 29 日，發文字號 11420571970
- 申請人：拓連科技股份有限公司 NOODOE
- 公開號：TW 202617461 A，公開日 民國 115 (2026) 年 5 月 1 日
- 名稱：電動車充電站之充電管理方法及系統
- IPC：B60L53/60、B60L53/68
- 唯一瑕疵：**請求項 9「該第一電動車」缺先行詞 → §26-2 明確性**
- 請求項 1~8、10：目前未發現不予專利理由
- 答辯期限：文到次日起 2 個月內（早已過期，今天 2026-05-12）

---

## 3. Phase A — 已完成的修改（讓 TW 中文 OA 跑得通）

### 改動清單（6 個檔案）

| 檔案 | 行數參考 | 改動內容 |
|------|----------|----------|
| `backend/shared/models.py` | L35-43 | `RejectionType` enum 新增 `ANTECEDENT_BASIS = "antecedent_basis"`（TW §26-2 缺先行詞子類） |
| `backend/patent_db/seed.py` | L81-141 新增節 | 種入 **TW202617461 A** 完整 patent（10 項 claims）；請求項 9 故意保留「該第一電動車」匹配 OA 指摘；其他項使用前後一致的「第一特定電動車充電站」用語 |
| `backend/ai_engine/oa_analyzer.py` | 多處 | (a) `_PARSE_OA_SYSTEM` 加 TW 專利法 → enum 對照表 + 中英文語言保留指令<br>(b) `_DRAFT_SYSTEM_TEMPLATE` 加語言/管轄域感知 + antecedent_basis 三種補救方案模板（改「一」+用語、定義併入上位項、改依附關係）<br>(c) `_CITATION_PATTERNS` 加 `專利法第N條第M項` + 9 碼 TW 公開號<br>(d) 新增 `_STATUTE_WHITELIST` 與 `_is_statute()`，讓 OA 引述的法條（`專利法第26條第2項`、`35 U.S.C. § 103`）不會被驗證器砍成 `[CITATION_REMOVED]`<br>(e) 新增 `extract_received_date()`，解析 `中華民國 NNN 年 N 月 N 日` / ISO / `Mailing Date: YYYY-MM-DD` 三種格式 |
| `backend/ai_engine/llm_client.py` | `_mock_parse_oa` / `_mock_draft` | Mock LLM 新增 (a) TW §26 先行詞路徑優先序（自動抓「請求項 N」）；(b) `_mock_draft` 對 `antecedent_basis` 回傳完整 TIPO 申復書格式 |
| `data/oa_samples/sample_oa_tw.txt` | 新檔 | 從 PDF 萃取後手動清整的繁體中文 OA，可直接貼進前端 Analyze 表單 |
| 已清理 | — | 刪掉我探索期建立的暫存檔 `docs/_oa.pdf`、`docs/_oa.txt`、`docs/_patent.pdf`、`docs/_patent.txt` |

### 設計決策（為什麼這樣做）

- **`ANTECEDENT_BASIS` 獨立 enum，不併入 `INDEFINITENESS_112`**：因為補救方案不一樣（明確性可能要重寫整段，缺先行詞只要加「一」就好），下游 draft step 要能分流。
- **`_STATUTE_WHITELIST` 例外**：TW 申復書一定要寫「專利法第26條第2項」這種法條引用，原本 verifier 把這些當「不在 grounded set」全砍掉，會把申復書掏空。法條來自 OA 自身且公開可驗證，加白名單是合理例外。
- **`extract_received_date()` 優先序**：先抓 ROC 民國日期（TIPO 公文格式），再抓 USPTO `Mailing Date:`，最後 fallback 任意 ISO 日期。**`make_oa_document()` 已改成呼叫這個 helper**，所以 deadline 是用真實 OA 日期算的，不是 `datetime.now()`。

### 驗證結果（mock 模式）

```
TW OA end-to-end smoke test (LLM_MODE=mock)
============================================================
OA received_date  : 2025-05-29T09:00:00+00:00   ← 從「中華民國 114 年 5 月 29 日」抓出 ✓
OA rejections     : 1
  - rej-1 type=antecedent_basis claims=[9] conf=0.93 ✓

Drafts            : 1
  strategy:  請求項9之「該第一電動車」缺先行詞，係屬專利法第26條第2項之記載瑕疵...
  citations: ['[GROUNDED_REF_1]', '專利法第43條第2項', '專利法第26條第2項'] ← statute 沒被砍 ✓
  draft_text: 申請人謹依鈞局民國114年5月29日（114）智專一（作）05150字第11420571970號審查意見通知函...

RAG hits (mock embeddings, 仍可辨識):
  - TW202617461#claim_2  ← seed 的新 patent 被檢索到 ✓
  - TW202617461#claim_3

Deadline          :
  statutory       : 2025-07-28T23:59:00+08:00   ← +60 天，落星期一不需 roll forward ✓
  recommended     : 2025-07-21T23:59:00+08:00
  warnings        : ['⛔ DEADLINE PASSED 288 days ago.']   ← 對的，今天是 2026-05-12 ✓
```

**US 既有樣本回歸測試也通過**：US OA 仍回 §103 + §102 兩條 rejection，新版 `extract_received_date()` 也正確抓出 `Mailing Date: 2025-04-15`。

### 跑真 Ollama 的方式

```bash
# 確認 Ollama 已 pull llama3.1:8b 並 serve 在 :11434
bash scripts/start_minimal.sh          # backend :8010
cd frontend && npm run dev             # UI :5173
```

Analyze 頁輸入：
- 案號：`CASE-2025-TW-001`
- 目標專利：`TW202617461`
- OA 內容：複製 `data/oa_samples/sample_oa_tw.txt` 全文

想讓 RAG 更精準排序：
```bash
EMBEDDING_BACKEND=bge-m3 bash scripts/start_minimal.sh
# 多語言 BGE-M3 會把 TW202617461#claim_1/9 排到前面（mock 雜湊 embedding 會排第一名給雜訊）
```

---

## 4. Phase B — 進行中：生成 30 份合成案例

### 使用者意圖（原句）

> 「可以幫我生成裡面文件可能的內容嗎  經過研究 我想生成30份類似我的產品需要的報告  包含專利內容文件和初審複審駁回書」

**解讀**：要 30 組假造但擬真的案例，每組包含：
- 1 份**專利文件**（TW 公開公報風格：title + 摘要 + claims + spec + IPC + 申請人 + 公開號）
- 1 份**初審審查意見通知函**（TIPO 格式）
- **約 6-8 組**另外含**再審查核駁審定書（複審駁回書）**，演示完整 prosecution timeline

用途：餵進 PatentMind demo corpus，讓 RAG 有變化、parse_oa 能展示多種 rejection_type、deadline 演示多個 ROC 日期。

### 30 案 Taxonomy（已規劃好，待產出）

| # | 技術領域 | 公開號 | 主要 Rejection | 受影響請求項 | 含複審？ |
|---|---------|--------|----------------|--------------|---------|
| 1 | 電動車充電站充電管理（已存在於 seed） | TW202617461 | §26-2 antecedent_basis | [9] | ❌ |
| 2 | 電動車電池熱管理 | TW202612345 | §22-2 進步性 | [1,2,3] | ❌ |
| 3 | 太陽能逆變器 MPPT | TW202611234 | §22-2 + §26-2 | [1-5, 7] | ✅ |
| 4 | 風力發電葉片設計 | TW202609876 | §22-1 新穎性 | [1,4] | ❌ |
| 5 | BMS / SOC 估測 | TW202608765 | §22-2 進步性 | [1-3] | ❌ |
| 6 | 智慧電網需量反應 | TW202607654 | §26-4 支持要件 | [6,7] | ❌ |
| 7 | 無線充電線圈對位 | TW202606543 | §22-2 進步性 | [1,2,5] | ✅ |
| 8 | LED 驅動 IC | TW202605432 | §22-2 進步性 | [1] | ❌ |
| 9 | 半導體封裝散熱 | TW202604321 | §26-1 揭露不充分 | [3,4] | ❌ |
| 10 | 5G 毫米波天線陣列 | TW202603210 | §22-2 進步性 | [1,2] | ❌ |
| 11 | IoT 低功耗廣域 (LPWAN) | TW202602109 | §22-1 新穎性 | [1] | ❌ |
| 12 | AI 製造瑕疵檢測 | TW202601098 | §22-2 + §26-2 | [1,3,8] | ✅ |
| 13 | LiDAR 點雲處理 | TW202600987 | §24 法定不予（純演算法） | [10] | ❌ |
| 14 | 醫療 CT 影像分析 | TW202598765 | §22-2 進步性 | [1-4] | ❌ |
| 15 | 穿戴式生理感測 | TW202597654 | §26-2 antecedent_basis | [5] | ❌ |
| 16 | 智慧手錶心率演算法 | TW202596543 | §22-2 進步性 | [1,2,3] | ✅ |
| 17 | 手術機器人控制 | TW202595432 | §26-4 支持要件 | [7] | ❌ |
| 18 | 藥物緩釋微粒 | TW202594321 | §22-2 進步性 | [1] | ❌ |
| 19 | 生物可降解骨支架 | TW202593210 | §22-1 新穎性 | [1,2] | ❌ |
| 20 | 食品保鮮包裝 | TW202592109 | §22-2 進步性 | [1-3] | ❌ |
| 21 | 鋰電池電解液添加劑 | TW202591098 | §22-2 + §26-2 | [1,4,5] | ✅ |
| 22 | 固態電池正極材料 | TW202590987 | §22-1 新穎性 | [1] | ❌ |
| 23 | 氫燃料電池雙極板 | TW202589876 | §22-2 進步性 | [1,2,3] | ❌ |
| 24 | 海水淡化薄膜 | TW202588765 | §22-2 進步性 | [1,5] | ❌ |
| 25 | 廢水處理光觸媒 | TW202587654 | §26-1 揭露不充分 | [3] | ❌ |
| 26 | 半導體蝕刻氣體 | TW202586543 | §22-2 進步性 | [1] | ✅ |
| 27 | 光阻劑配方 | TW202585432 | §22-1 新穎性 | [1,2] | ❌ |
| 28 | 量子點顯示器 | TW202584321 | §22-2 進步性 | [1,2,3] | ❌ |
| 29 | 折疊手機鉸鏈 | TW202583210 | §26-2 antecedent_basis | [4,8] | ❌ |
| 30 | 機器手臂力回饋 | TW202582109 | §22-2 + §32 一案兩請 | [1] | ✅ |

**複審共 7 案**：3, 7, 12, 16, 21, 26, 30。

**Rejection 類型分布**：
- §22-1 新穎性: 5 案（4, 11, 19, 22, 27）
- §22-2 進步性: 12 案（2, 5, 7, 8, 10, 14, 16, 18, 20, 23, 24, 28）
- §26-1 揭露不充分: 2 案（9, 25）
- §26-2 明確性 / antecedent_basis: 3 案（1, 15, 29）
- §26-4 支持要件: 2 案（6, 17）
- §24 法定不予: 1 案（13）
- §32 一案兩請: 1 案（30）
- 多重 rejection（§22-2 + §26-2）: 4 案（3, 12, 21, 30）

### 計畫的檔案產出結構

```
data/cases/
├── synthetic_cases.py        # 主要：CASES = [dict × 30] + render_*() helpers
├── manifest.json             # 30 案 index（case_id, title, rejection types, has_reexam）
└── CASE-DEMO-NN/             # 30 個 folder（NN = 01..30）
    ├── patent.txt            # TW 公開公報風格全文（title/摘要/claims/說明書節錄）
    ├── oa.txt                # 初審審查意見通知函（TIPO 格式 2 頁）
    └── reexam.txt            # 僅 7 案有：再審查核駁審定書

scripts/
└── render_cases.py           # 從 synthetic_cases.py 寫出上述 folder + manifest.json
```

每個 dict 大致長這樣（簡化版）：
```python
{
    "case_id": "CASE-DEMO-002",
    "patent": {
        "patent_no": "TW202612345",
        "title": "電動車電池模組之相變化熱管理裝置",
        "abstract": "...",                      # 2-4 句
        "claims": ["1. 一種...", ...],          # 5-8 項，含獨立 + 附屬
        "spec_text": "...",                     # 約 6-10 行，分節
        "filing_date_roc": (113, 5, 12),
        "publication_date_roc": (115, 4, 1),
        "ipc": ["H01M10/65"],
        "applicants": ["某某能源科技股份有限公司"],
        "inventors": ["王某", "李某"],
        "jurisdiction": "TW",
    },
    "oa": {
        "doc_type": "初審審查意見通知函",
        "date_roc": (114, 6, 15),
        "doc_no": "11420654321",
        "examiner": "張某某",
        "response_months": 2,
        "rejections": [{
            "statute": "專利法第22條第2項",
            "rejection_type": "103_obviousness",
            "affected_claims": [1, 2, 3],
            "cited_prior_art": ["TW201912345", "US10123456"],
            "argument": "...",                  # 2-3 句審查官論點
        }],
    },
    "reexam": None,  # 或 dict（同 oa 結構但 doc_type="再審查核駁審定書"）
}
```

---

## 5. 接手者的具體下一步

**TaskList 目前狀態**：
- #1~#6：✅ 全部完成（Phase A）
- #7 Draft 30-case taxonomy → ✅ 已完成（taxonomy 表在本文件第 4 節）
- #8 Write synthetic_cases.py → 🚧 **in_progress（這就是接手點）**
- #9 Add render helpers + extractor script → ⏳ pending
- #10 Generate per-case files → ⏳ pending
- #11 Smoke-test 3 random new cases → ⏳ pending

### 接手步驟

1. **創建 `data/cases/synthetic_cases.py`**
   - 一個 `CASES: list[dict]` 包 30 個 case
   - 每個 case 用上面的 dict 模板
   - 直接逐案撰寫（按 taxonomy 表的順序），確保 claims 與 rejection 在語意上吻合（例如 §26-2 antecedent_basis 的 case，claims 中要真的有一個沒先行詞的用語）

2. **同檔加 render 函式**
   - `render_patent_text(case) -> str`：產出 TW 公開公報風格文字
   - `render_oa_text(case) -> str`：產出 TIPO 初審通知函格式（可參考 `data/oa_samples/sample_oa_tw.txt` 的版面）
   - `render_reexam_text(case) -> str`：產出再審查核駁審定書格式

3. **創建 `scripts/render_cases.py`**
   ```python
   # 偽碼
   from data.cases.synthetic_cases import CASES, render_patent_text, render_oa_text, render_reexam_text
   for case in CASES:
       folder = Path(f"data/cases/{case['case_id']}")
       folder.mkdir(parents=True, exist_ok=True)
       (folder / "patent.txt").write_text(render_patent_text(case), encoding="utf-8")
       (folder / "oa.txt").write_text(render_oa_text(case), encoding="utf-8")
       if case.get("reexam"):
           (folder / "reexam.txt").write_text(render_reexam_text(case), encoding="utf-8")
   # 再產出 manifest.json
   ```

4. **跑一次 `python scripts/render_cases.py`**，檢查產出。

5. **冒煙測 3 個 random case**（mock 模式即可，不需要 Ollama）：
   - 選一個 §26-2、一個 §22-2、一個有複審的
   - 用 Phase A 的 `_orchestrate_analysis` 同樣手法測 parse_oa 是否分類正確、deadline 是否從 ROC 日期算出

### 重要約束（CLAUDE.md 提醒）

- ❌ 不要為了 demo 而違反 CLAUDE.md 鐵律（不要加 endpoint 跳過 redaction、不要 cross-user cache、不要把 mapping table 拉出 `data/`）
- ❌ 不要新建 `*.md` 文件（除非使用者明確要）。本 HANDOFF.md 是使用者明確要求的例外
- ❌ 不要加 emoji 到產出檔案（除非使用者要）
- ✅ 直接編現有檔案優於新建檔案，但 `data/cases/` 與 `scripts/render_cases.py` 是「合成資料目錄」的合理新建
- ✅ 中文檔案要 UTF-8（Windows 上 `python -c` 要 `PYTHONUTF8=1` 或 `io.TextIOWrapper`，否則 cp1252 會炸）

### Windows 環境眉角

- pdftoppm 不存在於這台機器；pdftotext 有（在 `C:\Program Files\Git\mingw64\bin\pdftotext.exe`）
- Chinese 檔名直接傳給 pdftotext 會 mojibake，要先 `cp` 到 ASCII 名再萃取
- Git Bash 與 PowerShell 都可用；本 session 使用 Bash 為主（透過 `Bash` tool，可跑 POSIX）

---

## 6. 一些尚未決定的事（如果使用者再被問可以幫忙釐清）

- 30 案的**目標格式**：目前計畫產出 plain text。如果要產出 PDF（更像原始素材），需另外裝 ReportLab/WeasyPrint，POC 沒這個依賴。建議先 plain text，要 PDF 再說。
- 每個 patent 的**完整 spec_text 篇幅**：原始 TW202617461 的說明書 46 頁，合成 30 份各 46 頁不現實。計畫每份產 ~8-12 行 spec_text（足夠 RAG chunking + retrieval 演示）。
- 是否**真的種進 RAG**：seed.py 加 30 patent 進去會讓 RAG 在 demo 時動作慢一些（首次 embedding）。可以保留為「optional 載入」，預設只跑既有 4 個 demo patent + TW202617461。

---

## 7. 截至這個視窗結束的檔案 git 狀態

```
M README.md                          ← 不是這個 session 改的，session 開始前就 M
M backend/ai_engine/llm_client.py    ← 本 session Phase A 改
M backend/ai_engine/oa_analyzer.py   ← 本 session Phase A 改
M backend/patent_db/seed.py          ← 本 session Phase A 改
M backend/shared/config.py           ← 不是這個 session 改的
M backend/shared/models.py           ← 本 session Phase A 改 RejectionType enum

新增（未追蹤）：
?? data/oa_samples/sample_oa_tw.txt  ← Phase A 新增
?? HANDOFF.md                        ← 本檔
?? backend/minimal/                  ← session 開始前就存在
?? docs/MVP_DEMO.md                  ← session 開始前就存在
?? docs/初審審查意見通知函.pdf        ← 原始素材
?? docs/專利文件.pdf                  ← 原始素材
?? scripts/smoke_test.py             ← session 開始前就存在
?? scripts/start_minimal.sh          ← session 開始前就存在
?? frontend/package-lock.json        ← session 開始前就存在
?? .analyze_result.json              ← session 開始前就存在
```

**本 session 沒有 commit**。Phase A 改動全部在 working tree。

---

## 8. 給接手 Claude 的一句話

> Phase A 已驗證可跑，請從第 5 節的步驟 1 開始：直接動手寫 `data/cases/synthetic_cases.py` 的 CASES list，按第 4 節 taxonomy 表逐案造資料。先不用太完美，30 案造完後再回頭微調。沒問題就接著做 render + extractor + 冒煙測。Mock 模式（`LLM_MODE=mock EMBEDDING_BACKEND=mock VECTOR_BACKEND=memory`）就足夠驗證，不用 Ollama。
