# 交付運行手冊 / Delivery Runbook

> 企業展示（enterprise demo）的一鍵啟動與操作手冊。
> One-click start + operating guide for the enterprise demo.
> 更深入的架構說明見 `docs/ARCHITECTURE.md`；demo 腳本見 `docs/MVP_DEMO.md`。

---

## 1. 前置需求 / Prerequisites

| 項目 / Item | 需求 / Requirement |
|---|---|
| OS | Windows 11（Git Bash for scripts）or Linux/macOS |
| Python | 3.11+，`pip install -r backend/requirements.txt`（含 test deps） |
| Node | 18+（`frontend/` vite dev server） |
| Docker Desktop | 已啟動 / running（qdrant、redis、postgres、minio via `docker-compose.yml`） |
| Port 注意 | 主機 **5432 已被外部容器（pulse-db）佔用** — 本專案 Postgres 對外綁 **15432**（`POSTGRES_HOST_PORT`，預設即 15432，勿改回 5432） |
| `.env` | 首次啟動會自動產生 `JWT_SECRET` / `INTERNAL_TOKEN` / `DEMO_LOGIN_SECRET`（需 `openssl`） |
| （選用）bge-m3 | 真實 RAG 模式需先 `python scripts/prefetch_bge_m3.py`（一次性下載；之後完全離線載入） |

佔用埠位一覽 / Port map：

| Port | Service |
|---|---|
| 5173 | Frontend（vite dev） |
| 8010 | Gateway（digiRunner mock，FastAPI） |
| 8011 | AI Engine（FastAPI） |
| 6333 / 6334 | Qdrant（REST / gRPC） |
| 6379 | Redis |
| 15432 | Postgres（本專案；選用 audit backend：`AUDIT_BACKEND=postgres`） |
| 19000 / 19001 | MinIO（S3 API / console；Q13 WORM 封存：`ARCHIVE_BACKEND=s3`） |
| 18080 | digiRunner（外部團隊部署，選用 hop） |
| 8088 | Dify CE（外部團隊部署，選用 hop） |

---

## 2. 啟動 / Start

```bash
# 一鍵全部（Git Bash）：docker infra → ai_engine → gateway → frontend
bash scripts/start_delivery.sh

# 不要自動開瀏覽器 / no auto browser:
SKIP_BROWSER=1 bash scripts/start_delivery.sh

# docker 已在跑、只要應用層 / infra already up:
SKIP_DOCKER=1 bash scripts/start_delivery.sh
```

啟動完成時會印出 **Service status 一覽表**（含 digiRunner / Dify 探測結果 —
它們 DOWN 不會阻擋啟動）。

啟動後驗證 / Post-start verification：

```bash
bash scripts/smoke_demo.sh   # 應印出 ALL GREEN — demo ready
```

---

## 3. Demo 流程 / Demo Flow

1. **登入 / Login** — 開 <http://localhost:5173/>，點 **Alice**（demo 點擊登入；
   或密碼 `demo-alice`）。Alice 屬 `tenant_a`，有 `CASE-2025-001` 的 ACL。
2. **上傳 OA / Upload OA** — 拖放 `docs/初審審查意見通知函.pdf`（TW 官方 PDF，
   走 PDF 解析 + 必要時 OCR），或貼上 `data/oa_samples/sample_oa_tw.txt` 文字。
3. **分析 / Analyze** — 按「分析 OA」。流程：遮罩（Q10）→ 快取（Q9）→
   AI Engine 解析核駁理由 → RAG 檢索（Q6/Q7）→ 草稿（Q14/Q15）→
   引證驗證（Q14 hard wall）→ 期限試算（Q17）。畫面顯示核駁項、
   grounded citations、答辯期限。
4. **簽核 / Attorney sign-off** — 在草稿編輯器逐項確認 AI / 律師段落
   （Q16 line-level provenance），勾選「我已逐項確認」後匯出
   （`POST /v1/oa/export`；未簽核會被 409 擋下 — 這就是賣點，展示它）。
5. **稽核驗證 / Audit verify** — 切到 Audit 頁（可用 `audit_dave` 登入展示
   角色隔離），看每一步的 append-only 紀錄，按 **hash-chain verify**
   （`GET /v1/audit/verify`）證明不可竄改。

### 外部 hop / External hops（已上線，2026-06-11 全部實測通過）

**digiRunner（前線 API 閘道，:18080）**

```bash
bash scripts/start_digirunner.sh     # 啟動容器 + 等 healthy + 自動重灌 12 條路由（H2 in-mem，每次開機 ~5s）
bash scripts/smoke_digirunner.sh     # 7 點煙霧測試（含經 digiRunner 的 login+analyze、標頭偽造拒絕）
```

