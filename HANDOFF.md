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

---

# 2026-05-30 session — Phase 1 + Day 1-6 wrap-up

> 這 session 把 POC 推進到「下週可上線 internal demo」狀態。
> 11 commits 落地，pytest 12/12 + vite build 全綠。
> Section 0-8 是 2026-05-12 的歷史，下面 9-15 是這 session 的全部產出。
> Section 12 (presenter notes) 是 demo 當天直接念的台本。

## 9. 完成的 commit (11 個，都在 local feature/patentmind-poc — 卡 push auth 見 §11)

```
0dfdfca Day 6: mock LLM rewrite (53% → 100% rejection_type) + ngrok demo helper
a343cea Day 5: Sentry observability — backend + frontend (env-gated, no-op without DSN)
17613af Day 4: one-click local demo launcher + pre-demo smoke validator
06d2ef6 Day 3: frontend polish — landing page, error/empty/loading UX, toast
73c1245 Day 2B: drag-drop PDF upload UI + preview pane
3552e50 Day 2A: PDF/DOCX upload endpoint with Vision OCR fallback
b93354a Day 1B: eval harness over 30 synthetic cases
3c1adae Day 1A: wire real Anthropic LLM (LLM_MODE=anthropic)
7153e89 Phase 1C: pytest + Playwright + GitHub Actions CI + pre-commit
3e26e35 Phase 1B: real Tailwind build + shadcn foundation + router + i18n + dark mode
0f7cb74 Phase 1A: docker-compose infra + env template + config knobs
```

### Per-commit summary
- **Phase 1A**: docker-compose (PG/Redis/Qdrant 都 loopback-bound + healthchecked), `.env.example` 全改, JWT secret runtime guardrail (非 mock/test 模式若用 placeholder 啟動會 raise)
- **Phase 1B**: 移除 Tailwind CDN → 正規 Vite+PostCSS, shadcn Button + cn helper + components.json, react-router-dom v6 routes (/login /analyze /audit /cases), ThemeProvider (localStorage-backed, FOUC-proof), react-i18next (zh-TW default + en fallback)
- **Phase 1C**: `pyproject.toml` (pytest + ruff + mypy), `tests/` (6 pytest passes), Playwright config + 1 smoke spec, `.github/workflows/ci.yml` (3 parallel jobs, main-safe concurrency), `.pre-commit-config.yaml`
- **Day 1A**: `AnthropicLLM` (AsyncAnthropic, Sonnet 4.6 reasoning + Haiku 4.5 cheap/verifier, prompt caching ephemeral on system, retry-after RFC 7231 HTTP-date parsing, threadsafe `_session_usage`, defense-in-depth confidential routing 3 層), `_MODEL_PRICING_USD_PER_M` 真實 Anthropic 價格表
- **Day 1B**: `scripts/eval_cases.py` 跑 30 案 → 寫 `data/eval_results/<TS-uuid6>/{CASE-DEMO-NN.json, REPORT.md}` (mode mock | anthropic, asyncio.gather + Semaphore, hermetic in-process orchestrator)
- **Day 2A**: `POST /v1/oa/upload` multipart (max 30MB, content-type whitelist), AI engine `/v1/ai/extract_text` (base64 JSON), `pdf_parser.extract_pdf_text` (PyMuPDF + bounded-parallel Vision OCR), `python-docx`. Defense-in-depth: gateway refuse confidential cases → AI engine 也 refuse → AnthropicLLM.vision_ocr 也 refuse
- **Day 2B**: `OAUpload.jsx` (state machine: idle→file-selected→uploading→server-extracting→success/error), XHR upload progress + real cancel, PDF preview via `<embed>`, integrated into `Analyze.jsx` as additive path (toggle 「📋 改貼文字」保留 fallback)
- **Day 3**: Login 變正規 landing (gradient hero + 4 value bullets + role cards w/ hover lift), `ErrorBanner` (8 status codes — 401 給登入按鈕, 429 給 30s countdown), `Skeleton`/`SkeletonText`/`SkeletonCard`/`EmptyState`/`toast`, /cases 變正式 coming-soon, favicon SVG + meta description + theme-color
- **Day 4**: `scripts/start_demo.sh` (python deps check → ai_engine + gateway + seed + frontend → auto-open browser → Ctrl+C tear-down), `scripts/smoke_demo.sh` (6-step pre-demo e2e validator)
- **Day 5**: `backend/shared/observability.py` (init_sentry with FastAPI + Starlette integrations), `frontend/src/lib/sentry.jsx` (initSentry + SentryErrorBoundary with friendly fallback UI), env-gated VITE_SENTRY_DSN / SENTRY_DSN
- **Day 6**: `_mock_parse_oa` 重寫 — 改正 5 個 weakness (102_novelty TW Chinese, other / 101 catch, multi-rejection emission, parsed affected_claims, antecedent_basis 近鄰判斷)；`scripts/start_ngrok.sh` 單 tunnel 暴露 frontend

