#!/usr/bin/env bash
# Bring up Postgres + Redis + Qdrant via docker compose, wait for each to be
# healthy, then print connection URLs. Safe for Git Bash on Windows.
set -euo pipefail

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

ok()  { echo -e "${GREEN}OK${NC} $*"; }
err() { echo -e "${RED}ERR${NC} $*"; }
inf() { echo -e "${YEL}>>${NC} $*"; }

# Pick the compose CLI (v2 plugin preferred; fall back to legacy docker-compose).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  err "Neither 'docker compose' nor 'docker-compose' is available. Install Docker Desktop."
  exit 1
fi

inf "Starting services via: $COMPOSE up -d"
$COMPOSE up -d

# Services we wait for + their container names from docker-compose.yml.
SERVICES="patentmind-postgres patentmind-redis patentmind-qdrant patentmind-minio"
TIMEOUT=60

wait_healthy() {
  local name="$1"
  local elapsed=0
  while [ $elapsed -lt $TIMEOUT ]; do
    # `docker inspect` returns "healthy" | "starting" | "unhealthy" | "none".
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || echo "missing")
    case "$status" in
      healthy)
        ok "$name healthy (${elapsed}s)"
        return 0
        ;;
      none)
        # No healthcheck declared; assume up.
        ok "$name running (no healthcheck)"
        return 0
        ;;
      missing)
        err "$name container not found"
        return 1
        ;;
    esac
    sleep 2
    elapsed=$((elapsed + 2))
  done
  err "$name did not become healthy within ${TIMEOUT}s (last status: $status)"
  return 1
}

FAILED=0
for svc in $SERVICES; do
  inf "Waiting for $svc ..."
  if ! wait_healthy "$svc"; then
    FAILED=1
  fi
done

echo
if [ $FAILED -ne 0 ]; then
  err "One or more services failed. Inspect with: $COMPOSE logs"
  exit 1
fi

# Pull the dev defaults from .env if present, else fall back.
POSTGRES_USER_VAL="${POSTGRES_USER:-patentmind}"
POSTGRES_DB_VAL="${POSTGRES_DB:-patentmind}"

ok "All services are up. Connection URLs:"
echo "  Postgres : postgresql://${POSTGRES_USER_VAL}:<password>@localhost:${POSTGRES_HOST_PORT:-15432}/${POSTGRES_DB_VAL}"
echo "  Redis    : redis://localhost:6379/0"
echo "  Qdrant   : http://localhost:6333 (REST), grpc://localhost:6334"
echo "  MinIO    : http://localhost:19000 (S3 API), http://localhost:19001 (console)"
echo "             WORM bucket init (once): python scripts/init_minio.py"
echo
echo "Next: bash scripts/check_docker.sh"
