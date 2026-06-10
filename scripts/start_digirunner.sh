#!/usr/bin/env bash
# One command to bring up digiRunner Open Source (TPIsoftware dgrv4) as the
# front-line API gateway for PatentMind, then (re)apply the route map.
#
#   bash scripts/start_digirunner.sh            # up + wait + configure routes
#   bash scripts/start_digirunner.sh stop       # stop the container
#   bash scripts/start_digirunner.sh logs       # follow container logs
#
# Deployment lives OUTSIDE this repo at D:\patentmind-infra\digirunner
# (override with DGR_INFRA_DIR). Container: patentmind-digirunner,
# host port 127.0.0.1:18080 -> container 18080.
#
# Full flow once up:
#   SPA (vite :5173, VITE_API_TARGET=http://localhost:18080)
#     -> digiRunner /dgrc/v1/*  (No-Auth passthrough route, header passthrough)
#       -> thin gateway http://host.docker.internal:8010/v1/*  (JWT + ACL + audit)
#         -> ai_engine :8011
set -euo pipefail

DGR_INFRA_DIR="${DGR_INFRA_DIR:-/d/patentmind-infra/digirunner}"
DGR_URL="${DGR_URL:-http://localhost:18080}"
COMPOSE_FILE="${DGR_INFRA_DIR}/docker-compose.yml"

cd "$(dirname "$0")/.."

case "${1:-up}" in
  stop|down)
    docker compose -f "$COMPOSE_FILE" down
    echo "digiRunner stopped."
    exit 0
    ;;
  logs)
    exec docker logs -f patentmind-digirunner
    ;;
  up) ;;
  *) echo "usage: $0 [up|stop|logs]"; exit 1 ;;
esac

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "!! $COMPOSE_FILE not found — the digiRunner deployment dir is missing."
  echo "   See scripts/setup_digirunner.md for how to recreate it."
  exit 1
fi

echo ">> Starting digiRunner (tpisoftwareopensource/digirunner-open-source) ..."
docker compose -f "$COMPOSE_FILE" up -d

echo ">> Waiting for ${DGR_URL}/dgrv4/login (Java boot, first run can take 1-3 min) ..."
DEADLINE=$((SECONDS + 300))
until curl -fs -o /dev/null "${DGR_URL}/dgrv4/login"; do
  if [ $SECONDS -ge $DEADLINE ]; then
    echo "!! digiRunner not up within 5 min — docker logs patentmind-digirunner"
    exit 1
  fi
  sleep 5
done
echo "OK digiRunner console: ${DGR_URL}/dgrv4/login"

# Apply / re-assert the PatentMind route map (idempotent).
bash scripts/setup_digirunner.sh

echo ""
echo "digiRunner is fronting PatentMind:"
echo "  Gateway hop test : curl ${DGR_URL}/dgrc/v1/health"
echo "  Route the SPA    : VITE_API_TARGET=${DGR_URL} VITE_API_PATH_PREFIX=dgrc npm run dev   (in frontend/)"
echo "                     (prefix WITHOUT leading slash — Git Bash mangles /dgrc into a Windows path)"
echo "  Smoke            : bash scripts/smoke_digirunner.sh"
