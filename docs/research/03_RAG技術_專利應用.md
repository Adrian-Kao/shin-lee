# RAG 技術深度文件 — 專利／OA 場景的檢索增強生成設計

> 受眾：PatentMind 工程團隊。
> 對照現況：`backend/ai_engine/rag.py`（chunking + 向量 store）、`oa_analyzer.py`（grounded citations + verifier）、`retrieval_eval.py`（recall@k / MRR / nDCG / coverage 評測）。
> 設計命脈（CLAUDE.md 不變量 #5）：**「引用必須來自 grounded set」**。本文所有技術選型都圍繞這條展開。

---

## 0. 30 秒摘要

專利答辯（OA response）場景的 RAG 跟一般文件問答**不是同一個問題**。它要在超長、結構化、多語言、法律精確性零容忍的文件上，把**每個技術特徵（claim element）**對應到**早於申請日的具體前案段落**，而且引用錯一個前案可能直接害當事人喪失專利權。這意味著：純語意向量（dense-only）不夠、泛 chunking 會切爛 claim 結構、retrieval 必須帶 metadata 硬過濾（日期/法域）、生成端必須有獨立驗證牆。

現況 PatentMind 的骨架是對的（claim-tree chunking + 獨立 verifier + grounded-set 硬牆 + per-tenant 隔離 + 可插拔 backend），但 retrieval 品質目前被三件事壓住：(1) 預設 `mock`/`lexical` embedding 不是真語意，(2) **沒有 hybrid（BM25 + dense）也沒有 reranker**，(3) metadata 過濾只用到 jurisdiction，**沒有用申請日做前案時效過濾**——這是法律正確性缺口，不只是品質缺口。

### 三個關鍵 takeaway

1. **專利檢索必須 hybrid + rerank，不能 dense-only。** 元件編號、化學式、專有名詞要靠稀疏（BM25/SPLADE）精確命中；語意改寫要靠 dense。再用 cross-encoder reranker（如 `bge-reranker-v2-m3`，多語、~0.6B、可 CPU 跑）把 top-50 重排成 top-5。建議用 BGE-M3 一個模型同時產 dense + sparse + ColBERT 三種表示，省一套 infra。

2. **「前案必須早於申請日」要當成 retrieval 的硬性 metadata filter，不是事後檢查。** 現在 `rag.retrieve()` 只接 `jurisdiction`，chunk 裡有 `pub_date` 卻沒拿來過濾。一個晚於申請日的「前案」在法律上根本不能拿來核駁/答辯——retrieval 階段就該用 `pub_date < priority_date` 砍掉，否則 grounded set 本身就被污染。

3. **接地與防幻覺是分層的，verifier 只是其中一層。** 現有 `verify_citations` 的**正則硬牆**（stage a）才是真防線，verifier LLM（stage b）是獨立第二意見。要把這套延伸成「引用可回溯到具體 chunk/span」+ 用 `retrieval_eval.py` 持續量 recall@k / citation precision / faithfulness，切到真 embedding（BGE-M3）後把 gate 從 0.10 拉到 0.70。

---

## 1. 為什麼專利場景的 RAG 特別難

專利答辯場景疊加了六個一般 RAG 很少同時遇到的難點：

| 難點 | 一般 FAQ/客服 RAG | 專利／OA RAG | 對系統的要求 |
|---|---|---|---|
| **文件長度** | 數百~數千 token | 單一專利說明書常 2 萬~10 萬+ 字，圖式幾十張，claim 數十條 | chunking 不能破壞結構；long-context 與 RAG 要權衡 |
| **法律精確性** | 「大致正確」可接受 | 引用條號（35 U.S.C. §103 / 專利法第26條）、前案編號、claim 範圍須**字面精確** | 精確詞彙必須被 sparse/lexical 命中，不能只靠語意近似 |
| **接地粒度** | 文件級/段落級 | **claim element（技術特徵）級**——核駁是逐特徵比對，答辯也要逐特徵 | 要能把「單一技術特徵」當 query 去檢索、去對齊 |
| **多語言** | 通常單語 | 中（TW/CN）、英（US/EP）、日（JP）、韓（KR）混雜，常跨語檢索 | embedding 與 reranker 必須多語且支援 cross-lingual |
| **比對本質** | 語意相似即可 | 需要的是**結構化對應**（feature ↔ prior-art passage），不是泛語意相似 | 偏向 element-level 對齊檢索、claim chart 式輸出，甚至知識圖譜 |
| **幻覺容忍度** | 低 | **零**——答辯書引用不存在/不相關的前案，可能害當事人喪權、律師失格 | 引用必須來自 grounded set 且可回溯 span；獨立 verifier |

