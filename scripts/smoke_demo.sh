#!/usr/bin/env bash
# Pre-demo smoke test. Assumes scripts/start_demo.sh is already running.
#
# Walks the full happy path: health → login → analyze → upload PDF.
# Prints GREEN/RED per step. Exits 0 if all green, 1 otherwise.
#
# Run before demo to catch boot-time regressions.
set -uo pipefail

cd "$(dirname "$0")/.."

# Windows: force UTF-8 so the inline `python -c` JSON parsing doesn't choke
# on the cp950 default codec (analyze/upload payloads contain zh-TW text).
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[1;33m'; NC='\033[0m'
ok()  { echo -e "${GREEN}GREEN${NC} $*"; }
bad() { echo -e "${RED}RED${NC}   $*"; FAILED=$((FAILED+1)); }
inf() { echo -e "${YEL}▶${NC}     $*"; }

FAILED=0
GW=http://127.0.0.1:8010
AI=http://127.0.0.1:8011
# `localhost` (not 127.0.0.1): on Windows vite often binds IPv6 ::1 only.
FE=http://localhost:5173

mkdir -p tmp

# ----- 1. Health -----
inf "Probing gateway health..."
if curl -fs "$GW/v1/health" > /dev/null; then ok "gateway $GW"; else bad "gateway $GW (not up — run start_demo.sh first)"; fi

inf "Probing ai_engine health..."
if curl -fs "$AI/v1/health" > /dev/null; then ok "ai_engine $AI"; else bad "ai_engine $AI"; fi

inf "Probing vite..."
if curl -fs "$FE/" > /dev/null; then ok "frontend $FE"; else bad "frontend $FE"; fi

# Bail early if backend not even up.
[ $FAILED -gt 0 ] && {
  echo ""
  bad "Pre-flight checks failed — fix above and re-run."
  exit 1
}

# ----- 2. Login -----
inf "Login as Alice..."
TOKEN=$(curl -fs -X POST "$GW/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"alice","password":"demo-alice"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['token'])" 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then ok "JWT issued (${#TOKEN} chars)"; else bad "login failed"; exit 1; fi

# ----- 3. Quota -----
inf "Check quota endpoint..."
if curl -fs "$GW/v1/quota?case_id=CASE-2025-001" -H "Authorization: Bearer $TOKEN" > /dev/null; then
  ok "quota endpoint"
else
  bad "quota endpoint"
fi

# ----- 4. Analyze -----
inf "POST /v1/oa/analyze with sample US OA..."
OA=$(python -c "import json; print(json.dumps(open('data/oa_samples/sample_oa_us.txt').read()))")
RES=$(curl -fs -X POST "$GW/v1/oa/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"oa_text\":$OA,\"case_id\":\"CASE-2025-001\",\"target_patent_no\":\"US17123456\"}" \
  > tmp/smoke_analyze.json 2>/dev/null) && {
  NREJ=$(python -c "import json; print(len(json.load(open('tmp/smoke_analyze.json'))['oa']['rejections']))")
  NDRAFT=$(python -c "import json; print(len(json.load(open('tmp/smoke_analyze.json'))['drafts']))")
  DEADLINE=$(python -c "import json; print(json.load(open('tmp/smoke_analyze.json'))['deadline_summary']['statutory_deadline'][:10])")
  ok "analyze: rejections=$NREJ drafts=$NDRAFT deadline=$DEADLINE"
} || bad "analyze failed — see tmp/smoke_analyze.json"

# ----- 5. PDF Upload (if real PDF exists) -----
PDF="docs/初審審查意見通知函.pdf"
if [ -f "$PDF" ]; then
  inf "POST /v1/oa/upload with $PDF..."
  RES=$(curl -fs -X POST "$GW/v1/oa/upload" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Case-Id: CASE-2025-001" \
    -F "file=@$PDF" \
    > tmp/smoke_upload.json 2>/dev/null) && {
    PAGES=$(python -c "import json; print(json.load(open('tmp/smoke_upload.json'))['page_count'])")
    CHARS=$(python -c "import json; print(json.load(open('tmp/smoke_upload.json'))['char_count'])")
    OCR=$(python -c "import json; print(len(json.load(open('tmp/smoke_upload.json'))['ocr_pages_used']))")
    ok "upload: pages=$PAGES chars=$CHARS ocr_pages=$OCR"
  } || bad "upload failed — see tmp/smoke_upload.json"
else
  inf "skip PDF upload (no $PDF)"
fi

# ----- 6. Audit -----
inf "Check audit log..."
DAVE=$(curl -fs -X POST "$GW/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"audit_dave","password":"demo-audit_dave"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['token'])" 2>/dev/null || echo "")
if [ -n "$DAVE" ]; then
  NROWS=$(curl -fs "$GW/v1/audit/recent" \
    -H "Authorization: Bearer $DAVE" \
    -H "X-Case-Id: CASE-2025-001" \
    | python -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  ok "audit rows: $NROWS"
else
  bad "audit_dave login failed"
fi

# ----- Summary -----
echo ""
if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}════════════════════════════════════════"
  echo -e "  ALL GREEN — demo ready"
  echo -e "════════════════════════════════════════${NC}"
  exit 0
else
  echo -e "${RED}════════════════════════════════════════"
  echo -e "  $FAILED check(s) failed"
  echo -e "════════════════════════════════════════${NC}"
  exit 1
fi
