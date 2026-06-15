# 方向一：檢索與接地品質 — 實作計畫 + 起手式進度

> 承知識地圖(分冊 00)三大優化方向中**槓桿最大的「檢索與接地品質」**,展開成可執行的分階段計畫,
> 並記錄本輪已完成的「起手式」(零 GPU 依賴、有測試保護的兩項)。

## 貫穿洞見

目前**沒有可信的品質數字可優化**:`retrieval_eval.py` 是現成量測機制(recall@k / MRR / nDCG / coverage),
但 `EMBEDDING_BACKEND=mock` 下分數是 SHA-256 噪聲,CI gate 只能擺 `0.10` 地板,離 Q6 真正在乎的
`0.70` 很遠。**第一要務是把量測變真**(eval set + 真 embedder),否則後面每一步都是盲改。

## North-star 驗收
- **recall@5 ≥ 0.70**(Q6 目標),用 bge-m3 + hybrid + rerank 達成。
- **前案可受性**:grounded set 內 0 筆晚於申請日的前案(日期硬過濾在 live 生效)。
- **草稿引用精確度**:草稿只引 grounded,且 grounded 命中審查官實際引證前案達標。

## 分階段計畫

| Phase | 目標 | 改哪些檔 | 驗收 | GPU |
|---|---|---|---|---|
| 0 量測變真 | 有可信 baseline | `data/eval/retrieval_eval_set.json`(擴標註)、`config`(切 bge-m3/qdrant) | harness 在 bge-m3 跑出真 baseline | 需 |
| 1 真 embedding + 棘輪 gate | 換掉假地基 | `retrieval_eval.py`(雙軌 gate)、CI 加 bge-m3 lane | bge-m3 recall@5 量到並 gating | 需 |
| 2 Hybrid + 日期過濾 | 補精確詞彙 + 法律正確性 | `rag.py`(Qdrant named dense+sparse、RRF 融合)、**filing_date 接線** | hybrid recall 高於 dense baseline;前案日期過濾 live 生效 | 部分 |
| 3 Reranker | top-k 精確度 | 新增 `rerank.py`(`bge-reranker-v2-m3`)、`rag.retrieve()` 重排 | nDCG@5/引用精確度上升 | 需 |
| 4 接地閉環 | 檢索→引對 | `retrieval_eval.py`/`quality_eval.py` span 級引用精確度 | 引用精確度被追蹤+gating | — |

**依賴與風險**:bge-m3/reranker 需 torch/GPU runner(此研究機無);**eval set 標註是關鍵路徑**,易被低估;
**別打破輕量 CI lane**(mock 維持 0.10,雙軌 gating)。

---

## 起手式進度(本輪已完成 — 零 GPU、有測試)

### A. 前案日期硬過濾 — live 接線完成 ✅
之前已備好 `rag.retrieve(max_pub_date=)` 能力(分冊 05 實驗2);本輪把它接進 live 流程:
- `backend/shared/models.py` `AnalysisRequest` 加 `filing_date: str | None`(ISO,選配,`extra=forbid` 相容)。
- `backend/ai_engine/main.py` `RetrieveRequest` 加 `filing_date`;`/v1/retrieve_prior_art` 端點傳 `max_pub_date=req.filing_date`。
- `backend/gateway/orchestrator.py` 檢索 payload 帶 `filing_date`(來自 `AnalysisRequest`)。
- `backend/ai_engine/rag.py` `retrieve()`:日期過濾**豁免 `prefer_patent_no`(本案自身)**——應用本身不是自己的前案,不可被 cut-off 移除(否則 drafter 失去本案 claim 上下文)。
- **測試**:`tests/integration/test_retrieve_prior_art_filing_date.py`(2,HTTP 契約:晚於申請日的前案被排除、本案豁免、無 filing_date 行為不變)+ `tests/unit/test_rag_chunking_robustness.py` 新增豁免單元測試。
- **效果**:提供申請日的案件,前案檢索自動硬性排除晚於申請日的引證(專利法 §22/§23),本案 claim 仍可作 grounding。預設 None = 完全向後相容。
- **剩**:申請日的真實來源仍需 case-management 提供(目前由請求帶入)。

### B. retrieval eval set 擴充 ✅
- `data/eval/retrieval_eval_set.json` 由 7 → **10 案**,補上 `tenant_b` 的 **CN101234567 / KR1020210012345** 覆蓋(原本只有 EP):
  - `ev8` CN 負載管理(簡中 query)、`ev9` KR 負載管理(韓文 query)、`ev10` **跨語言 recall**(英文概念 query 應同時撈出 CN+KR——只有多語 embedder bge-m3 撈得到,mock/lexical 撈不到)。
- 全用**實際 seed 的專利**(`backend/patent_db/seed.py`),非杜撰。harness 把全部 demo 專利索引進 `__eval__` 單一 tenant(case 的 `tenant_id` 僅供追溯),故新案例可解析。
- mock-floor gate 仍 PASS(0.350 ≥ 0.10),CI 維持綠;`ev10` 在 bge-m3 才有意義。