關鍵差異在於：**專利前案比對需要的是「結構化對應」而非泛語意相似。** 審查委員的核駁邏輯是「請求項第 1 項的特徵 A 對應到引證文件 D1 的第 [0023] 段，特徵 B 對應 D1 第 [0031] 段……」——這是一張 **claim chart**（請求項對照表，業界 XLSCOUT/Questel 等工具的核心輸出，待查證其內部技術）。RAG 系統若只把整條 claim 當一個 query 丟進去做 top-k 語意檢索，會錯過「某個特徵只在附屬項才出現、卻命中了另一篇前案」這種對應關係。

幻覺零容忍這點再強調一次：在大多數 RAG 應用裡，引用錯一筆來源是「品質瑕疵」；在專利答辯裡，引用一篇**晚於申請日的「前案」**或**根本不存在的判例**，是會出大事的法律錯誤。這就是為什麼 PatentMind 把 grounded-set 設成不變量 #5、把 verifier 設成「即使 prompt 看似可信也不能跳過」（CLAUDE.md §9）。

---

## 2. Chunking 策略

### 2.1 專利文件的天然結構

專利文件不是自由文本，它有強結構，chunking 必須順著結構切：

```
專利文件
├── 摘要 (abstract)            → 1 chunk
├── 說明書 (specification)
│   ├── 發明領域 / 背景 / 摘要 / 詳細實施方式  → 分節，節內再 sliding window
│   └── 圖式說明 (brief description of drawings) → 與圖號對應
├── 請求項 (claims)            → claim-tree（獨立項 + 其附屬項）
└── 圖式 (figures)             → 圖區偵測 + caption 對應（Q8，Vision 描述為 future）
```

通用 RAG 的「固定 N token 切塊」在專利上會犯兩個致命錯：(a) 把一條 claim 從中間切斷，破壞權利範圍的完整語意；(b) 把獨立項和其限縮特徵的附屬項拆到不同 chunk，導致檢索一個「只出現在附屬項的特徵」時撈不回它所屬的請求項家族。

### 2.2 claim-level vs paragraph-level，與 parent-child / hierarchical chunking

業界共識（2024-2025 的 production RAG 研究，見來源）是**結構感知（structure-aware）+ 階層式（hierarchical / parent-child）chunking** 優於盲目固定切塊：

- **paragraph-level（說明書）**：先依語意節（節標題）切，節內超過閾值再用 sliding window（帶 overlap），保留 parent 節標籤當 metadata。檢索命中小 chunk 時可回溯 parent 段落補上下文（parent-child / small-to-big 模式）。
- **claim-level（請求項）**：每條 claim 是一個語意單元，**不可橫切**。

### 2.3 為何 claim 要連同附屬項一起 chunk

這是專利 chunking 最關鍵的設計，PatentMind 已經做對了——`rag.py` 的 `chunk_patent()` 同時產兩種 claim chunk：

1. **per-claim chunk**（`claim_N`，`claim_no=N`）：單條 claim 文字，供 claim-tree UI 用。
2. **bundle chunk**（`claim_N_tree`，`claim_no=None`）：每個**獨立項**＋其**所有遞移附屬項**串接成一個 chunk，供 retrieval embedding 用。

理由（`rag.py:131-154` 註解講得很清楚）：當使用者用一個只存在於附屬項的限縮特徵（「…further comprising temperature sensors」）做 query，bundle chunk 能讓整個獨立項家族浮上來；而 per-claim chunk 維持單條完整性，讓 `parse_claim_dependencies` 的樹解析不會誤判。兩種 chunk 用 `claim_no` 是否為 `None` 區分，互不污染。這個設計值得保留。

### 2.4 對照現有 `rag.py` 的改進建議

| 現況 | 問題 | 建議 |
|---|---|---|
| sliding window 用 `chars/3` 當 token proxy（`_sliding_window`） | 跨語不準：CJK 一字常 ≥1 token，英文一 token 常 ≈4 char，`/3` 對中英都偏差 | 切到 bge-m3 後改用該模型 tokenizer 算長度（或 `count_tokens` 校準）；至少對 CJK / Latin 分開估算 |
| 節標題正則只有英文（`_SECTION_HEADINGS` 全英文） | TW/CN/JP 專利說明書節標題是中/日文（「發明所屬之技術領域」「先前技術」「實施方式」），會 fall back 到單一 `BODY` chunk，喪失節結構 | 加中文/日文節標題 pattern；無法辨識時退而求其次用段號（[0001] 式）切 |
| 圖式只做 region 偵測（Q8），Vision 描述是 future | 圖是專利核心揭露，目前 RAG 看不到圖內容 | 機密案僅地端 Vision；非機密可走 Claude Vision（見 §3.7 與 §7） |
| chunk metadata 已含 `pub_date`，但 retrieve 沒拿來過濾 | **前案時效（早於申請日）沒在 retrieval 把關**——見 §4.3，這是法律缺口 | 把 `pub_date` 升級成可過濾欄位 |