## 10. 怎麼跑 — one-click demo

### 最常用 (mock 模式，不用 key)
```bash
bash scripts/start_demo.sh
# Auto: deps → ai_engine:8011 → gateway:8010 → seed → vite:5173 → open browser
# Ctrl+C cleanup all 3

# 另一 terminal:
bash scripts/smoke_demo.sh
# 6 GREEN = demo ready
```

### Real LLM (週日 key 到手後)
```bash
ANTHROPIC_API_KEY=sk-... bash scripts/start_demo.sh
# 自動切 LLM_MODE=anthropic (start_demo.sh 偵測 env)

# 跑 30 案 real LLM eval (對比 mock baseline):
ANTHROPIC_API_KEY=sk-... python scripts/eval_cases.py --mode anthropic
# 預計 token cost ~$2-5 (30 案 × ~50K tokens with cache)
# 報告: data/eval_results/<ts>/REPORT.md
```

### Remote demo audience
```bash
# Terminal 1:
bash scripts/start_demo.sh
# Terminal 2:
bash scripts/start_ngrok.sh
# → 印 https://<random>.ngrok.app URL，audience 開這個
```

## 11. Push status — 卡 GitHub auth (你還沒修)

Remote `https://github.com/Adrian-Kao/shin-lee.git`，password auth 已被 GitHub 停用。**11 commit 卡 local，沒 backup**。

修法（任一即可）：
1. **PAT (Personal Access Token)** — 最快
   ```bash
   # GitHub → Settings → Developer settings → Personal access tokens → Generate (scope: repo)
   git remote set-url origin https://Adrian-Kao:<TOKEN>@github.com/Adrian-Kao/shin-lee.git
   git push
   ```
2. **SSH key**
   ```bash
   ssh-keygen -t ed25519 -C "your@email.com"   # 貼 ~/.ssh/id_ed25519.pub 到 GitHub SSH keys
   git remote set-url origin git@github.com:Adrian-Kao/shin-lee.git
   git push
   ```
3. **GitHub CLI**
   ```bash
   gh auth login
   gh repo set-default Adrian-Kao/shin-lee
   git push
   ```

修好告訴下個 Claude session 「push 修好了」，它會幫推。

## 12. Demo presenter notes — 拿來直接念

### 12.1 Pre-demo checklist (T-30 min)

- [ ] `git pull` 最新（push 修好的話）
- [ ] 確認 `.env`: `JWT_SECRET` 不是 placeholder + `ANTHROPIC_API_KEY` 有值
- [ ] `bash scripts/start_demo.sh` — 等「Demo ready」訊息
- [ ] `bash scripts/smoke_demo.sh` — 6 個 GREEN
- [ ] 瀏覽器 http://localhost:5173 — 登入 Alice 跑一次確認流暢
- [ ] `docs/初審審查意見通知函.pdf` 放桌面備用
- [ ] 若用 ngrok：`bash scripts/start_ngrok.sh`，URL 貼 chat

### 12.2 The pitch (5 分鐘)

