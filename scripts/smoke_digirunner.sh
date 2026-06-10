#!/usr/bin/env bash
# Smoke test: PatentMind behind digiRunner Open Source (TPIsoftware dgrv4).
#
# Asserts:
#   (a) digiRunner is up (admin console answering)
#   (b) the PatentMind route map is registered in digiRunner (AC API query)
#   (c) login + OA analyze round-trip THROUGH digiRunner returns 200 and
#       parses rejections from data/oa_samples/sample_oa_tw.txt
#   (d) the direct gateway path (:8010, the fallback) still works
#   (e) upstream-header identity contract (Day 8C): x-user-id/x-tenant-id +
#       x-upstream-auth-token honoured through digiRunner; spoof without the
#       shared secret is rejected (skipped if no secret in .env)
#
# Prereqs: backend up (bash scripts/start_backend.sh) and digiRunner up +
# configured (bash scripts/start_digirunner.sh).
set -uo pipefail

cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

DGR_URL="${DGR_URL:-http://localhost:18080}"
GW_URL="${GW_URL:-http://127.0.0.1:8010}"
DGR_USER="${DGR_ADMIN_USER:-manager}"
DGR_PASS="${DGR_ADMIN_PASS:-manager123}"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
FAILURES=0
pass() { echo -e "${GREEN}PASS${NC} $*"; }
fail() { echo -e "${RED}FAIL${NC} $*"; FAILURES=$((FAILURES+1)); }

json_get() { python -c "import sys,json;print(json.load(sys.stdin)$1)" 2>/dev/null; }

echo "== PatentMind x digiRunner smoke =="
echo "   digiRunner : $DGR_URL"
echo "   gateway    : $GW_URL"
echo ""

# ---------------------------------------------------------------- (a) up?
code=$(curl -s -o /dev/null -w '%{http_code}' "${DGR_URL}/dgrv4/login")
if [ "$code" = "200" ]; then
  pass "(a) digiRunner admin console up (${DGR_URL}/dgrv4/login)"
else
  fail "(a) digiRunner not answering (HTTP $code) — bash scripts/start_digirunner.sh"
fi

# ---------------------------------------------------------- (b) routes registered?
PASS_B64=$(printf '%s' "$DGR_PASS" | base64)
AC_TOKEN=$(curl -fsS -X POST "${DGR_URL}/dgrv4/tptoken/oauth/token" \
  -F "grant_type=password" -F "username=${DGR_USER}" -F "password=${PASS_B64}" 2>/dev/null \
  | json_get "['access_token']")
if [ -z "$AC_TOKEN" ]; then
  fail "(b) could not log in to digiRunner AC API"
else
  TXDATE=$(date +%Y%m%dT%H%M%S%z)
  LIST=$(curl -fsS -X POST "${DGR_URL}/dgrv4/11/AA0301" \
    -H "Authorization: Bearer ${AC_TOKEN}" -H "Content-Type: application/json" \
    -d "{\"ReqHeader\":{\"txSN\":\"smoke1\",\"txDate\":\"${TXDATE}\",\"txID\":\"AA0301\",\"cID\":\"YWRtaW5Db25zb2xl\",\"locale\":\"en-US\"},\"ReqBody\":{\"keyword\":\"/v1/oa/analyze\",\"apiSrc\":[],\"publicFlag\":\"\",\"paging\":\"N\"}}" 2>/dev/null)
  if echo "$LIST" | grep -q "/v1/oa/analyze"; then
    pass "(b) route /v1/oa/analyze registered in digiRunner (AA0301 query)"
  else
    fail "(b) /v1/oa/analyze not found in digiRunner API list — bash scripts/setup_digirunner.sh"
  fi
fi

# ------------------------------------------- (c) login + analyze THROUGH digiRunner
PM_TOKEN=$(curl -fsS -X POST "${DGR_URL}/dgrc/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","password":"demo-alice"}' 2>/dev/null | json_get "['token']")
if [ -z "$PM_TOKEN" ]; then
  fail "(c) login through digiRunner failed"
else
  pass "(c1) login through digiRunner OK (alice)"
  RESULT=$(python - "$PM_TOKEN" "$DGR_URL" <<'EOF'
import sys, json, pathlib, urllib.request, urllib.error
token, base = sys.argv[1], sys.argv[2]
oa = pathlib.Path("data/oa_samples/sample_oa_tw.txt").read_text(encoding="utf-8")
body = json.dumps({"case_id": "CASE-2025-001", "oa_text": oa,
                   "target_patent_no": "TW-I-654321"}).encode()
req = urllib.request.Request(
    f"{base}/dgrc/v1/oa/analyze", data=body, method="POST",
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {token}",
             "X-Case-Id": "CASE-2025-001"})
try:
    r = urllib.request.urlopen(req, timeout=300)
    d = json.load(r)
    rej = d.get("oa", {}).get("rejections", [])
    print(f"{r.status}|{len(rej)}|{d.get('request_id','')}")
except urllib.error.HTTPError as e:
    print(f"{e.code}|0|")
EOF
)
  HTTP=$(echo "$RESULT" | cut -d'|' -f1)
  NREJ=$(echo "$RESULT" | cut -d'|' -f2)
  if [ "$HTTP" = "200" ] && [ "${NREJ:-0}" -ge 1 ]; then
    pass "(c2) analyze through digiRunner: HTTP 200, ${NREJ} rejection(s) parsed from sample_oa_tw.txt"
  else
    fail "(c2) analyze through digiRunner: HTTP ${HTTP}, rejections=${NREJ:-?}"
  fi
fi

# --------------------------------------------------- (d) direct gateway fallback
code=$(curl -s -o /dev/null -w '%{http_code}' "${GW_URL}/v1/health")
if [ "$code" = "200" ]; then
  pass "(d) direct gateway fallback path up (${GW_URL}/v1/health)"
else
  fail "(d) direct gateway not answering (HTTP $code) — bash scripts/start_backend.sh"
fi

# ---------------------------------- (e) upstream-header identity (Day 8C contract)
SECRET=$(grep -E '^UPSTREAM_AUTH_SHARED_SECRET=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
if [ -z "$SECRET" ]; then
  echo "SKIP (e) UPSTREAM_AUTH_SHARED_SECRET not set in .env"
else
  code=$(curl -s -o /dev/null -w '%{http_code}' "${DGR_URL}/dgrc/v1/quota" \
    -H "x-user-id: alice" -H "x-tenant-id: tenant_a" \
    -H "x-upstream-auth-token: ${SECRET}")
  if [ "$code" = "200" ]; then
    pass "(e1) upstream-header identity honoured through digiRunner (alice, no Bearer)"
  else
    fail "(e1) upstream-header identity rejected (HTTP $code)"
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' "${DGR_URL}/dgrc/v1/quota" \
    -H "x-user-id: alice" -H "x-tenant-id: tenant_a")
  if [ "$code" = "401" ]; then
    pass "(e2) header spoof WITHOUT shared secret correctly rejected (401)"
  else
    fail "(e2) expected 401 for missing shared secret, got HTTP $code"
  fi
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo -e "${GREEN}ALL DIGIRUNNER CHECKS PASSED${NC}"
  exit 0
else
  echo -e "${RED}${FAILURES} CHECK(S) FAILED${NC}"
  exit 1
fi
