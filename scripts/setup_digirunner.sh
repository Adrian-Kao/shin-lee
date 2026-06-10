#!/usr/bin/env bash
# Register + enable the PatentMind route map in digiRunner Open Source (dgrv4).
#
# digiRunner OSS is configured through its Admin Console (AC) REST API — the
# same transaction-style endpoints the bundled Angular console calls:
#
#   POST /dgrv4/tptoken/oauth/token   AC login (grant_type=password,
#                                     password = base64("manager123"))
#   POST /dgrv4/11/AA0311             "API Registration > CUSTOMIZE" (dgrc mode)
#   POST /dgrv4/11/AA0303             API List > Enable / Disable
#
# Request envelope: {"ReqHeader":{txSN,txDate,txID,cID,locale},"ReqBody":{...}}
# cID = base64("adminConsole") — the seeded AC OAuth client.
#
# dgrc-mode registration notes (reverse-engineered from
# https://github.com/TPIsoftwareOSPO/digiRunner-Open-Source —
# dpaa/service/AA0311Service.java + the ac0311 Angular component):
#   * moduleName + apiId BOTH carry the proxy path; the server keeps the first
#     path segment as the module ("/v1") and the full path as the api key.
#   * dataFormat / jweFlag / jweFlagResp are "bcrypt params":
#     base64(bcrypt(subitemNo)) + "," + index-in-item-list. The values below
#     are pre-computed for dataFormat=1 (JSON, index 1) and jweFlag=0
#     (no JWT, index 0); the server only bcrypt-verifies them, so any
#     valid hash of the right subitem value works forever.
#   * noOAuth=true => the route is a public passthrough at the digiRunner
#     layer; PatentMind's own JWT auth (Authorization header is forwarded
#     untouched) remains the real auth wall.
#
# After this script, every route is callable at:
#   ${DGR_URL}/dgrc/<path>     e.g. http://localhost:18080/dgrc/v1/oa/analyze
#
# Idempotent: rtnCode 1100 = created, 1353 = already exists (both OK).
#
# Env overrides:
#   DGR_URL       digiRunner base URL          (default http://localhost:18080)
#   DGR_USER      AC username                  (default manager)
#   DGR_PASS      AC password, plaintext       (default manager123)
#   PM_TARGET     PatentMind gateway as seen FROM the digiRunner container
#                 (default http://host.docker.internal:8010)
set -euo pipefail

DGR_URL="${DGR_URL:-http://localhost:18080}"
DGR_USER="${DGR_USER:-manager}"
DGR_PASS="${DGR_PASS:-manager123}"
PM_TARGET="${PM_TARGET:-http://host.docker.internal:8010}"

# Pre-computed bcrypt params (see header). Regenerate with:
#   python -c "import bcrypt,base64;print(base64.b64encode(bcrypt.hashpw(b'1',bcrypt.gensalt())).decode()+',1')"
DATA_FORMAT_JSON="JDJiJDEyJElrcDBDTEl3aDRRNGExb2JQYnNOb3VnRFl3UWdPY2txYUZkTUd2VkpST1JnVjFNNkphRkt5,1"
JWE_FLAG_OFF="JDJiJDEyJFRwWHBoRVlQd1k0MTRpRC5JLy5ONHVEeVB5Q2NvNW8vZUdiQWFxejkya2NqUXQzNFV2dVRL,0"

GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()  { echo -e "${GREEN}OK ${NC} $*"; }
inf() { echo -e "${YEL}>> ${NC} $*"; }
err() { echo -e "${RED}!! ${NC} $*"; }

json_get() { python -c "import sys,json;print(json.load(sys.stdin)$1)" 2>/dev/null; }

# ---------------------------------------------------------------------------
# 1. AC token
# ---------------------------------------------------------------------------
inf "Logging in to digiRunner AC at ${DGR_URL} ..."
PASS_B64=$(printf '%s' "$DGR_PASS" | base64)
TOKEN=$(curl -fsS -X POST "${DGR_URL}/dgrv4/tptoken/oauth/token" \
  -F "grant_type=password" -F "username=${DGR_USER}" -F "password=${PASS_B64}" \
  | json_get "['access_token']")
if [ -z "$TOKEN" ]; then
  err "Could not obtain AC token from ${DGR_URL} — is digiRunner up? (bash scripts/start_digirunner.sh)"
  exit 1
fi
ok "AC token acquired (${#TOKEN} chars)"