1. **問題 (1 min)** — 台灣 TIPO 每年 71,965 件專利申請 (2025 數字), 平均 8 個月才收到第一次 OA, 律師收到 OA 必須 2 個月內答辯, 每件人工平均 4-8 小時; 案件量+人力不足 → 答辯品質下滑風險
2. **解法 (1 min)** — PatentMind = OA 答辯草擬 AI 助手, 上傳 OA PDF → 自動 (a) 分類核駁理由 (b) RAG 找佐證 (c) 起草申復書 (d) 算法定期日, 律師審核+簽核+送件, AI 是放大器不取代律師
3. **差異化 (1 min)** — vs 競品 DeepIP / Solve Intelligence / Harvey / Lexis+ Protégé:
   - **TW 特化**: 中文 OA + 民國日期 + TIPO 公文格式 + 第26條第2項先行詞獨立 enum
   - **隱私可控**: redaction (Q10) + audit chain (Q13) + 機密案件強制地端 LLM (Q15)
   - **可驗證**: 每段 citation 必來自 grounded set (Q14), 防 hallucination
4. **架構 (1 min)** — 厚 Gateway + AI Engine 分層 (Q1+FU), 8 條鐵律 (CLAUDE.md §4)
5. **狀態 (1 min)** — POC 已 30 案 corpus + 真 Anthropic 接通 + PDF upload 含 Vision OCR + 一鍵 demo

### 12.3 The demo (5-10 分鐘) — 照順序操作

**段 1: Landing + login (30s)**
- 開 http://localhost:5173 — 看 gradient hero + value bullets
- 點 Alice (Attorney, tenant_a)
- 講: 「Bob paralegal 同租戶但案件 ACL 不同; Carol IT admin 無 case 權限; Dave auditor 只能讀 audit」

**段 2: 上傳 OA + 分析 (3-5 min)** — 核心 demo
- 拖 `docs/初審審查意見通知函.pdf` 到 drop zone
- 看 PDF preview (左) + status pane (右) 出現
- 點「上傳」— 進度條
- 講: 「PyMuPDF 萃取, 掃描頁 fallback 到 Claude Vision OCR」
- 出 success: 「已抽出 2 頁 / 1234 字」
- 點「使用此文字」— textarea 自動填
- 點「預覽 redaction」— 看 PII + 客戶識別碼被 redact (Q10)
- 點「分析 OA」— RunningPanel 動畫 (mock 即時; real LLM 約 30-60 秒)
- 出結果:
  - **Deadline card**: 2025-07-28 (從民國 114 年 5 月 29 日算出 +60 天)
  - **Rejection block**: antecedent_basis, claim=[9], confidence 0.93
  - **Examiner argument**: 中文原文
  - **RAG**: TW202617461#claim_2 (我們種的 patent, retrieval 命中)
  - **Draft**: 完整 TIPO 申復書格式, DraftEditor 可逐句簽核 (Q16)

**段 3: Audit + chain verify (1-2 min)** — 合規賣點
- 登出，登入 Dave (Auditor)
- 進 /audit → 看剛才兩筆 (upload + analyze) 都記錄
- 注意 `mask 規則` 欄 — 證明 redaction 真的觸發
- 注意 `policy` 欄 — 證明 authz/quota/RPM 都 pass
- 點「驗證 hash chain」— 綠燈 + 「N 列全部通過 hash 驗證」
- 講: 「Production 加 S3 Object Lock 每小時封存」

**段 4: 案件 ACL (30s)** — 隱私賣點
- 登出，登入 Carol (IT Admin, tenant_b)
- 嘗試輸入 CASE-2025-001 (tenant_a 的) + 分析
- 看 ErrorBanner 「您沒有此案件的存取權限」
- 講: 「防線在 gateway middleware (Q12), AI Engine 永遠收不到請求」

### 12.4 邊角值得提

- **Citation 必須 grounded**: verifier 砍編造引用 (Q14)
- **機密案件強制地端 LLM**: case_id 以 `-CONF` 結尾自動 route Ollama (Q15)
- **30 案 eval**: `python scripts/eval_cases.py --mode mock` 0.2s 出 markdown 報告
- **Sentry 接好 no-op**: 設 `SENTRY_DSN` 即啟用

### 12.5 Backup plan

| 故障 | 備案 |
|------|------|
| Anthropic API 掛 | mock mode 仍 work — 「切回 mock 證明架構解耦」 |
| Vite 卡 | refresh, 不行就 Ctrl+C + 重啟 start_demo.sh |
| PDF upload 失敗 | 改貼文字 toggle, 貼 `data/oa_samples/sample_oa_tw.txt` 內容 |
| Backend 死 | 看 `tmp/gateway.log` / `tmp/ai_engine.log`, 通常重啟 |
| Backend 起不來 | 確認 `.env` JWT_SECRET 不是 placeholder (Day 1A guardrail) |
| ngrok 限速 | free tier 同時 1 條 tunnel, 多人連會慢 — 用螢幕分享代替 |

