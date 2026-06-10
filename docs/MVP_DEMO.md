# PatentMind MVP Demo 操作手冊

## 為什麼這份 MVP 存在

把雙 process 的 POC 砍成單 process minimal backend，接上地端 Ollama (llama3.1:8b)，讓核心 redact → parse → retrieve → draft → verify → deadline 流程能用真實 LLM 跑出可示範的結果。

## 需要什麼環境

- Python 3.11+（backend）
- Node 18+（frontend Vite）
- [Ollama](https://ollama.com/download)（Windows native，serve 在 `:11434`）
- 已 pull 的模型：`ollama pull llama3.1:8b`（約 4.7 GB）

## 啟動順序

1. **啟 Ollama**：安裝後預設自動 serve，驗證 `curl http://localhost:11434/api/tags` 看到 `llama3.1:8b`。
2. **啟 backend**：在 repo 根目錄跑 `bash scripts/start_minimal.sh`，會自動 export `LLM_MODE=local` 並先檢查 Ollama；listen on `:8010`。
3. **啟 frontend**：另開 terminal，`cd frontend && npm install && npm run dev`，開啟 `http://localhost:5173`。
4. **登入**：用 demo 帳號 `alice`（無密碼，POC 簡化）。
5. **送分析**：在 Analyze 頁貼 OA 文字、填案號與目標專利後送出。

## Demo 腳本

| 動作 | 預期結果 |
|------|----------|
| 1. 用 `alice` 登入 | 右上角顯示 `Apex Patent Law Firm / alice`，Token bar 出現 |
| 2. Analyze 頁貼 `data/oa_samples/sample_oa_us.txt`，案號 `CASE-2025-001`、目標專利 `US10000001`，按「分析」 | 等 30–90 秒（CPU 推論），看到 `drafts[0].draft_text` 為 llama 真實英文段落（非 mock 樣板字串） |
| 3. Hover draft 中的 `[GROUNDED_REF_N]` pill | 顯示對應 patent 的 patent_no / section / snippet，這是 Q14 grounded citation |
| 4. 看右側 Deadline 卡片 | 顯示 TW 期日（received_date + 60d，遇假日 roll forward） |

## 已知限制

- **CPU 推論慢**：單一 analyze 約 30–120 秒（取決於 OA 長度與 rejection 數）；GPU 環境下可降到 5–15 秒。
- **小模型對 grounded citation 過嚴**：llama3.1:8b 偶爾不主動使用 `[GROUNDED_REF_N]` placeholder，導致 verifier 把所有 citation 砍掉；可重跑或調整 prompt。
- **JSON 穩定度**：已加 `OUTPUT FORMAT` 強制指令與 `_safe_json` 容錯，但若 llama 仍偶發亂吐，會 fallback 到空結構（不會 crash）。
- **單 process 無中介層**：audit chain / cache / rate limit / case ACL 都是 stub（`/v1/quota`、`/v1/audit/*` 回固定值），不要拿來壓測。
- **Mapping table 與 RAG 都是 in-memory**：重啟 backend 後 redaction mapping 和 patent index 會重 seed，已分析的 draft unmask 會失效。

## Fallback

Ollama 沒就緒時用：`LLM_MODE=mock bash scripts/start_minimal.sh`，會走原本的 deterministic mock，UI 流程仍完整。
