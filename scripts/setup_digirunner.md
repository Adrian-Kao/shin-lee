# digiRunner Open Source — PatentMind front-line gateway setup

> Status: **LIVE and verified** (real digiRunner OSS, not a stand-in).
> `bash scripts/smoke_digirunner.sh` → ALL DIGIRUNNER CHECKS PASSED.

PatentMind now runs behind [digiRunner Open Source](https://github.com/TPIsoftwareOSPO/digiRunner-Open-Source)
(TPIsoftware dgrv4) as the front-line API gateway:

```
Browser (SPA :5173)
  └─ vite proxy  /api/*  ──►  digiRunner :18080  /dgrc/v1/*     (No-Auth proxy route, header passthrough)
                                  └──►  thin gateway :8010  /v1/*   (JWT + case ACL + redaction + audit)
                                            └──►  ai_engine :8011    (mock LLM / RAG)
```

## 1. Deployment (outside this repo)

| What | Where |
|---|---|
| Compose file | `D:\patentmind-infra\digirunner\docker-compose.yml` |
| Image | `tpisoftwareopensource/digirunner-open-source:latest` |
| Container | `patentmind-digirunner`, host `127.0.0.1:18080 → 18080` |
| Persistence | named volume `dgr-keys` (token keystore). **The OSS image runs H2 in-memory** (`jdbc:h2:mem:dgrdb`), so route registrations do NOT survive restarts — `start_digirunner.sh` re-applies the idempotent route map after every boot (~5 s). Do not switch to a file DB: `schema.sql` is non-idempotent (`spring.sql.init.mode=always`) and the second boot would fail. |
| Admin console | `http://localhost:18080/dgrv4/login` — credentials in repo `.env` (`DGR_ADMIN_USER` / `DGR_ADMIN_PASS`; OSS default `manager`/`manager123`, change for prod) |
| Reference source | `D:\patentmind-infra\digirunner\src` (shallow clone, used to derive the AC API contract) + `dgr-docs-llms-full.txt` (offline docs dump) |

Commands:

```bash
bash scripts/start_digirunner.sh        # up + wait + (re)apply route map
bash scripts/start_digirunner.sh stop   # down
bash scripts/start_digirunner.sh logs   # follow logs
bash scripts/smoke_digirunner.sh        # 7-point smoke (see below)
```

First boot of the Java/Spring container takes ~20 s on this machine (allow up to
3 min cold); JVM is configured `-Xms2g -Xmx4g` by the image.

## 2. Route configuration — fully automated via the AC REST API

digiRunner OSS is normally configured in the Admin Console UI, but the UI is a
thin Angular client over a transaction-style REST API. `scripts/setup_digirunner.sh`
drives that API directly (idempotent — safe to re-run):

| Step | Endpoint | Notes |
|---|---|---|
| AC login | `POST /dgrv4/tptoken/oauth/token` | multipart form: `grant_type=password`, `username=manager`, `password=base64(manager123)` → Bearer token |
| Register route | `POST /dgrv4/11/AA0311` | envelope `{"ReqHeader":{txSN,txDate,txID:"AA0311",cID:"YWRtaW5Db25zb2xl",locale},"ReqBody":{...}}`; dgrc mode (`apiSrc:"R"`, `type:1`), `moduleName`+`apiId` = proxy path, `srcUrl` = target, `noOAuth:true`; `dataFormat`/`jweFlag*` are bcrypt-param encoded (pre-computed in the script); `rtnCode 1100`=created, `1353`=exists |
| Enable route | `POST /dgrv4/11/AA0303` | `{"ignoreAlert":"Y","apiStatus":"1","apiList":[{"moduleName":"/v1","apiKey":"<path>"}]}` |
| Verify | `POST /dgrv4/11/AA0301` | API-list query (used by the smoke test) |

Registered route map (all targets `http://host.docker.internal:8010<path>`,
invoked at `http://localhost:18080/dgrc<path>`):

| Proxy path | Methods |
|---|---|
| `/v1/health` | GET |
| `/v1/auth/login`, `/v1/auth/logout`, `/v1/auth/magic/request`, `/v1/auth/magic/consume` | POST |
| `/v1/quota` | GET |
| `/v1/oa/analyze`, `/v1/oa/upload`, `/v1/oa/export` | POST |
| `/v1/debug/redaction_preview` | POST |
| `/v1/audit/recent`, `/v1/audit/verify` | GET |

### Equivalent Admin Console click-path (manual fallback / live demo)

1. `http://localhost:18080/dgrv4/login` → `manager` / (see `.env`).
2. **API Management → API Registration → CUSTOMIZE**.
3. Fill **Target URL** = `http://host.docker.internal:8010/v1/oa/analyze`,
   **API Name** = `patentmind-oa-analyze`, **digiRunner Proxy Path** = `/v1/oa/analyze`,
   **Http Methods** = POST, check **No Auth** → **Register**.
4. **API Management → API List** → select the API → **Enable** → Confirm.
5. Test in the built-in test area (flask icon) with Authorization = No Auth.

## 3. Auth mode — what is LIVE

**Live demo mode: passthrough JWT.** digiRunner routes are registered **No Auth**
(public proxy at the digiRunner hop); the SPA's own login token
(`Authorization: Bearer <PatentMind JWT>`) passes through digiRunner untouched and
the thin gateway remains the auth wall (JWT + case ACL + role gates). Verified
end-to-end: login → analyze through `:18080` returns 200 with rejections parsed.

**Also wired and verified: upstream-header identity (Day 8C contract).**
`.env` now sets `TRUSTED_UPSTREAM_IPS=127.0.0.1,::1` and a random
`UPSTREAM_AUTH_SHARED_SECRET`. Docker Desktop delivers container→host traffic
from `127.0.0.1`, so a request through digiRunner carrying

```
x-user-id: alice
x-tenant-id: tenant_a
x-upstream-auth-token: <UPSTREAM_AUTH_SHARED_SECRET from .env>
```

authenticates as alice with **no Bearer token** (smoke check e1), while the same
headers **without** the shared secret are rejected 401 (smoke check e2). Role
whitelist applies: upstream may only assert ATTORNEY/PARALEGAL; AUDITOR/IT_ADMIN
must come from local login (`backend/gateway/auth.py`).

**Enterprise story (next step, not enabled):** switch the routes off No Auth and
issue digiRunner API keys / OAuth client-credentials per law firm
(Client Management → API Group + Client), then have digiRunner inject the
identity headers. OSS supports client/credential management; header-injection
templating is the part to confirm with TPIsoftware for the enterprise tier.

## 4. Frontend switch

`frontend/vite.config.js` is env-driven:

```bash
# default — direct to thin gateway (fallback path)
npm run dev                                   # /api/* -> http://localhost:8010/*

# through digiRunner
VITE_API_TARGET=http://localhost:18080 VITE_API_PATH_PREFIX=dgrc npm run dev
                                              # /api/* -> http://localhost:18080/dgrc/*
```

NOTE: pass the prefix as `dgrc` **without** a leading slash — Git Bash (MSYS)
rewrites leading-slash arguments into `C:/Program Files/Git/...`; the config
normalises the slash back in.

## 5. Smoke test

`bash scripts/smoke_digirunner.sh` asserts:

- (a) digiRunner admin console answering on `:18080`
- (b) `/v1/oa/analyze` registered (AC API `AA0301` query)
- (c) login + OA analyze round-trip **through digiRunner** → HTTP 200,
  ≥1 rejection parsed from `data/oa_samples/sample_oa_tw.txt`
- (d) direct gateway fallback (`:8010/v1/health`) still 200
- (e) upstream-header identity honoured with the shared secret; spoof without
  the secret → 401

## 6. Gotchas / notes

- **Windows curl + TLS**: corporate networks may need `curl --ssl-no-revoke`
  for github/docs fetches (schannel revocation check). Container traffic is plain HTTP locally.
- **Ports**: 18080 was chosen because 8010/8011/5173/6333/6379/5432/5433/8088/11434
  are occupied (8088 reserved for Dify). digiRunner's container port is 18080 natively.
- **`/dgrc` prefix**: registered (dgrc-mode) APIs are served under `/dgrc/<proxy-path>`
  (observed: also reachable without the prefix; use `/dgrc` — that is the documented form).
- **Audit invariant intact**: every request through digiRunner still produces
  exactly one thin-gateway audit row; digiRunner adds its own gateway-level
  transaction log (Online Console) on top.
- **H2 is embedded** in the OSS image — fine for the pilot; the enterprise
  deployment swaps to an external RDB per TPIsoftware sizing guidance.
