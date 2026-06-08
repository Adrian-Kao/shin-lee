# 前端設計深度研究彙整（5-Agent 平行研究）

> 研究日期：2026-06。方法：5 個獨立 agent 平行研究前端不同面向，唯讀分析，每項附 `檔案:行號` 證據。
> 五個面向：(1) UX/IA/流程 (2) 視覺設計系統 (3) 無障礙/i18n (4) 程式架構/狀態/效能 (5) 法律領域信任型 UX。

---

## 0. 總體判斷（跨 agent 共識）

**「規格極成熟、實作落差極大」** —— 多個 agent 各自獨立得出同一結論。
專案有一整套高品質規劃文件（`DESIGN_SYSTEM.md` 1200+ 行、`ACCESSIBILITY_AND_I18N.md` 1284 行、
`UX_PERSONA_JOURNEYS.md`），但落地率僅約 5–30%。這些文件是「北極星」，不是「現況」。

強化前端的本質工作 = **把已寫好的規格與已存在的後端保證，真正接到 UI 上。**

---

## 1. 高信心發現（≥2 個 agent 獨立指出 = 最該先修）

| # | 發現 | 證據 | 指出的 agent |
|---|------|------|------|
| ★1 | **簽核→出稿閉環斷裂**：`DraftEditor` 的 `onAccept` 在 `DraftsPane.jsx:165` 渲染時根本沒傳入，逐句簽核的 provenance 資料（Q16 核心責任界線）丟進虛空，簽完核沒有下一步、切 tab 即遺失 | `DraftEditor.jsx:57`、`DraftsPane.jsx:165` | UX、架構、信任 |
| ★2 | **Citation pill 在 iPad 上是死的**：grounded citation 來源只靠 HTML `title=` 屬性（hover-only），觸控裝置不觸發；且與右窗格 reference 不連動 | `DraftEditor.jsx:166-168` | UX、a11y、信任 |
| ★3 | **Verifier 把關結果被丟棄**：orchestrator 把 `invalid_citations`/`verifier_confidence` 壓扁丟掉，前端只剩無上下文的 `[CITATION_REMOVED]` 紅標，沒 tooltip。最強的「防幻覺硬牆」前端看不見 | `orchestrator.py:289-291`、`oa_analyzer.py:214-220`、`DraftEditor.jsx:174` | 信任（獨家高價值） |
| ★4 | **機密路由看不見**：機密案走地端 LLM 這件事律師當下看不到，要去 Audit 表挖 model 欄；Trust Band 還是純前端字串比對 `caseId.endsWith('-CONF')` 不是讀後端真值 | `AppShell.jsx:244-258`、`orchestrator.py:445-451`、`README.md:56` | 信任 |
| ★5 | **`alert()` 當簽核守門員**：原生 alert 在 iPad 阻斷、無法 i18n、與產品質感衝突 | `DraftEditor.jsx:52` | UX、a11y |
| ★6 | **i18n 半成品**：有完整 zh-TW/en 資源但**沒有語言切換 UI、零處 `changeLanguage()`**，en 是死碼；9 元件 72 處中文硬編 | `i18n.js:286`、`DraftEditor`/`DraftsPane`/`InputPane` | a11y、UX、視覺 |
| ★7 | **暗色模式插電未接燈**：`theme.jsx` + `.dark` token 完整，但全專案 0 個 `dark:` class，元件全寫死 `bg-white`，dark mode 實際無作用 | `index.css:38-66`、grep `dark:` = 0 | 視覺、架構 |
| ★8 | **主流程 emoji 圖示**：`📄⏳✓●○` 與已升級的 lucide 系統混用，削弱「官方門戶」可信度 | `DraftsPane.jsx:42,219,238`、`InputPane.jsx` | UX、視覺 |
| ★9 | **Analyze god component + 無 memo**：14 個 useState、往 InputPane 透傳 23 個 props、三窗格全量 re-render、無伺服器狀態層 | `Analyze.jsx:60-75,158-185` | 架構 |
| ★10 | **品牌色雙頭**：全站 navy，但整個分析工作區是 indigo | `Analyze.jsx:368`、`DraftsPane.jsx:107`、`ClaimTree.jsx:163` | 視覺 |