## 13. External research (2026-05-30 web search snapshots)

### 13.1 Taiwan TIPO market 2025
- 71,965 patent applications (-1% YoY), 97,411 trademark (+8% YoY)
- First OA average: 8 months (improved from 2024)
- Total pendency: 13.8 months
- Foreign filings +0.6%, domestic -2.7% — foreign 比重持續增加
- **Implication**: 外國申請 → 英/日文 OA 需 TW 律師翻譯, i18n + 多語言 LLM 很重要

### 13.2 Competitive landscape

| 工具 | 形式 | 價格 | 強項 | 弱項 |
|------|------|------|------|------|
| **Harvey** | Web | $1000+/user/mo | broad legal, Assistant+Vault+Workflow, AmLaw 採用 | 不是 patent-specific, $$$ |
| **Westlaw/CoCounsel** | Web+Word | $200-500/user/mo | source-grounded, patent 模組 | US-focused, 無 TW |
| **Lexis+ Protégé** (rebranded Feb 2026) | Web | $200-400/user/mo | source-grounding | US-focused |
| **DeepIP** | Word add-in | n/a | full-lifecycle patent, drafting→prosecution | 無 on-prem |
| **Solve Intelligence** | Web | n/a | browser-based, claim charts + figures | 無 TW 中文, 無 on-prem |
| **PatentPal** | Web | <$1000/mo | terminology + flow diagrams | paralegal 為主, 非 OA |
| **PatentMind (us)** | Vite SPA | TBD | **TW-specific + on-prem + redaction + audit chain + grounded citations** | POC, 未實戰 |

**Pitch 差異化**:
- vs Harvey/Westlaw/Lexis: 「他們是 general legal, patent 不是核心」
- vs DeepIP/Solve: 「美式 prosecution 為主, 沒 TW §22/§26/§32 分類, 沒民國日期, 沒 TIPO 公文」
- 我們: 「TW 事務所專用 + 合規 + 機密不上雲 + 開放 30 案 baseline」

### 13.3 Anthropic 最佳實務 (對我們 demo / prod 直接相關)

**Prompt caching (Day 1A 已接好)**
- TTL: 預設 5 分鐘 (2026 初從 60 分鐘改的; 某些 workload cost +30-60%)
- 1 小時 cache 額外付費可用 (API/Bedrock/Vertex/Foundry)
- 我們把 patent-specific system prompt (2-4 KB) 標 ephemeral cache_control → 重複 case 第二次省 ~25% cost
- Workspace-level isolation (Feb 5, 2026): demo+prod 同 key 可控

**1M context window (Sonnet 4.6, GA March 2026)**
- 我們 oa_analyzer 一次只塞 OA + top-3 RAG hits (~10K tokens) — headroom 大
- 未來可一次塞整本 spec (~46 頁約 30K tokens) 給 draft step → 引用更準

**Batch API (50% cost savings, 300K output tokens beta)**
- 適合 eval pipeline: 30 案 batch → 一次 submit、隔天拿結果
- 適合定期 audit: 律師事務所每月把過去所有案件 re-analyze 看新 prior art

**Pricing (week 1 launch budget)**
- Sonnet 4.6: $3/M input + $15/M output, cache 90% off + batch 50% off
- Haiku 4.5: $1/M input + $5/M output (我們的 verifier + Vision OCR)
- 30 案 eval (real, no batch, no cache): ~$2-5
- 100 案/天 prod (with caching + batch): ~$5-10/day

