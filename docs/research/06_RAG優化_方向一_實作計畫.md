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

### 下一步(承上)
1. **Phase 0 另一半**:把 eval set 擴到 ~30 案(需更多真實 OA↔前案標註)。
2. **Phase 1**:取得 GPU runner,切 bge-m3,量 baseline——**gate 會自動棘輪到 0.70(已就緒)**;CI 加 bge-m3 lane 呼叫 `assert_quality_auto()`。
3. **Phase 2 另一半**:Qdrant named dense+sparse + RRF 融合(hybrid)。