ac_call() { # ac_call TXID JSON_REQBODY
  local txid="$1" reqbody="$2"
  local txdate txsn
  txdate=$(date +%Y%m%dT%H%M%S%z)
  txsn="pm$(date +%s%N | cut -c1-16)"
  curl -fsS -X POST "${DGR_URL}/dgrv4/11/${txid}" \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    -d "{\"ReqHeader\":{\"txSN\":\"${txsn}\",\"txDate\":\"${txdate}\",\"txID\":\"${txid}\",\"cID\":\"YWRtaW5Db25zb2xl\",\"locale\":\"en-US\"},\"ReqBody\":${reqbody}}"
}

# ---------------------------------------------------------------------------
# 2. Route map  (path|methods|name)  — mirrors backend/gateway/main.py and
#    digirunner/routes.yaml design intent. All No-Auth passthrough at the
#    digiRunner hop; PatentMind JWT/case-ACL still enforced downstream.
# ---------------------------------------------------------------------------
ROUTES=(
  '/v1/health|"GET"|patentmind-health'
  '/v1/auth/login|"POST"|patentmind-auth-login'
  '/v1/auth/logout|"POST"|patentmind-auth-logout'
  '/v1/auth/magic/request|"POST"|patentmind-auth-magic-request'
  '/v1/auth/magic/consume|"POST"|patentmind-auth-magic-consume'
  '/v1/quota|"GET"|patentmind-quota'
  '/v1/oa/analyze|"POST"|patentmind-oa-analyze'
  '/v1/oa/upload|"POST"|patentmind-oa-upload'
  '/v1/oa/export|"POST"|patentmind-oa-export'
  '/v1/debug/redaction_preview|"POST"|patentmind-redaction-preview'
  '/v1/audit/recent|"GET"|patentmind-audit-recent'
  '/v1/audit/verify|"GET"|patentmind-audit-verify'
)

ENABLE_ITEMS=""
for route in "${ROUTES[@]}"; do
  IFS='|' read -r path methods name <<< "$route"
  body=$(cat <<EOF
{"apiSrc":"R","type":1,"protocol":"http",
 "srcUrl":"${PM_TARGET}${path}",
 "apiName":"${name}",
 "moduleName":"${path}","apiId":"${path}",
 "noOAuth":true,"urlRID":false,"redirectByIp":false,
 "funFlag":{"tokenPayload":false},
 "methods":[${methods}],
 "dataFormat":"${DATA_FORMAT_JSON}",
 "jweFlag":"${JWE_FLAG_OFF}","jweFlagResp":"${JWE_FLAG_OFF}",
 "bodyMaskPolicy":"0","headerMaskPolicy":"0",
 "failDiscoveryPolicy":"0","failHandlePolicy":"0",
 "apiDesc":"PatentMind ${path} (digiRunner -> thin gateway :8010)"}
EOF
)
  resp=$(ac_call AA0311 "$body")
  rtn=$(echo "$resp" | json_get "['ResHeader']['rtnCode']")
  case "$rtn" in
    1100) ok  "registered ${path}" ;;
    1353) ok  "exists     ${path} (already registered)" ;;
    *)    err "FAILED     ${path}: $resp"; exit 1 ;;
  esac
  ENABLE_ITEMS="${ENABLE_ITEMS:+${ENABLE_ITEMS},}{\"moduleName\":\"/v1\",\"apiKey\":\"${path}\"}"
done

# ---------------------------------------------------------------------------
# 3. Enable everything (AA0303, apiStatus 1 = Enabled)
# ---------------------------------------------------------------------------
inf "Enabling routes ..."
resp=$(ac_call AA0303 "{\"ignoreAlert\":\"Y\",\"apiStatus\":\"1\",\"apiList\":[${ENABLE_ITEMS}]}")
rtn=$(echo "$resp" | json_get "['ResHeader']['rtnCode']")
if [ "$rtn" = "1100" ]; then
  ok "all routes enabled"
else
  err "enable failed: $resp"; exit 1
fi

echo ""
ok "digiRunner route map ready."
echo "   Invoke pattern : ${DGR_URL}/dgrc/<path>"
echo "   e.g.           : curl ${DGR_URL}/dgrc/v1/health"
echo "   Admin console  : ${DGR_URL}/dgrv4/login  (manager / see .env DGR_ADMIN_*)"
echo "   Smoke test     : bash scripts/smoke_digirunner.sh"