---

## 3. Embedding 選型

### 3.1 多語言專利檢索的 embedding 候選

| 模型 | 維度 | 多語 | 適合專利？ | 備註（含待查證） |
|---|---|---|---|---|
| **BGE-M3**（BAAI，2024-01） | 1024（dense）| ✅ 100+ 語、8192 token | ✅ 強推 | 一個模型同時出 **dense + sparse（lexical weights）+ ColBERT（multi-vector）**；MIRACL nDCG@10 dense 67.8、三路融合 70.0（超過 E5-large 65.4）。長 context（8192）對長 claim/段落友善。**PatentMind 現有 `EMBEDDING_BACKEND=bge-m3` 已支援。** |
| **E5 / multilingual-E5-large** | 1024 | ✅ | ⚪ 通用多語強，非專利專用 | MIRACL 略低於 BGE-M3 dense；無內建 sparse/ColBERT |
| **Qwen-3 Embedding** | 待查證 | ✅ | ⚪ | 近期多語檢索基準有與 BGE-M3 對比（來源），專利適配度**待查證** |
| **PatentSBERTa**（AI-Growth-Lab） | 768 | ❌ 主英文 | ⚪ 專利專用但單語 | SBERT 架構、在 150 萬筆 claim 上 fine-tune，CPC 分類 F1≈0.66；強在 patent-to-patent 相似度、IPC/CPC landscaping，**但非多語**，不適合 TW/JP/KR 主場景。可作英文專用增強或分類輔助。 |
| **patembed-base / PatenTEB 模型族** | 待查證 | 部分多語 | ✅ 專利專用 | 近期專利 embedding 基準（PatenTEB / 22-model 評測，2025-2026，來源）顯示**專利專用 + 多語訓練**模型在專利任務上優勢最大。**具體模型可用性與授權待查證**——值得追蹤但目前以 BGE-M3 為穩妥落地選擇。 |

> 涉及具體基準數字皆引用所附來源；PatenTEB 模型族的 production 可用性、授權、是否含中日韓，**待查證**後再評估替換 BGE-M3。

### 3.2 稠密 vs 稀疏 vs 混合，為何專利必須混合

- **稠密（dense）**：把文字壓成單一向量，擅長語意/改寫匹配（「散熱片」≈「heat sink」≈「導熱結構」）。**弱點**：對精確 token（元件編號 `132a`、化學式 `Li₆PS₅Cl`、型號、罕見專有名詞）容易稀釋——這些字在語意空間裡沒有「鄰居」，dense 反而抓不準。
- **稀疏（sparse / BM25 / SPLADE）**：基於詞頻與精確匹配。**強在**精確詞彙、編號、化學式；**弱在**同義改寫（query 與文件相關但無共同字時 BM25 無能為力，見來源）。
- **混合（hybrid）**：兩者分數融合（RRF / 加權）。production RAG 研究一致顯示 **hybrid + rerank 兩段式顯著優於任一單段**（一份基準：Recall@5 0.816、MRR@3 0.605，大幅勝過單段，見來源）。

專利場景**必須混合**，因為一條 claim 同時含語意概念（要 dense）和精確元件編號/化學式/法條（要 sparse）。只用 dense 會在「申請人就是靠某個特定數值範圍或元件編號區別於前案」時失準——而那往往正是答辯的勝負手。

### 3.3 對照現況

現有 `rag.py` 的 `Embedder` 支援 `mock | lexical | bge-m3` 三種 backend，但：
- `mock`：SHA-256 雜湊，**非語意**，cosine 近隨機（`retrieval_eval.py` 已明確警告 mock 數字無意義）。
- `lexical`：numpy-only hashing vectorizer，有**真詞彙重疊語意**（CJK 走 bigram，Latin 走 word token），air-gapped demo 可用，但仍非真稠密語意。
- `bge-m3`：真多語稠密——但**目前只用了 dense 那一路**，BGE-M3 的 sparse 與 ColBERT 能力沒被用上，向量 store 也只存單一 dense 向量。

**改進核心：把 BGE-M3 的 sparse + ColBERT 接起來做 hybrid。** 見 §4 與 §8 路線圖。

---

## 4. 檢索與重排

### 4.1 Hybrid search 流程

```
query (一條 claim / 一個技術特徵 / OA 核駁段落)
   │
   ├── dense 向量  ──► Qdrant 向量檢索（cosine）      ┐
   │                                                  ├─► RRF / 加權融合 ─► top-50 候選
   └── sparse 向量 ──► BM25 / SPLADE / BGE-M3 lexical ┘
                                                          │
                                            metadata 硬過濾（§4.3）
                                            jurisdiction ∧ pub_date < priority_date ∧ IPC?
                                                          │
                                                          ▼
                                          cross-encoder reranker（top-50 → top-5）
                                                          │
                                                          ▼
                                              grounded set → oa_analyzer
```