> 文件待修：`vite.config.js` 用 `:8010`（正確，後端實跑此 port），但 CLAUDE.md §2 / `client.js:4` 註解寫 `:8000` 過時，應更新。

---

## 2. 各面向重點摘要

### A. UX / 資訊架構 / 流程
- 做得好：rejection 驅動三窗格同步、誠實的 7 階段載入時間軸、錯誤狀態分類成熟、OAUpload 狀態機完整。
- 痛點：簽核閉環斷裂(★1)、多 rejection 無全域簽核進度、無角色差異化（4 個 demo 帳號共用同一 UI、登入都丟到分析頁撞 403）、case ID 是裸輸入框打錯就 403、`/cases` 是 placeholder（IA 斷點）。

### B. 視覺設計系統
- 澄清：**Tailwind 已是 PostCSS 編譯版，不是 CDN**（CLAUDE.md §7.3 過時）。
- 痛點：`ui/button.jsx` 定義完整卻**零 import**（40 個手寫 `<button>` 散在 14 檔）、卡片樣式重複 6+ 次、4 套各寫各的 chip tone 邏輯、動態 class 內插靠 safelist 硬撐（脆弱）、字級魔術數字 `text-[10px]` 繞過字階、navy/indigo 雙頭、dark mode 死碼。
- 建議：三層 token（primitive→semantic→component）但只做畫面真用到的；不要照 1200 行規格全做。

### C. 無障礙 / i18n
- 痛點（a11y）：逐句 Accept/Edit 按鈕 hover-only **純鍵盤完全不可達**、5–7 分鐘分析過程無 live region（視障全黑箱）、citation pill 非語意元素、無全域 focus-visible、`<html lang>` 寫死、ClaimTree 未用 tree pattern、狀態僅靠顏色。
- 痛點（i18n）：無切換器(★6)、日期寫死 `'zh-TW'` 無民國曆、無集中 Intl 格式層、無 ICU 複數。

### D. 程式架構 / 狀態 / 效能
- 最大缺口：**無伺服器狀態層**，全手寫 `useState+useEffect+fetch`，無快取/重試/去重（audit verify 被 AppShell + AuditView 各打一次）。
- 痛點：god component + props drilling(★9)、provenance 上浮斷路(★1)、`client.js` 無重試/逾時/401 集中處理、session 只存 React state（**重整即登出**）、無 code splitting（Sentry 50KB 全進 entry）、無單元測試。
- 判斷：**建議引入 TanStack Query**（server state）+ Context（UI state）；Zustand 先不急。

### E. 法律領域信任型 UX（最獨特面向）
- 做得好：全域 Trust Band、hash chain 白話綠/紅燈、grounded pill 區隔、逐句紫/綠 provenance、redaction 預覽。
- 信任缺口：verifier 硬牆隱形(★3)、機密路由看不見(★4)、deadline 只給天數不給計算依據（`warnings`/版本/建議內部日後端有卻沒渲染）、redaction 無 before→after diff、provenance 只有 ai/attorney 二元（缺 paralegal→律師→合夥人多人鏈）、簽核未見寫 audit row 的回饋。
- 差異化：把這些畫出來 = 4 個「ChatGPT 永遠做不到」的展示亮點（不幻覺是可見硬牆、資料沒外流可稽核、誰負責逐句標示、可究責 user-verifiable）。

---

## 3. 整合後的優先級路線圖

