#!/usr/bin/env bash
# start_rag_stack.sh — bring up the opt-in Qdrant RAG stack and wait until it
# is ready to serve, then print next steps. Separate from start_docker.sh so
# the RAG infra is opt-in. Safe for Git Bash on Windows.
#
# Usage:
#   bash scripts/start_rag_stack.sh
#
# After this returns OK:
#   export VECTOR_BACKEND=qdrant EMBEDDING_BACKEND=bge-m3
#   python scripts/prefetch_bge_m3.py
#   python scripts/rag_smoke.py
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.rag.yml"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[1;33m'; NC='\033[0m'
ok()  { echo -e "${GREEN}OK${NC} $*"; }
err() { echo -e "${RED}ERR${NC} $*"; }
inf() { echo -e "${YEL}>>${NC} $*"; }

# Load .env if present so script + compose agree on values (e.g. QDRANT_URL).
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# Pick the compose CLI (v2 plugin preferred; fall back to legacy docker-compose).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  err "Neither 'docker compose' nor 'docker-compose' is available. Install Docker Desktop."
  exit 1
fi

inf "Starting Qdrant via: $COMPOSE -f $COMPOSE_FILE up -d"
$COMPOSE -f "$COMPOSE_FILE" up -d

# Wait for Qdrant's HTTP readiness endpoint (/readyz). We poll the URL from the
# HOST (not the container) so this works even if the container image lacks curl
# for its internal healthcheck. Prefer curl, fall back to wget, then Python.
READY_URL="${QDRANT_URL%/}/readyz"
TIMEOUT=120
elapsed=0

probe() {
  if command -v curl >/dev/null 2>&1; then
    curl -sf "$READY_URL" >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null "$READY_URL" 2>/dev/null
  else
    python - "$READY_URL" <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
  fi
}

inf "Waiting for Qdrant readiness at $READY_URL (timeout ${TIMEOUT}s) ..."
until probe; do
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    err "Qdrant did not become ready within ${TIMEOUT}s."
    err "Inspect with: $COMPOSE -f $COMPOSE_FILE logs"
    exit 1
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

ok "Qdrant ready at $QDRANT_URL (${elapsed}s)"
echo
echo "Next:"
echo "  export VECTOR_BACKEND=qdrant EMBEDDING_BACKEND=bge-m3"
echo "  python scripts/prefetch_bge_m3.py   # one-time bge-m3 model cache"
echo "  python scripts/rag_smoke.py         # real recall@5 / MRR"
echo
echo "Tear down:  $COMPOSE -f $COMPOSE_FILE down       (keeps data)"
echo "Wipe data:  $COMPOSE -f $COMPOSE_FILE down -v"