### 4.2 Reranker：cross-encoder vs ColBERT

第一段檢索（bi-encoder/BM25）為了快，query 與文件各自獨立編碼；**reranker 用 cross-encoder**，把 (query, 候選) 成對一起進模型做 joint attention，抓得到獨立編碼漏掉的細粒度關係（見來源）。代價是每個候選都要跑一次，所以只能重排小池（top-50→top-5）。

| 選項 | 參數量 | 多語 | 適合 PatentMind？ |
|---|---|---|---|
| **`bge-reranker-v2-m3`** | ~0.6B（MiniLM 系，可 CPU 跑小批） | ✅ | ✅ 首選——與 BGE-M3 同家族、多語、輕量，<100 對可 CPU；air-gapped 友善 |
| Jina Reranker v2 / Jina-ColBERT | 待查證 | ✅ | ⚪ ColBERT 式可處理 8000 token 長文，減少激進切塊需求（見來源）；授權/地端部署待查證 |
| 通用大型 cross-encoder | 大 | 視模型 | ⚪ 準度高但延遲高，不利即時 |

注意 reranking 有「倒 U」效應（見 long-context 來源）：候選給太多反而被無關段落分心，top-50→top-5 是合理起點，不要把 top-200 全餵 reranker。

### 4.3 Metadata 過濾——本系統最該補的一塊

**前案的本質是「早於申請日（priority date）的公開技術」。** 一篇 `pub_date` 晚於系爭專利申請日的文件，**法律上不能當前案**。現況 `rag.retrieve()`：

```python
# rag.py 現況 — 只接 jurisdiction
def retrieve(tenant_id, query, top_k=5, jurisdiction=None, prefer_patent_no=None):
    base_filter = {"jurisdiction": jurisdiction} if jurisdiction else {}
```

chunk metadata 裡明明有 `pub_date`（`chunk_patent` 每個 chunk 都塞了 `patent.publication_date.isoformat()`），卻**完全沒被當過濾條件**。這是法律正確性缺口，優先級高於一般品質優化。

建議的 metadata 過濾維度：

| 維度 | 來源 | 用途 |
|---|---|---|
| **`pub_date < priority_date`** | chunk metadata 已有 `pub_date`；申請日由 case 帶入 | **前案時效硬過濾**（最關鍵） |
| `jurisdiction` | 已支援 | 法域範圍 |
| IPC / CPC 分類 | 待補（需 patent_db 帶分類碼） | 技術領域收斂，提升 precision |
| `patent_no` | 已支援（`prefer_patent_no` 同案加權） | 同案聚焦 |

Qdrant 的 payload filter 支援範圍查詢（`pub_date` 用 datetime/range condition），`MemoryVectorStore.search` 目前只支援等值比對（`getattr(ch,k)!=v`），要擴成支援範圍過濾——兩個 backend 的 `VectorStore` 契約都要更新（`tests/unit/test_vector_store_contract.py` 一起加 case）。

### 4.4 claim-element 對齊的檢索

呼應 §1 的「結構化對應」：與其把整條 claim 當一個 query，**把每個技術特徵當一個 query** 分別檢索，再彙整成 claim-chart 式對應。流程：

```
claim → 拆解成 element 列表（element_table.py 已有 claim 結構解析）
   for each element:
       hybrid retrieve（帶 §4.3 過濾）→ 該特徵最相關的前案 span
   彙整 → feature ↔ prior-art passage 對應表（claim chart）
```

PatentMind 已有 `claim_tree.py` / `element_table.py` 做 claim 結構解析，element-level 檢索是自然延伸（見 §8 P2）。這也直接服務「審查委員逐特徵核駁、律師逐特徵答辯」的真實工作流。

---

## 5. 接地與防幻覺（本系統命脈）

### 5.1 現有分層防線（`oa_analyzer.py`）

PatentMind 的 `verify_citations` 是**兩段式**，分層很關鍵：

- **stage (a) 正則硬牆**：`_extract_citations` 抓出 draft 裡所有引用，逐一檢查是否屬於 `[GROUNDED_REF_N]` grounded set。不在 grounded set 又不是法條白名單（`_STATUTE_WHITELIST`，如 35 U.S.C. §103 / 專利法第26條這些 OA 本身就引、公開可查的）的引用，一律 `[CITATION_REMOVED]`。**這是真防線**——`result["valid"]` 純由此推導，verifier LLM 回什麼都改變不了它。
- **stage (b) verifier LLM**：獨立第二模型（`assert_verifier_independence()` 強制 ≠ drafter，anthropic 模式走 Haiku），只貢獻 `verifier_confidence`，並當作 prompt-injection 逃逸的第二道防禦（CLAUDE.md §9）。