### P0 — Demo 前必做（高信心、高價值）
1. **補完簽核→出稿→audit 閉環**(★1)：`DraftsPane` 傳 `onAccept` 上浮到 `Analyze`，加「匯出答辯狀」按鈕，簽核寫 audit row 並回饋。
2. **多 rejection 全域簽核進度**：簽核狀態提升到 `Analyze`，tab 加 ✓ badge，全簽才能出稿。
3. **Verifier 結果升級為一級「幻覺防禦」面板**(★3)：後端透傳 `invalid_citations`，前端畫成綠/紅狀態列，`[CITATION_REMOVED]` 加 tooltip。
4. **機密路由即時可見**(★4)：後端回傳真實 `security_level`/`routing`，加「本案地端處理、資料未出境」橫幅，Trust Band 讀真值。
5. **移除 `alert()`**(★5)：改 inline 提示 + auto-scroll 到第一個未決定句。
6. **角色感知 landing + 簽核權限**：依 role 決定首屏，paralegal 看「送交律師簽核」。
7. **citation pill 可點 + 跨窗格連動 + iPad 可用**(★2)：改 `<button>`/`role=link`，點擊開側欄高亮原文。
8. **indigo → navy 全域收斂**(★10)：純機械替換，零風險。

### P1 — 重要
9. **接語言切換器 + 完成元件 i18n 遷移**(★6)：一行 `changeLanguage` 解鎖整套英文資源 + 同步 `<html lang>`。
10. **DraftEditor 鍵盤全可達 + 分析 live region**：最高 ROI 的 a11y 修。
11. **導入 TanStack Query**(★9 相關)：解決快取/重試/去重/輪詢/loading 散落。
12. **啟用 `Button` + 抽 `Badge`/`Card`/`PaneHeader` 元件**：收斂 40 按鈕 + 4 套 chip。
13. **deadline 計算依據可解釋**：渲染 `warnings`/假日表版本/建議內部日。
14. **拆 Analyze god component + memo 邊界**：Context 承載跨窗格狀態 + `React.memo`。
15. **主流程 emoji → lucide**(★8)。
16. **多人 provenance**：ai/attorney → drafted_by/edited_by/signed_by。

### P2 — 打磨
17. 補語意 token 中介層 → 解鎖 dark mode(★7)。
18. redaction before→after diff。
19. 字級魔術數字回收進字階、圓角收斂、`max-w-[1920px]` 具名化。
20. `prefers-reduced-motion`、對比度（`slate-400`→`slate-500`）、landmark/skip-link、audit 表 `scope`/caption。
21. code splitting（路由 lazy + Sentry 條件載入）、session 持久化。
22. 加 vitest 單元測試（`classifyError`/cascade/簽核狀態機）+ `@axe-core/playwright` a11y 斷言。
23. RunningPanel 接真實後端進度（目前是前端假動畫）。
24. 消滅動態 class 字串插值（改明確 class 對照表）。

---

## 4. 如果只能做 5 件事（跨 agent 加權）

1. **簽核→出稿→audit 閉環**(★1) — 被 3 個 agent 獨立點名的最致命斷點，讓整個產品故事在高潮處戛然而止。
2. **Verifier「防幻覺硬牆」可視化**(★3) — 後端做了最難的部分卻把證據丟掉；這是對比 ChatGPT 最鋒利的差異點。
3. **citation pill 可點、iPad 可用、跨窗格連動**(★2) — persona doc 明確標為決定 churn-or-stay 的 watershed moment。
4. **機密路由即時可見**(★4) — 最強合規賣點目前完全隱形，同時服務簽核合夥人與採購 IT。
5. **接語言切換器**(★6) — 一行程式碼解鎖整套已寫好的英文資源，ROI 最高。

---

## 5. 後續可繼續對話的 agent

每個 agent 可用 SendMessage 接續深挖：
- UX/流程：`a3b064682d7e3657b`
- 視覺設計系統：`a9ef34eaf9b4c7479`
- 無障礙/i18n：`a4be25a748426eb96`
- 架構/效能：`aba2b02342ce84d6f`
- 信任型 UX：`ab1face45689a0ee0`