- 呼叫格式：`http://localhost:18080/dgrc/<原路徑>`（例 `/dgrc/v1/oa/analyze`）
- 前端改走 digiRunner：
  ```bash
  cd frontend && VITE_API_TARGET=http://localhost:18080 VITE_API_PATH_PREFIX=dgrc npm run dev
  ```
- Admin console：<http://localhost:18080/dgrv4/login>（帳密見 `.env` 的 `DGR_ADMIN_*`）
- 細節與手動設定路徑：`scripts/setup_digirunner.md`

**Dify CE（AI workflow 引擎，:8088）**

```bash
cd /d/patentmind-infra/dify/docker && docker compose up -d   # 12 個容器
PYTHONUTF8=1 python scripts/setup_dify.py                    # 冪等：admin → Ollama plugin → 模型 → workflow 匯入 → API key 回寫 .env
bash scripts/smoke_dify.sh                                   # 驗證 model_used=dify/qwen2.5:7b
```

- `.env` 設 `LLM_MODE=dify` 後，parse_oa / draft_response 走 `patentmind-analyze-oa`
  workflow（本機 Ollama qwen2.5:7b，全程不出機器）。引證驗證（Q14 硬牆）仍留在本專案程式內。
- Dify 不可達時自動降級 mock 並在 audit 標 `dify/qwen2.5:7b-DEGRADED-mock`（demo 不會死）。
- Console：<http://localhost:8088>（帳密見 `.env` 的 `DIFY_ADMIN_*`）；細節：`scripts/setup_dify.md`
- E2E 證明：`data/dify_e2e_proof.json`（完整 gateway 鏈路 27.2s，真模型 zh-TW 申復書）

### 稽核存放層選項 / Audit storage options（Q13，皆為選用 — 預設零依賴）

**Audit DB → Postgres**（`AUDIT_BACKEND=postgres`）

```bash
docker compose up -d postgres          # host :15432（5432 被佔，勿改回）
# .env：
#   AUDIT_BACKEND=postgres
#   POSTGRES_URL=postgresql://patentmind:patentmind@localhost:15432/patentmind
```

- 與 SQLite 完全同語意：append-only（plpgsql trigger 阻擋 UPDATE/DELETE）、
  同 hash-chain 格式、`/v1/audit/verify` 的驗證邏輯兩個 backend 共用同一套程式。
- Postgres 不可達時 gateway **拒絕啟動**（invariant #4 — 沒有稽核就不該服務）；
  運行中寫入失敗則照舊落入 write-ahead outbox（`audit_outbox.py`）等待 replay。

**WORM 封存 → MinIO Object Lock**（`ARCHIVE_BACKEND=s3`）

```bash
docker compose up -d minio             # S3 API :19000，console :19001
python scripts/init_minio.py           # 一鍵建 bucket（Object Lock 必須在建立時啟用）
# .env：ARCHIVE_BACKEND=s3（其餘 ARCHIVE_S3_* 預設即對應 compose MinIO）
python -m backend.gateway.audit_archive seal     # 封存
python -m backend.gateway.audit_archive verify   # 從 bucket 拉回驗 Merkle chain
```

- 每個 sealed segment / manifest 上傳時帶 per-object retention
  （`ARCHIVE_S3_RETENTION_MODE`，dev 預設 GOVERNANCE；正式上線改 **COMPLIANCE**
  + `ARCHIVE_S3_RETENTION_DAYS=2555`＝7 年）。物件版本在 retention 期內
  **連 root 都刪不掉**（COMPLIANCE）；覆寫只會疊新版本，封存版本永遠可取回。
- 換真 AWS S3 / 相容服務：只改 `ARCHIVE_S3_ENDPOINT` + credentials。

---

## 4. 疑難排解 / Troubleshooting