**Sources** (research done 2026-05-30):
- [Union Patent TIPO 2025 stats](https://en.unionpatent.com.tw/overview-of-2025-taiwan-patent-and-trademark-filing-statistics)
- [DeepIP vs Solve Intelligence comparison](https://www.lexology.com/library/detail.aspx?g=a945581a-89b2-45ca-9a37-894711af9cdc)
- [Best AI Patent Drafting Tools 2026](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools)
- [Claude prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Sonnet 4.6 1M context guide](https://www.aiforanything.io/blog/claude-sonnet-4-6-1m-context-window-guide)
- [Anthropic 1M context GA announcement](https://dev.to/onsen/claudes-1m-context-window-is-now-generally-available-95f)

## 14. Next steps (週日 → 上線)

### 週日 (2026-05-31): real LLM smoke
1. 拿 ANTHROPIC_API_KEY → 加 `.env`
2. `bash scripts/start_demo.sh` → 看 「LLM_MODE=anthropic」 訊息
3. 上傳 `docs/初審審查意見通知函.pdf` → 看 real LLM output 品質
4. `python scripts/eval_cases.py --mode anthropic` → 跑 30 案 (~$2-5)
5. 比對 mock vs anthropic REPORT.md
6. 若 anthropic > 90% rejection_type + > 80% affected_claims → demo ready

### 週一 (2026-06-01): demo rehearsal
1. 跑 §12.3 demo flow (5-10 min)
2. 念 §12.2 talking points
3. 找朋友 mock 觀眾, 問會問什麼問題
4. 預備 §12.5 backup answers

### 週二-週六: buffer + soft launch
- T-3: 確認 internal 觀眾名單
- T-1: 重 smoke 一遍
- T-0: demo

### Phase 2 (上線後): production hardening
1. **Postgres audit** (current SQLite OK for pilot, swap > 1K rows/day)
2. **Redis cache** (Phase 2A 已開始 — 看 backend/gateway/redis_cache.py)
3. **Qdrant vector** (current numpy OK for < 1000 patents)
4. **OIDC** (Keycloak in docker-compose)
5. **Real PDF figure analysis** (Claude Vision 已接, 可擴大用途)
6. **Quality eval pipeline** (週/月律師抽樣評分)
7. **Prometheus + Grafana** (Sentry 是 error 層, 這是 metric 層)

## 15. 給接手 Claude 的一句話 (2026-05-30 版)

> POC 已推進到「下週可上線 internal demo」, 11 commit 落地但 push auth 卡 (§11). real LLM 路徑已接通但 demo 時還沒實機驗 (key 預定週日到手). 下個 session 優先序: (1) 確認 push 修好否 → push; (2) 真 LLM smoke (§14 週日 checklist); (3) demo rehearsal (§12 直接念); (4) 若還有時間 → Phase 2 chunks (從 backend/gateway/redis_cache.py 開始). §12 presenter notes 可以直接念給觀眾。

---

# 2026-06-01 session — Day 8 autonomous overnight sprint

> User asked for "資安和權限管理 + 前端 UIUX 產品等級 + 競品研究 + code review on
> everything" before going to sleep for 8 hours. This section documents what
> landed. 9 Day 8 commits, **120 pytests passing** (was 18 at session start),
> 0 breaking regressions on baseline.

## 16. Day 8 commit log

```
aa1e1e4 Day 8I: Security Chunks A/B post-review fixes — login rate limit + warnings
10775ee Day 8H: Security Chunk C — defense-in-depth headers + body caps + role gates
f389bc6 Day 8G: Security Chunk B — ACL bypass fix + audit row on every exit path (C-3 + H-7)
423520a Day 8F: Security Chunk A — lock front door (C-1 + C-2 + C-4 + H-8)
04071cf Day 8E: Three-pane Analyze workspace (UX_RESEARCH §5 #1 must-have)
95ad810 Day 8D: docs/UX_RESEARCH.md (competitor walkthroughs + workflow analysis)
9ac2356 Day 8C: Compat Refactor 3 — upstream-header auth for digiRunner front-line
492750f Day 8B: Compat Refactor 2 — first-class /v1/redact + /v1/audit/append
780bef3 Day 8A: Compat Refactor 1 — externalize prompts to YAML for Dify migration
```

Plus committed earlier this session: docs/SECURITY_AUDIT.md (30 findings), docs/UX_RESEARCH.md (8 must-have UX items).

## 17. What the Day 8 sprint accomplished

### digiRunner + Dify compatibility (user said "一定要能相容")
- **Day 8A**: All AI engine prompts (parse_oa / draft_response / verify_citations) moved from Python constants into `backend/ai_engine/prompts/*.yaml`. Dify workflows can `paste-import` these directly when migration happens. `GET /v1/prompts/{intent}` endpoint exposes them HTTP-style. Env-gated by `EXPOSE_PROMPT_API` (set false in prod once Dify import done).
- **Day 8B**: `/v1/debug/redaction_preview` promoted to first-class `/v1/redact` (deprecated alias kept with RFC 9745-compliant `Deprecation: @<unix>` header + Sunset + Link). New `/v1/audit/append` for digiRunner post-LLM hooks to push audit rows HTTP-style; `extra="forbid"` schema prevents identity forgery via body extras; `_AUDIT_APPEND_ROLES` whitelist.
- **Day 8C**: Gateway accepts `x-user-id` / `x-tenant-id` / `x-user-role` upstream headers from trusted IPs (digiRunner-validated identity), falls back to JWT for local dev. Role whitelist: AUDITOR / IT_ADMIN must come from local `_USERS` — upstream can only assert ATTORNEY / PARALEGAL (defense against confused-deputy via trusted-IP foothold). IPv4-mapped IPv6 normalized. CIDR rejected at config-load time (silent CIDR support would be a foot-gun). Boot guard refuses non-loopback trust without `UPSTREAM_AUTH_SHARED_SECRET` in non-mock mode.

### Product-grade UX (user said "前端 UIUX 要有產品等級")
- **Day 8D**: `docs/UX_RESEARCH.md` (2832 words, 56 URLs cited) — competitor walkthroughs (DeepIP / Solve Intelligence / Harvey / PatentPal / Lexis+ Protégé / Westlaw CoCounsel / NLPatent), patent attorney workflow analysis, 5-pattern UI library, 8 must-have + 6 nice-to-have UX recommendations with impact/effort ratings.
- **Day 8E**: Three-pane Analyze workspace (UX_RESEARCH §5 #1 must-have). Universal pattern across DeepIP / Solve / Patlytics — "tab switching" was the #1 cited UX pain. Desktop `≥xl`: 3-pane grid `[3fr 4fr 3fr]` (InputPane / DraftsPane / ReferencesPane), each scrolls independently, shared `activeRejectionId` state, sticky pane headers. Tablet/mobile `<xl`: tabbed single-column. `Analyze.jsx` slimmed 588 → 310 lines. Bundle +6KB raw / +1.5KB gz. ZERO new deps.

### Security + permission hardening (user said "資安和權限管理")
- **Day 8 audit deliverable**: `docs/SECURITY_AUDIT.md` — 30 findings (4 Critical, 8 High, 11 Medium, 7 Low) with file:line evidence + attack scenarios + recommended fixes + effort estimates.
- **Day 8F (Chunk A)**: Fixed C-1 (login mints token for any user_id with no credential — anyone reaching gateway could dump audit_dave's audit chain), C-2 (AI engine `:8011` had zero auth — anyone reachable could poison RAG / force public on -CONF / burn Anthropic budget), C-4 (JWT placeholder guardrail disabled in mock mode, which is the demo config), H-8 (login user enumeration via 404 vs 200). Added `_internal_headers()` on every gateway→AI engine httpx call; AI engine middleware refuses without `X-Internal-Token`. Demo passwords `demo-{user_id}` (sha256+salt+hmac.compare_digest; **POC ONLY** docstring per Day 8I), or `X-Demo-Secret` header for click-Alice frictionless UX (when `DEMO_LOGIN_SECRET` env set). `scripts/start_demo.sh` auto-generates secrets via `openssl rand` on first boot.
- **Day 8G (Chunk B)**: Fixed C-3 (ACL bypass — `auth.py` had a dead `_cached_body` read for body-bound case_id ACL that never fired; ACL silently passed for JSON POSTs omitting X-Case-Id) by gutting the branch + explicit `authorize_case_access(user, body.case_id)` after Pydantic parse. Fixed H-7 (invariant #4 violated on error path — only success/cache paths wrote audit row) via try/finally on every gateway endpoint. Added `_safe_audit_write` (swallows audit-DB errors so audit failure doesn't mask response). Header-vs-body case_id mismatch → 400 (confused-deputy defence).
- **Day 8H (Chunk C)**: SecurityHeadersMiddleware (CSP / HSTS / X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy on every response, even 4xx — clickjacking via 404 is still clickjacking). MaxBodySizeMiddleware (rejects > MAX_BODY_BYTES via Content-Length BEFORE Pydantic parse so 1GB attack doesn't burn memory). `extra="forbid"` + Pydantic `Field(..., max_length=N)` on every BaseModel. New `require_roles(*roles)` dependency factory. Role gates: /v1/oa/analyze + /v1/oa/upload + /v1/redact → ATTORNEY + PARALEGAL; /v1/quota → any; /v1/audit/* → AUDITOR. Env-driven CORS (specific methods+headers, no `*`). `LISTEN_HOST=127.0.0.1` default (was 0.0.0.0 — relied on dev firewalls).
- **Day 8I (post-review fixes)**: Login pre-auth rate limit (per-IP, default 10/min) — closes brute-force window on demo passwords. VITE_DEMO_LOGIN_SECRET loud warning ("dev builds only — vite inlines into JS bundle"). sha256 docstring loud warning ("POC ONLY — switch to argon2id/bcrypt for real user passwords").

### Code review on EVERYTHING (user mandate)
Each chunk got a dedicated reviewer agent before commit:
- Phase 1A/B/C (earlier sessions): 3 reviewers
- Day 1A LLM wiring: reviewer (threadsafe / retry-after / etc.)
- Day 1B eval harness: reviewer (concurrency / badness comparison / etc.)
- Compat Refactor 1/2/3: 3 reviewers (Day 8 ran with stale-base mitigation)
- Security Chunks A+B combined: reviewer (verdict "Ship as-is, 6 Important deferred")
- Day 8I addresses the 3 highest-impact Important findings; remaining 3 are documented design tradeoffs

## 18. Status snapshot (post Day 8I)

| Metric | Value |
|---|---|
| pytest | **120 passed** (1 warning, pre-existing pydantic protected_namespace, silenced for AuditEntry+CostMeta in 8H) |
| Frontend build | `vite build` 269 → 275 KB (+6KB raw, +1.5KB gz) |
| Local commits ahead of origin | **22** (still NOT pushed — auth issue from §11 not resolved) |
| Compat-with-digiRunner+Dify | All Hard Blockers from `docs/COMPAT_AUDIT` resolved (prompts externalized, /v1/redact + /v1/audit/append first-class, upstream-header auth ready). Migration plan ready in §16-17. |
| Security findings closed | 4/4 Critical (C-1 C-2 C-3 C-4) + 4/8 High (H-1 H-2 H-6 H-7 H-8) + 2/11 Medium (M-1 M-9) |
| Security findings open | 4/8 High (H-3 H-4 H-5 — chunk D never spawned) + 9/11 Medium + 7/7 Low |
| UX recommendations shipped | 1/8 must-have (#1 three-pane). 7 must-have + 6 nice-to-have remaining. |

## 19. What you should do when you wake up

### 1. Push to origin (still blocked — §11 has 3 recipes)
22 commits sit local. Until pushed, lose laptop = lose 1 weekend of work.
```bash
# Pick one of:
git remote set-url origin https://Adrian-Kao:<PAT>@github.com/Adrian-Kao/shin-lee.git && git push
# OR set up SSH and: git remote set-url origin git@github.com:Adrian-Kao/shin-lee.git && git push
# OR: gh auth login + git push
```

### 2. Get the Anthropic API key into `.env`
Day 8F's `scripts/start_demo.sh` auto-generates JWT_SECRET / INTERNAL_TOKEN /
DEMO_LOGIN_SECRET on first boot. ANTHROPIC_API_KEY you set manually:
```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
bash scripts/start_demo.sh   # auto-detects key → switches LLM_MODE=anthropic
```
Then `python scripts/eval_cases.py --mode anthropic` to A/B against the mock baseline. Cost: ~$2-5 for all 30 cases.

### 3. Stakeholder demo dry-run
§12 presenter notes still valid. Day 8E's three-pane layout changes the visual — re-walk the demo flow once. Mobile fallback works at < 1280px.

### 4. Outstanding security work (if pre-pilot)
Open findings from `docs/SECURITY_AUDIT.md`:
- **H-3** (mock embeddings same vector across tenants) — Chunk D scope
- **H-4** (cross-tenant audit verify missing) — Chunk D scope
- **H-5** (JWT HS256 single secret, no rotation/revocation) — defer to OIDC migration
- **M-2..M-8 / M-10..M-11** (assorted: in-memory rate state reset on restart, missing CSP nonces in prod, sqlite check_same_thread, Unicode normalize before redaction, cache key uses raw text, etc.) — none blocking pilot
- **L-1..L-7** — all defer

### 5. Outstanding UX work (post-demo)
From `docs/UX_RESEARCH.md` §5, must-have items NOT yet shipped:
- **#2** Claim dependency tree in left rail (S effort, High impact — backend has the data)
- **#3** Inline citation hover-preview + click-to-source-pane (S effort, High impact — Q14 data exists)
- **#4** USPTO underline/strikethrough export from DraftEditor (S effort, High impact)
- **#5** Cmd/Ctrl+K command palette (M effort — Harvey baseline)
- **#6** Examiner-style review pre-submit check (S effort)
- **#7** Shared "Workroom" view (M effort — Lexis+ Workrooms is new bar)
- **#8** Bilingual UX hardening (S effort — language switcher in header)

## 20. 給接手 Claude 的一句話 (2026-06-01 版 — overnight wrap)

> 22 commits ahead of origin, 120/120 pytests pass, all 4 Critical security findings closed + 4 High + 2 Medium, three-pane UX live, digiRunner+Dify migration unblocked (prompts externalized + /v1/redact + /v1/audit/append + upstream-header auth ready), HANDOFF §16-20 has the complete play-by-play. Push auth still blocks (§11). Priorities when you wake up: (1) push to origin §19.1; (2) ANTHROPIC_API_KEY + real LLM smoke §19.2; (3) demo dry-run §12 (visuals refreshed by 8E); (4) Phase 2 Chunk D (H-3 + H-4 cross-tenant) if time. UX_RESEARCH §5 items #2-#8 are the next sprint after demo.

---

# 2026-06-05 session — Phase 3 migration planning

## 21. Phase 3 migration plan

> User explicitly chose digiRunner + Dify as the production landing stack
> ("我要使用 digirunner 和 dify"). This session produced planning + artefacts
> only — no backend or frontend code changed.

- **Comprehensive plan:** [`docs/PHASE3_MIGRATION.md`](docs/PHASE3_MIGRATION.md) — 11 sections covering goals/non-goals, target architecture (3-layer → 5-layer), stays-vs-moves table with file:line evidence, 4-phase rollout (3.1 design + shadow → 3.2 digiRunner front-line → 3.3 cutover → 3.4 cleanup), risk register, open questions for TPIsoftware contact.
- **Generated Dify workflow artefacts:** [`dify_workflows/`](dify_workflows/)
  - `analyze_oa.workflow.json` — main orchestrator DAG (replaces `backend/gateway/orchestrator.py`)
  - `extract_pdf.workflow.json` — PDF/DOCX upload → text (replaces `/v1/oa/upload` path)
  - `ocr_page.workflow.json` — per-page Vision OCR sub-workflow (refuses confidential)
  - `prompts_export.md` — paste-ready system prompts + JSON schemas, manual-setup fallback
- **Generated digiRunner config templates:** [`digirunner/`](digirunner/)
  - `routes.yaml` — design-intent route definitions + auth + rate-limit + AI policy refs
  - `oidc.yaml` — OIDC provider template with claim mapping + audit hook forwarding
  - `ai-gateway-models.yaml` — Anthropic + Ollama provider config, routing rules, cost tracking, confidential-routing rule
- **Design invariants preserved:** all 8 from `CLAUDE.md §4`. Audit chain stays authoritative in our thin gateway; redaction mapping table stays on-prem; verifier stays as Dify HTTP node calling our `/v1/verify_citations` (Q14 hard wall); confidential routing has three walls (digiRunner AI gateway rule + Dify IF/ELSE branch + our `llm_client.py:556-563` assert).
- **Next steps:** (1) socialise the plan with TPIsoftware contact — see §10 of PHASE3_MIGRATION.md for the 10 open questions; (2) stand up Dify sandbox + import workflow JSONs; (3) Phase 3.1 shadow mode against 30 synthetic cases via `scripts/eval_cases.py`.
- **No code changed.** Backend gateway/ai_engine/orchestrator paths untouched. 120 pytests should still pass — no edits to any tested path.