這個「正則硬牆為主、LLM 為輔」的設計是對的——把法律正確性綁在確定性規則上，而非可被 prompt 操弄的模型輸出。

### 5.2 可回溯到具體 chunk / span

現況 grounded ref 對到的是 `RetrievalHit`（含 `patent_no`、`section`、`text[:600]`、`chunk_id`）。要強化「引用可回溯到具體 span」：

- grounded block 已帶 `chunk_id`（`RetrievalHit.metadata["chunk_id"]`），但 draft 裡的 `[GROUNDED_REF_N]` 目前只對到整個 chunk 的 600 字摘要。
- 建議：reranker/verifier 階段把命中**收斂到 chunk 內的具體 span（起訖字元 offset 或句子）**，存進 grounded ref metadata，UI 點引用可高亮原文那一句。這讓「引用可回溯」從 chunk 級進到 span 級，律師審閱時能一眼看到憑據。

### 5.3 Retrieval evaluation 指標（對照 `retrieval_eval.py`）

現有 harness 已經量四個指標，定義都對：

| 指標 | `retrieval_eval.py` 函式 | 意義 | 專利場景用途 |
|---|---|---|---|
| **recall@k** | `recall_at_k` | top-k 命中多少比例的相關前案 | Q6 核心 gate（目標 0.70） |
| **MRR** | `mrr` | 第一個相關命中的倒數排名 | 「最相關前案排多前」 |
| **nDCG@k** | `ndcg_at_k` | 排序品質（相關項排越前越好） | 區分「排第 1」vs「排第 5」 |
| **grounding coverage@k** | `grounding_coverage` | 回傳集裡多少比例相關（precision-like） | **Q14 直接關注**：grounded set 雜訊越低、引用品質越好 |

補充建議：
- **faithfulness / citation precision**：業界（RAGAS 等，見來源）有現成定義——faithfulness 把答案拆成 statement 逐句對 context 查證、context precision 量檢索集相關比例。`grounding_coverage@k` 已是 context-precision 的近似；可再加一個「draft 引用中 valid 比例」（draft citation precision），直接量 stage(a) 硬牆過後留下多少有效引用。
- **切到真 embedding 後把 gate 拉高**：`retrieval_eval.py` 現在 `DEFAULT_MIN_RECALL_AT_5=0.10`（mock 是雜訊，0.70 會 flaky red），`PROD_TARGET_RECALL_AT_5=0.70`（Q6 真目標）。**切到 `EMBEDDING_BACKEND=bge-m3` + hybrid + rerank 後，把 CI gate 從 0.10 棘輪上調到 0.70**，讓它變成真品質 gate。

---

## 6. 多租戶與機密性對 RAG 的影響

| 議題 | 現況 | 說明 |
|---|---|---|
| **per-tenant collection 隔離** | ✅ `QdrantVectorStore._coll(tenant_id)` → `patentmind_<tenant>` 一租戶一 collection | Q5/Q7 落地；retrieval 只在該租戶向量空間查 |
| **機密案僅地端 embedding/向量 store** | ✅ `EMBEDDING_BACKEND=bge-m3` 可全地端（sentence-transformers，offline-first `local_files_only`）；機密案 LLM 走本地 Ollama（不變量 #7） | 機密案的 embedding、向量、Vision OCR 都不離機 |
| **不可跨租戶污染（H-3）** | ✅ mock/lexical 用 tenant-salt（`_lexical_embed` 把 `tenant_id` 折進 hash bucket） | 防 similarity-oracle 攻擊：同一段文字在 tenant_a vs tenant_b 產生不同向量 |

幾點要注意：

- **H-3 salt 只對 mock/lexical 有意義。** 真 BGE-M3 是 content-only（語意相似就是它的目的，不能 salt），所以**真正的生產隔離靠 per-tenant collection 切分**，不是靠 salt（`rag.py:382` 註解已點明）。切到 bge-m3 + Qdrant 後，隔離責任完全落在 collection 邊界——務必確保任何新檢索路徑（hybrid 的 sparse 那一路、reranker 的候選撈取）**也都帶 tenant_id**，否則 sparse 索引可能變成跨租戶洩漏點。
- **embedding cache 也是 tenant-namespaced**（`_embedding_cache_key` 折進 `tenant_id`），跨租戶讀不到——加 sparse 後，sparse 表示的 cache key 也要同樣 namespace。
- **新增 reranker 的隔離**：reranker 本身無狀態（只對 (query, candidate) 打分），不存租戶資料，安全；但餵給它的候選必須已是該租戶過濾後的結果。

