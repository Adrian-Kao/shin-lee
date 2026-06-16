# 深入方向 Roadmap

> 承知識地圖(00)三大方向與方向一起手式(05/06)後,「還能往哪深入做」的整理。
> 標出 **GPU 依賴**、**工夫**、**面試/demo 價值**,供挑選。

## 目前已完成(基準)
- **方向一(檢索/接地品質)**:CJK 段落切塊 ✅、前案日期硬過濾(能力+live 接線)✅、
  跨管轄引用洩漏偵測 ✅、§26 支持度 lint(模組)✅、`_jurisdiction_for_patent` 強化 ✅、
  retrieval eval set 7→10 案 ✅、雙軌 auto-gate(mock 0.10 / bge-m3 自動 0.70)✅、
  **hybrid 檢索(BM25 + dense via RRF,memory store)✅**(mock recall@5 0.350→0.750)。
- **方向二(延遲/成本)**、**方向三(可靠性)**:尚未動。

---

## ★ 首推:claim-element 級 grounded retrieval + faithfulness eval
**為什麼**:目前「整條 rejection 當 query」。專利級做法是**把請求項拆成技術特徵(element),
每個特徵各自檢索 + 對齊前案**——這正是審查官的推理單位(本案元件 102 ↔ 引證元件 200)。
**地基已備**:`element_table.py`(`extract_elements` + `correlate` 的 102↔200 Jaccard 對應)、
`claim_tree.py`(請求項樹)、hybrid 檢索。
**做什麼**:claim → feature list → 每 feature 跑 hybrid 檢索 → 「feature ↔ 前案段落」對齊矩陣 →
draft 逐特徵接地;配 **faithfulness eval**(grounded set 是否真含審查官引證前案 / draft 是否逐特徵接地)。
**評估**:無 GPU 可原型、極專利特異、強化系統命脈(引用接地)。**面試深度最高**。

---

## A. 順著 RAG 往下(完成方向一)
| 項目 | 價值 | GPU | 工夫 |
|---|---|---|---|
| bge-m3 真 embedding + 量 baseline | auto-gate 自動棘輪到 0.70,把「機制」變「真品質」 | 需 | 小 |
| Reranker(`bge-reranker-v2-m3`)| hybrid top-50 → 精排 top-5 | 需 | 中 |
| Qdrant 原生 hybrid(named dense + sparse 向量)| 現在 BM25 hybrid 只在 memory store;production 要 qdrant sparse | 部分 | 中 |
| eval set 擴到 ~30 案 | 量測地基(關鍵路徑)| 無 | 中 |
| GraphRAG(claim-element ↔ 前案特徵知識圖)| 跨前案組合檢索(進步性常是多篇組合),最進階 | 部分 | 大 |

## B. 撰稿側(目前最弱的工作流階段)
- **§26 lint 接上線**:`claim_support.py` 已做好,缺 `/v1/claim_support` 端點 + 前端徽章。
  **低成本、立刻能 demo、無 GPU**。
- **LLM 輔助撰稿 + §26 lint 當護欄**:生成 spec/claim,用確定性 lint 即時擋「請求項未為說明書支持」。
  展示「LLM 生成 + 確定性把關」架構。

## C. 系統面大工程(broad impact,偏 production)
- **方向二 延遲/成本**:vLLM continuous batching(25–28s 砍半)、streaming(感知延遲)、
  response cache 去 user_id 改 case-scoped。可量、面試可講「怎麼把 28 秒變可用」。
- **方向三 可靠性**:Postgres streaming replication(RPO 24h→秒)、rate-limit redis 化(多副本正確性)、
  audit per-tenant 分鏈 + 中央 verify-only。展示「怎麼從 demo 變敢交付律所」。

---

## 選擇建議
- **加一個面試深講點(無 GPU、本週可做)** → 首推 claim-element 級 grounding;或 §26 lint 接端點(更快出 demo)。
- **要最扎實的「真品質」數字** → 借 GPU 跑 bge-m3,auto-gate 自動驗(已就緒)。
- **展示系統廣度** → 方向二的 streaming + cache scoping(風險低、ROI 高)。
