#!/usr/bin/env bash
# Probe Postgres, Redis, Qdrant. Print GREEN/RED per service.
# Exit 0 if all green; 1 otherwise. Reuses verify.sh color helpers for consistency.
set -uo pipefail

cd "$(dirname "$0")/.."

# Load .env if present so script and compose see the same values.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YEL='\033[1;33m'
NC='\033[0m'

ok()  { echo -e "${GREEN}GREEN${NC} $*"; }
bad() { echo -e "${RED}RED${NC}   $*"; }
inf() { echo -e "${YEL}>>${NC}    $*"; }

FAILED=0

# Dev defaults; override via .env / environment.
PG_USER="${POSTGRES_USER:-patentmind}"
PG_DB="${POSTGRES_DB:-patentmind}"
PG_CONTAINER="patentmind-postgres"
REDIS_CONTAINER="patentmind-redis"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

# ----- Postgres -----
inf "Probing Postgres (SELECT 1) ..."
if docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tAc "SELECT 1" 2>/dev/null | grep -q '^1$'; then
  ok "postgres ($PG_CONTAINER) SELECT 1"
elif command -v psql >/dev/null 2>&1 && PGPASSWORD="${POSTGRES_PASSWORD:-patentmind}" psql -h localhost -U "$PG_USER" -d "$PG_DB" -tAc "SELECT 1" 2>/dev/null | grep -q '^1$'; then
  ok "postgres (host psql) SELECT 1"
else
  bad "postgres SELECT 1 failed (tried docker exec + host psql)"
  FAILED=1
fi

# ----- Redis -----
inf "Probing Redis (PING) ..."
if docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q '^PONG$'; then
  ok "redis ($REDIS_CONTAINER) PONG"
elif command -v redis-cli >/dev/null 2>&1 && redis-cli -h localhost -p 6379 ping 2>/dev/null | grep -q '^PONG$'; then
  ok "redis (host redis-cli) PONG"
else
  bad "redis PING failed (tried docker exec + host redis-cli)"
  FAILED=1
fi

# ----- Qdrant -----
inf "Probing Qdrant ($QDRANT_URL/healthz) ..."
# Qdrant exposes /healthz; older versions only / responds. Try both.
if curl -fs "${QDRANT_URL%/}/healthz" >/dev/null 2>&1 || curl -fs "${QDRANT_URL%/}/" >/dev/null 2>&1; then
  ok "qdrant $QDRANT_URL responding"
else
  bad "qdrant $QDRANT_URL not reachable"
  FAILED=1
fi

echo
if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}======================================"
  echo -e "  ALL SERVICES GREEN"
  echo -e "======================================${NC}"
  exit 0
else
  echo -e "${RED}======================================"
  echo -e "  ONE OR MORE SERVICES RED"
  echo -e "======================================${NC}"
  exit 1
fi