---

## 7. 進階方向

### 7.1 GraphRAG / 知識圖譜（claim-element ↔ 前案特徵的圖）

GraphRAG（微軟等推動，見來源）把語料建成實體-關係圖，能做主題級/全域級摘要與可追溯推理。專利場景的自然圖結構：

```
(claim element) ──maps_to──► (prior-art feature) ──disclosed_in──► (D1, [0023])
       │                              │
   part_of                       cited_by
       ▼                              ▼
 (independent claim)            (examiner rejection)
```

把「技術特徵 ↔ 前案特徵」建成圖後，可支援多跳推理（「特徵 A 像 D1，但 D1 沒揭露特徵 B，而 D2 有 B——審委用 D1+D2 組合核駁 §103 obviousness」）。這正是 claim chart 與顯而易見性答辯的核心。屬中長期方向，落地成本高，建議先把 hybrid+rerank 做穩。

### 7.2 Agentic retrieval（多輪查詢分解，呼應多-agent 需求）

Agentic RAG（2025 趨勢，見來源）讓 agent 自主規劃多步檢索：reflection、planning、tool use，比固定單跳 pipeline 更會處理多跳。對應到專利答辯：

```
OA core agent
 ├─ 分解：把核駁拆成「逐特徵子查詢」
 ├─ 對每個特徵：retrieve → reflect（這個前案真的揭露這特徵嗎？）→ 不夠再查
 ├─ 跨前案：D1 缺的特徵去 D2 找（多跳）
 └─ 彙整 → claim chart → drafter
```

PatentMind 的 §4.4 element-level 檢索是 agentic retrieval 的前置；要走全 agentic，可用 Claude 的 tool use 把「retrieve 一個特徵」做成工具，讓 reasoning 模型自主 fan-out。**注意**：agentic 多輪會放大 LLM 呼叫數與成本，且每一輪檢索仍要過 §4.3 過濾與 §5 verifier——不變量不能因為「agent 自主」而被繞過。

### 7.3 Long-context vs RAG 的取捨

2025 研究共識（見來源）：

- **開源/較弱模型**長 context 能力有限，RAG 收益大；**強閉源模型**長 context 較強，但餵太多會「lost in the middle」「資訊洪流」分心，呈倒 U 曲線。
- long-context 純餵全文 **token 不效率**，且放大分心。
- 新興共識是**整合兩者**：用 RAG 的 token 效率 + 接近 long-context 的覆蓋。

對 PatentMind：本專案 LLM 路由支援 `mock | anthropic | local(Ollama qwen2.5:7b) | dify`。Claude 最新模型（Opus 4.8、Sonnet 4.6 皆 **1M context**；Haiku 4.5 為 **200K**）長 context 很強，理論上能把整篇前案丟進去。但**不建議放棄 RAG**：
1. 機密案走本地 `qwen2.5:7b`，長 context 與分心問題明顯，RAG 仍是命脈。
2. 即使用 Claude 1M context，幾十篇候選前案塞滿仍會分心 + 貴 + 慢，且**破壞「引用來自 grounded set」的可控性**——grounded set 是刻意把模型能引用的範圍收斂到檢索結果，這是防幻覺的設計，不該為了 long-context 放棄。
3. 務實做法：RAG 收斂到 top-5 grounded set，再用 Claude 長 context 對這 5 篇做深度比對與 claim chart。**prompt caching** 對重複前置（系統 prompt、grounded set 前綴）可省 ~90% 快取輸入成本（Claude 快取讀 ~0.1×），長 grounded block 重複查時值得用。

### 7.4 Reranking 與 RAG 評測 harness

`retrieval_eval.py` 已是現成 harness。加 hybrid + rerank 後，把它擴成**分段消融**：dense-only → +sparse(hybrid) → +rerank，各跑一次 recall@5 / nDCG@5 / coverage@5，量出每一段的增益（也驗證 reranker 沒有反而變差）。`scripts/eval_cases.py` / `eval_compare.py`（Q19 eval harness）可掛這套對比。

---

## 8. 落地路線圖

> 原則：先補**法律正確性**缺口（前案時效過濾）與**檢索品質**地基（真 embedding + hybrid + rerank），再上 element-level 與進階。每階段標清楚改哪個檔案。

### 階段 0（現況 baseline）
- `EMBEDDING_BACKEND=mock|lexical`、`VECTOR_BACKEND=memory|qdrant`、dense-only、無 reranker、metadata 只用 jurisdiction。
- `retrieval_eval.py` gate = 0.10（mock 雜訊）。