| 症狀 / Symptom | 原因與解法 / Cause & fix |
|---|---|
| `verify.sh` / pytest 紅 | 先修這個再 demo。`PYTHONUTF8=1 python -m pytest -q` |
| Gateway 拒絕啟動：JWT placeholder | `.env` 的 `JWT_SECRET` 還是 placeholder。刪掉該行重跑 `start_delivery.sh`（會自動重新產生） |
| Vite 起在 5174 而不是 5173 | 已有另一個 dev server 佔 5173（常是 IPv6 `::1` only，`curl 127.0.0.1:5173` 看不到）。`start_demo.sh` 已會自動偵測並重用；手動檢查：`netstat -ano \| grep 5173` |
| Postgres 容器起不來：port 衝突 | 不要綁 5432（被 pulse-db 佔用）。確認 `docker-compose.yml` 用 `${POSTGRES_HOST_PORT:-15432}` 且 `.env` 沒把它改回 5432 |
| Qdrant 測試紅：`dim mismatch ... Refusing to drop` | 既有 collection 與目前 embedder 維度不合。這是資料保護（Q7 guard），不是 bug。要重建索引才設 `QDRANT_ALLOW_REINDEX=true` |
| bge-m3 載入失敗 / 測試 skip | 模型未預載：`python scripts/prefetch_bge_m3.py`。公司防火牆下載不到時，Embedder 會優先離線載入 HF cache（已內建 local_files_only fallback） |
| `ModuleNotFoundError: redis` 等 | venv 缺宣告的依賴：`pip install -r backend/requirements.txt` |
| analyze 回 429 | Q18 quota / cost circuit breaker 觸發。`GET /v1/quota?case_id=...` 看餘額；demo 重啟 gateway 即重置（in-memory） |
| 匯出回 409 | 設計行為：未勾律師簽核（Q16 gate）。Demo 時故意先按一次展示 |
| digiRunner / Dify 顯示 DOWN | 不影響本 demo（選用 hop）。找對應團隊；本系統照常直連 :8010 |
| 中文亂碼（cp950） | shell 先 `export PYTHONUTF8=1 PYTHONIOENCODING=utf-8`（腳本已內建） |
| 8010/8011 殘留進程 | 見下方停止指令；或 `netstat -ano \| grep 801` 找 PID 後 `taskkill //PID <pid> //F` |

---

## 5. 停止 / Stop

```bash
# 前景跑 start_delivery.sh 的話：Ctrl+C 會關掉 ai_engine / gateway / vite
#（vite 若是「重用既有的」則不會被關，因為不是本腳本起的）

# Docker infra（保留資料卷）
docker compose down

# Docker infra（連資料卷一起清掉 — qdrant 向量、postgres 資料會消失！）
docker compose down -v
```

日誌位置 / Logs：`tmp/{gateway,ai_engine,frontend,seed}.log`。

---

## 6. 測試 / Tests

```bash
PYTHONUTF8=1 python -m pytest -q          # 全套（qdrant/redis 在跑時會多測真實後端）
bash scripts/verify.sh                     # 20 個架構決策的 e2e 不變量
bash scripts/smoke_demo.sh                 # demo 前最後一道煙霧測試
```

- Qdrant 單元測試會以 **per-run 命名空間**（`pytest_<hex>_tenant_*`）建臨時
  collection 並於 teardown 刪除，不會碰 demo 資料。
- bge-m3 測試在模型未預載時會 **skip**（不是 fail）。

---

## 7. 維運 / Operations — 排程備份 Scheduled backups (Q20)

`backend/gateway/backup.py` 是備份本體（snapshot / restore / DR drill /
GDPR erasure）；`scripts/run_backup.py` 是排程器要呼叫的 CLI 包裝 —
一次呼叫 = snapshot 全部 stateful store（audit.db / mapping.db / patent.db /
WORM audit archive）+ retention 清理（預設保留 `BACKUP_RETENTION_KEEP=168`
份，即一週的每小時備份）。**exit code 0 = 成功、1 = 失敗** — 失敗務必告警
（cron `MAILTO` 或 healthcheck ping），因為 recovery point 沒有前進。

```bash
# 手動驗證一次 / verify once by hand
PYTHONUTF8=1 python scripts/run_backup.py --quiet          # snapshot + 清理
PYTHONUTF8=1 python scripts/run_backup.py --drill --quiet  # DR drill（restore + 驗 audit chain）
```

**Linux/macOS（crontab）** — 範例與說明見 `scripts/backup_cron.sh`：

```cron
# 每小時 snapshot；保留最近 168 份
0 * * * *  /usr/bin/env bash /opt/patentmind/scripts/backup_cron.sh >> /var/log/patentmind-backup.log 2>&1
# 每季 DR drill（證明備份「真的能還原」且還原後 audit hash-chain 完整）
15 3 1 1,4,7,10 *  /usr/bin/env bash /opt/patentmind/scripts/backup_cron.sh --drill >> /var/log/patentmind-backup.log 2>&1
```

**Windows（Task Scheduler）** — 一行建立每小時排程（系統管理員 prompt）：

```bat
schtasks /Create /TN PatentMindBackup /SC HOURLY /TR "py -3 D:\patentmind-poc\scripts\run_backup.py --quiet" /F
```

備份輸出目錄由 `BACKUP_DIR` 控制（預設 `data/backups/`）；每份備份附
`manifest.json` + per-file sha256，restore 時逐檔驗雜湊。

> ⚠ **上線前必升級 streaming replication。** 週期性 snapshot 只能把資料
> 損失上界壓到 cron 間隔，**無法達成 Q20 的 RPO < 5 min 目標**。正式環境
> 必須改用串流複寫（audit 遷 Postgres 後走 WAL shipping；仍在 SQLite 階段
> 可先用 litestream）。本節的 cron 是 POC / pilot 過渡方案。