### C. 雙軌 CI gate(Phase 1 enabler)— 完成 ✅
讓 gate 隨 embedding backend **自動換檔**,免得切 bge-m3 後還要記得改門檻:
- `backend/ai_engine/retrieval_eval.py` 新增 `gate_threshold_for_backend()`:`mock`/`lexical` → 地板
  `DEFAULT_MIN_RECALL_AT_5`(0.10);`bge-m3` → prod target `PROD_TARGET_RECALL_AT_5`(0.70)。
  新增 `assert_quality_auto()` 作為 CI 入口(回報 `gate_backend`),`_print_report` 也顯示 active auto gate。
- **效果**:**一旦 `EMBEDDING_BACKEND=bge-m3`,CI 自動把 recall@5 門檻拉到 0.70**——零額外設定、不會忘記。
  mock/lexical 仍走 0.10 地板保持綠。純 additive,既有 `assert_quality()` 與測試不動。
- **測試**:`tests/unit/test_retrieval_eval.py` 新增 4 個(各 backend 選對門檻、bge-m3 棘輪到 0.70、
  `assert_quality_auto` 在當前 backend 選對 gate 且綠)。

### D. Hybrid 檢索(Phase 2 主菜)— 完成 ✅(memory store)
dense(embedding cosine)+ **BM25 lexical** 經 **RRF(Reciprocal Rank Fusion)** 融合,補上 dense
對「元件編號/化學式/專名」等精確詞彙的弱點:
- `backend/shared/config.py`:`RETRIEVAL_MODE=dense|hybrid`(預設 dense)。
- `backend/ai_engine/rag.py`:`MemoryVectorStore.lexical_search()`(標準 BM25 k1=1.5/b=0.75,沿用
  `_lexical_tokens` 的拉丁詞 + CJK bigram tokenizer,corpus 統計即時算);`_rrf_fuse()`(以 rank 融合,
  避免 cosine vs BM25 尺度不可比);`retrieve(hybrid=)` 加融合步(opt-in;qdrant 無 `lexical_search`
  時自動退回 dense)。融合在日期過濾**之前**,故 §22/§23 前案日期硬牆仍生效。
- **量到的數據**(同一 10 案 eval set,**mock backend** 下——dense 是 SHA-256 噪聲):

  | 模式 | recall@5 | MRR |
  |---|---|---|
  | dense | 0.350 | 0.333 |
  | **hybrid** | **0.750** | **0.683** |

  即使沒有語意 embedder,光是把 BM25 精確詞訊號用 RRF 疊上去,recall@5 就翻倍並越過 Q6 的 0.70 線。

**原理(為何有效)**：
- **dense 的弱點**：向量檢索強在語意相近(同義改寫),弱在精確詞彙——元件編號、化學式、版本號、
  罕見專名會被壓進向量裡「平滑掉」。本專案預設 `mock` embedding 更是 SHA-256 噪聲,排序近乎隨機。
- **BM25 補精確詞**:`score = Σ_{t∈q} IDF(t)·f·(k1+1) / (f + k1·(1−b+b·|d|/avgdl))`;`IDF` 讓
  **罕見詞權重大**,`k1=1.5` 做 TF 飽和,`b=0.75 + |d|/avgdl` 做長度正規化。罕見精確詞 df 小 → IDF 大
  → 含它的 chunk 分數爆高。斷詞沿用 `_lexical_tokens`(拉丁詞 + CJK bigram),中英混排皆可。
- **RRF 解決尺度不可比**:dense 給 cosine(0–1)、BM25 給 0–20+,直接相加會被 BM25 蓋掉。RRF
  **只看名次不看分數**:`RRF(d)=Σ_lists 1/(k+rank)`,`k=60`。同時被 dense 與 BM25 都撈到的 chunk
  兩份相加 → 融合分最高 → 「雙訊號都認同的前案」浮到最上面。
- **與 bge-m3 的關係**:hybrid 不是 dense 的替代,是互補——語意找改寫、BM25 找術語。上了 bge-m3 後
  兩者一起,預期再往上;mock 下的 0.75 是「BM25 詞彙命中率」非真品質,但 dense→hybrid 的**相對增益是真的**。
- **誠實邊界**:corpus 統計即時算(O(N)/query),只適合 POC 小語料;production qdrant 要走真 sparse/
  倒排索引(Phase 2 另一半);top-k 內精排待 reranker(Phase 3)。

- **測試**:`tests/unit/test_rag_chunking_robustness.py` 新增 5 個(RRF 跨清單加權、BM25 精確詞命中、
  hybrid 撈出 dense-mock 漏掉的詞、hybrid=False 等同 dense、hybrid 仍遵守日期過濾)。
- **剩**:qdrant 的 named dense + sparse 向量索引(production hybrid),讓地端 qdrant 也走 hybrid。

### 下一步(承上)
1. **Phase 0 另一半**:把 eval set 擴到 ~30 案(需更多真實 OA↔前案標註)。
2. **Phase 1**:取得 GPU runner,切 bge-m3,量 baseline——**gate 會自動棘輪到 0.70(已就緒)**;CI 加 bge-m3 lane 呼叫 `assert_quality_auto()`。
3. **Phase 2 另一半**:Qdrant named dense+sparse 向量 + RRF(讓 qdrant 後端也支援 hybrid)。
4. **Phase 3**:reranker(`bge-reranker-v2-m3`),hybrid top-50 → 重排 top-5(需 GPU)。