### 階段 1 — 法律正確性 + 真語意（最高優先）
| 動作 | 改哪個檔案 | 預期效益 | 風險 |
|---|---|---|---|
| **前案時效過濾**：`retrieve()` 加 `priority_date` 參數，`pub_date < priority_date` 硬過濾 | `rag.py`（`retrieve`、兩個 `VectorStore.search`）、`main.py`（把 case 申請日帶入）、`test_vector_store_contract.py` | 消除「引用晚於申請日的非法前案」缺口 | MemoryVectorStore 要從等值過濾擴成範圍過濾；契約測試要同步 |
| 切換真 embedding `EMBEDDING_BACKEND=bge-m3` | env / `scripts/prefetch_bge_m3.py`（已有） | retrieval 從雜訊變真語意 | dim 從 384→1024，需 `QDRANT_ALLOW_REINDEX` 重建；torch 在某些機器會 crash（CLAUDE.md pitfall） |
| 切真 embedding 後把 CI gate 0.10 → 0.70 | `retrieval_eval.py`（`DEFAULT_MIN_RECALL_AT_5`） | gate 變真品質防線 | 達標前可能 red，要先驗證 recall 真的到 0.70 |
| 中/日節標題 chunking + tokenizer 校準長度 | `rag.py`（`_SECTION_HEADINGS`、`_sliding_window`） | TW/CN/JP 說明書不再退化成單一 BODY | — |

### 階段 2 — Hybrid + Rerank（檢索品質地基）
| 動作 | 改哪個檔案 | 預期效益 | 風險 |
|---|---|---|---|
| 啟用 BGE-M3 的 **sparse + ColBERT** 輸出，向量 store 存 dense+sparse | `rag.py`（`Embedder.embed_one` 出多表示、`VectorStore` 契約加 sparse upsert/search）、Qdrant 用 named vectors / sparse vector | 精確詞彙（元件編號/化學式/法條）命中大升 | Qdrant sparse vector API、collection schema 變更；memory backend 也要實作 sparse 以維持契約對等 |
| **RRF / 加權融合** dense+sparse 候選 | `rag.py`（`retrieve` 融合邏輯，取代現有 `prefer_patent_no` boost 的臨時做法） | hybrid 顯著優於單段（見來源基準） | 融合權重要調 |
| 加 **cross-encoder reranker** `bge-reranker-v2-m3`（top-50→top-5） | 新檔 `backend/ai_engine/reranker.py` + `retrieve` 末段呼叫 | top-5 grounded set 品質升、coverage 升 | 延遲增加（CPU 小批可接受）；候選別給太多（倒 U） |
| eval harness 分段消融（dense→hybrid→rerank） | `retrieval_eval.py` / `scripts/eval_compare.py` | 量化每段增益、防 reranker 反退 | — |

### 階段 3 — Element-level 與接地強化
| 動作 | 改哪個檔案 | 預期效益 | 風險 |
|---|---|---|---|
| **claim-element 對齊檢索**：逐特徵 query → claim chart | `oa_analyzer.py`（draft 前的檢索編排）、`element_table.py` / `claim_tree.py`（已有解析） | 對應到「逐特徵核駁/答辯」真實工作流；coverage 更精準 | LLM/檢索呼叫數增加；仍須過 §4.3 過濾 |
| **span 級回溯**：grounded ref 收斂到 chunk 內具體句子 + offset | `rag.py`（`RetrievalHit` metadata）、`oa_analyzer.py`（verify）、frontend grounded ref UI | 引用可回溯到 span，律師一眼看憑據 | — |
| 加 IPC/CPC metadata 過濾 | `patent_db/seed.py`（帶分類碼）、`rag.py`、`deadline.py` 無關 | 技術領域收斂、precision 升 | 需要前案資料帶分類碼 |
| draft citation precision 指標 | `retrieval_eval.py` / `quality_eval.py`（Q19） | 直接量 stage(a) 硬牆後有效引用比例 | — |

### 階段 4 — 進階（中長期）
| 動作 | 改哪個檔案 | 預期效益 | 風險 |
|---|---|---|---|
| 圖式 Vision 描述問答（機密案僅地端 Vision） | `pdf_parser.py`（已有 region 偵測）+ 新 Vision 呼叫；非機密走 Claude Vision | RAG 能「看懂圖」 | 機密案需地端 Vision 模型；成本 |
| Agentic retrieval（多輪分解，呼應多-agent） | 新 orchestration（用 Claude tool use 把「檢索一特徵」做成工具） | 多跳前案組合（D1+D2 §103） | 成本/延遲放大；每輪仍要守不變量 |
| GraphRAG（claim-element ↔ prior-art 圖） | 新 graph 層 + 圖檢索 | 顯而易見性多跳推理、可追溯 | 落地成本最高，建議最後做 |

---

## 9. 待查證清單

