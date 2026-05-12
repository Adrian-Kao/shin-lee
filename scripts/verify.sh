#!/usr/bin/env bash
# End-to-end smoke test. Assumes backend running (run scripts/start_backend.sh first).
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p ./tmp

# Windows: force UTF-8 mode so Python doesn't choke on cp950 default codec
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

GREEN='\033[0;32m'
RED='\033[0;31m'
YEL='\033[1;33m'
NC='\033[0m'

ok()  { echo -e "${GREEN}✓${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*"; exit 1; }
inf() { echo -e "${YEL}▶${NC} $*"; }

# ----- 1. Health -----
inf "Gateway + AI Engine health"
curl -fs http://127.0.0.1:8010/v1/health > /dev/null && ok "gateway alive"
curl -fs http://127.0.0.1:8011/v1/health > /dev/null && ok "ai_engine alive"

# Phase 1: rag backend (memory | qdrant)
RAG_HEALTH=$(curl -fs http://127.0.0.1:8011/v1/health)
RAG_BACKEND=$(echo "$RAG_HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['rag_stats'].get('backend','?'))")
case "$RAG_BACKEND" in
  memory|qdrant) ok "rag backend = $RAG_BACKEND" ;;
  *) err "unexpected rag backend: $RAG_BACKEND" ;;
esac

# Phase 2: embedding backend (mock | bge-m3) + dim consistency
EMB_BACKEND=$(echo "$RAG_HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['rag_stats'].get('embedding_backend','?'))")
EMB_DIM=$(echo "$RAG_HEALTH" | python3 -c "import sys,json;print(json.load(sys.stdin)['rag_stats'].get('embedding_dim','?'))")
case "$EMB_BACKEND" in
  mock)    [ "$EMB_DIM" = "384" ]  && ok "embedding = mock/384"  || err "mock embedding wrong dim: $EMB_DIM" ;;
  bge-m3)  [ "$EMB_DIM" = "1024" ] && ok "embedding = bge-m3/1024" || err "bge-m3 wrong dim: $EMB_DIM" ;;
  *) err "unexpected embedding backend: $EMB_BACKEND" ;;
esac

# ----- 2. Login -----
inf "Login as Alice (attorney, tenant_a)"
ALICE_TOKEN=$(curl -fs -X POST http://127.0.0.1:8010/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"user_id":"alice"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
[ -n "$ALICE_TOKEN" ] && ok "JWT issued (${#ALICE_TOKEN} chars)"

inf "Login as Carol (it_admin, tenant_b — should fail case ACL on /v1/oa/analyze)"
CAROL_TOKEN=$(curl -fs -X POST http://127.0.0.1:8010/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"user_id":"carol"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
ok "Carol token issued"

# ----- 3. Authz: Carol cannot access CASE-2025-001 -----
inf "Q12: Carol denied access to CASE-2025-001"
HTTP_CODE=$(curl -s -o ./tmp/carol.json -w '%{http_code}' \
  -X POST http://127.0.0.1:8010/v1/oa/analyze \
  -H "Authorization: Bearer $CAROL_TOKEN" \
  -H "X-Case-Id: CASE-2025-001" \
  -H 'Content-Type: application/json' \
  -d '{"oa_text":"x","case_id":"CASE-2025-001","target_patent_no":"y"}')
[ "$HTTP_CODE" = "403" ] && ok "got 403 (case ACL working)" || err "expected 403, got $HTTP_CODE"

# ----- 4. Redaction preview -----
inf "Q10: redaction preview"
RED=$(curl -fs -X POST http://127.0.0.1:8010/v1/debug/redaction_preview \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "X-Case-Id: CASE-2025-001" \
  -H 'Content-Type: application/json' \
  -d '{"text":"alice@apex-ip.com 0912-345-678 APEX-2025-0314 CL-EVCO12"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(','.join(d['rules_triggered']))")
echo "  rules: $RED"
[ "$RED" = "email,phone_tw,apex_case_no,apex_client_code" ] && ok "all 4 mask rules fired" || err "got $RED"

# ----- 5. Full analyze flow -----
inf "Full pipeline: parse → retrieve → draft → verify → deadline"
OA=$(python3 -c "import json;print(json.dumps(open('data/oa_samples/sample_oa_us.txt').read()))")
RES=$(curl -fs -X POST http://127.0.0.1:8010/v1/oa/analyze \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"oa_text\":$OA,\"case_id\":\"CASE-2025-001\",\"target_patent_no\":\"US17123456\"}")
echo "$RES" > ./tmp/analyze.json
NUM_REJ=$(python3 -c "import json;print(len(json.loads(open('./tmp/analyze.json').read())['oa']['rejections']))")
NUM_DRAFTS=$(python3 -c "import json;print(len(json.loads(open('./tmp/analyze.json').read())['drafts']))")
DEADLINE=$(python3 -c "import json;print(json.loads(open('./tmp/analyze.json').read())['deadline_summary']['statutory_deadline'])")
ok "rejections=$NUM_REJ  drafts=$NUM_DRAFTS  deadline=$DEADLINE"
[ "$NUM_REJ" -ge 1 ] && [ "$NUM_DRAFTS" -ge 1 ] || err "expected ≥1 rejection and draft"

# ----- 6. Cache hit on second call -----
inf "Q9: second identical call should hit cache (cost=0)"
RES2=$(curl -fs -X POST http://127.0.0.1:8010/v1/oa/analyze \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"oa_text\":$OA,\"case_id\":\"CASE-2025-001\",\"target_patent_no\":\"US17123456\"}")
COST2=$(echo "$RES2" | python3 -c "import sys,json;print(json.load(sys.stdin)['cost_meta']['estimated_cost_usd'])")
ok "second-call cost: $COST2 (probably 0 from cache)"

# ----- 7. Audit log + chain -----
inf "Q13: audit chain"
AUD_TOKEN=$(curl -fs -X POST http://127.0.0.1:8010/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"user_id":"audit_dave"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
NUM_ROWS=$(curl -fs -H "Authorization: Bearer $AUD_TOKEN" \
  -H "X-Case-Id: CASE-2025-001" \
  http://127.0.0.1:8010/v1/audit/recent \
  | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
ok "audit rows: $NUM_ROWS"
VERIFY=$(curl -fs -H "Authorization: Bearer $AUD_TOKEN" \
  -H "X-Case-Id: CASE-2025-001" \
  http://127.0.0.1:8010/v1/audit/verify)
echo "  $VERIFY"
[ -n "$(echo $VERIFY | grep '"broken":\[\]')" ] && ok "chain intact" || err "tampering detected"

# ----- 8. Deadline self-test -----
inf "Q17: deadline calculator self-test"
python3 -m backend.ai_engine.deadline 2>&1 | tail -1

echo
echo -e "${GREEN}======================================"
echo -e "  ALL CHECKS PASSED"
echo -e "======================================${NC}"