1. **PatenTEB / patembed-base 等專利專用 embedding 模型族**的 production 可用性、授權、是否涵蓋中/日/韓——確認後再評估是否替換或補強 BGE-M3（§3.1）。
2. **Qwen-3 Embedding** 在專利檢索上的實測表現與多語涵蓋（§3.1，目前僅見通用多語對比）。
3. **Jina Reranker v2 / Jina-ColBERT** 的地端部署可行性與授權（air-gapped/機密案需求，§4.2）。
4. **XLSCOUT / Questel 等商用 claim-chart 工具**的內部檢索/對齊技術細節（§1、§4.4 僅引用公開描述）。
5. **BGE-M3 sparse + ColBERT 在 Qdrant 的 named/sparse vector 落地細節**（§8 階段 2，Qdrant 版本與 API 形態待實測確認）。
6. 涉及 Anthropic/Claude 的事實已以最新模型校準（**Opus 4.8 / Sonnet 4.6 = 1M context、Haiku 4.5 = 200K**；prompt caching 快取讀 ~0.1×、寫 5-min TTL ~1.25×；皆 2026-06 基準）；若上線時程拉長，重查模型/定價。

---

## 來源（Sources）

- [BAAI/bge-m3 · Hugging Face](https://huggingface.co/BAAI/bge-m3)
- [BGE M3-Embedding 論文 quick review (Liner)](https://liner.com/review/bge-m3embedding-multilingual-multifunctionality-multigranularity-text-embeddings-through-selfknowledge-distillation)
- [Comparative Analysis of Qwen-3 and BGE-M3 for Multilingual IR (Medium)](https://medium.com/@mrAryanKumar/comparative-analysis-of-qwen-3-and-bge-m3-embedding-models-for-multilingual-information-retrieval-72c0e6895413)
- [PatentSBERTa (arXiv 2103.11933)](https://arxiv.org/abs/2103.11933)
- [Benchmarking Patent Embeddings: 22 Models (arXiv 2605.24297)](https://arxiv.org/html/2605.24297)
- [PatenTEB: Patent Text Embedding Benchmark (arXiv 2510.22264)](https://arxiv.org/pdf/2510.22264)
- [BAAI/BGE Reranker v2 M3 details (agentset.ai)](https://agentset.ai/rerankers/baaibge-reranker-v2-m3)
- [Advanced RAG Retrieval: Cross-Encoders & Reranking (Towards Data Science)](https://towardsdatascience.com/advanced-rag-retrieval-cross-encoders-reranking/)
- [Top 7 Rerankers for RAG (Analytics Vidhya, 2025)](https://www.analyticsvidhya.com/blog/2025/06/top-rerankers-for-rag/)
- [Production RAG: Chunking, Retrieval, Evaluation (Towards AI)](https://towardsai.net/p/machine-learning/production-rag-the-chunking-retrieval-and-evaluation-strategies-that-actually-work)
- [Hybrid Search and Re-Ranking in Production RAG (Towards Data Science)](https://towardsdatascience.com/hybrid-search-and-re-ranking-in-production-rag/)
- [From BM25 to Corrective RAG (arXiv 2604.01733)](https://arxiv.org/html/2604.01733v1)
- [Graph Retrieval-Augmented Generation (EmergentMind)](https://www.emergentmind.com/topics/graph-retrieval-augmented-generation-grag)
- [RAG in 2025: Enterprise Guide to Graph RAG and Agentic AI (Data Nucleus)](https://datanucleus.dev/rag-and-agentic-ai/what-is-rag-enterprise-guide-2025)
- [Beyond RAG vs. Long-Context (arXiv 2509.21865)](https://arxiv.org/abs/2509.21865)
- [Solving the 'Lost in the Middle' Problem (getmaxim.ai)](https://www.getmaxim.ai/articles/solving-the-lost-in-the-middle-problem-advanced-rag-techniques-for-long-context-llms/)
- [RAGAS Metrics 文件](https://docs.ragas.io/en/v0.1.21/concepts/metrics/)
- [RAG Evaluation Metrics: Faithfulness, Relevancy (Deepchecks)](https://deepchecks.com/rag-evaluation-metrics-answer-relevancy-faithfulness-accuracy/)
- [Automated Patent Claim Charts (XLSCOUT)](https://xlscout.ai/automating-patent-infringement-how-ai-claim-charts-transform-ip-strategy/)
- [Patent Mapping and Claim Analysis with AI (Questel)](https://www.questel.com/patent/patent-preparation-patent-prosecution-process-copilots/patent-mapping-and-claim-analysis-with-ai/)
- Claude 模型 ID／context／pricing：以 claude-api skill 內建目錄為準（2026-06 基準，Opus 4.8 / Sonnet 4.6 = 1M、Haiku 4.5 = 200K）。
