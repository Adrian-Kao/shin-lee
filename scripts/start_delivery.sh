#!/usr/bin/env bash
# ============================================================================
# One-click DELIVERY launcher — enterprise demo edition.
#
#   bash scripts/start_delivery.sh
#
# Brings up, in order:
#   1. Docker infra  : qdrant :6333, redis :6379, postgres :15432 (host port —
#                      5432 is occupied by a foreign container on this box)
#   2. ai_engine     : 127.0.0.1:8011
#   3. gateway       : 127.0.0.1:8010
#   4. frontend      : 127.0.0.1:5173 (vite dev server)
#
# Env comes from .env (auto-generated secrets on first boot — see
# start_demo.sh). External hops deployed by other teams are PROBED but never
# block startup:
#   - digiRunner API gateway  : http://127.0.0.1:18080
#   - Dify CE workflow engine : http://127.0.0.1:8088
#
# Implementation note: this script only prepares Docker infra and the status
# table, then DELEGATES the app bring-up (deps, secrets, health waits, seed,
# vite, Ctrl+C cleanup) to scripts/start_demo.sh — single source of truth.
#
# Env overrides:
#   SKIP_DOCKER=1     don't touch docker compose (assume infra already up)
#   SKIP_BROWSER=1    don't auto-open the browser
#   LLM_MODE=...      forwarded to start_demo.sh (mock|anthropic|local|dify)
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✓${NC} $*"; }
inf() { echo -e "${YEL}▶${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*"; }

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  PatentMind DELIVERY Launcher"
echo "════════════════════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# 1. Docker infra (qdrant + redis + postgres). Reuses start_docker.sh, which
#    runs `docker compose up -d` and waits for health. Postgres binds host
#    port ${POSTGRES_HOST_PORT:-15432} — NEVER 5432 (foreign pulse-db).
# ---------------------------------------------------------------------------
if [ -z "${SKIP_DOCKER:-}" ]; then
  inf "Bringing up Docker infra (qdrant/redis/postgres)..."
  if ! bash scripts/start_docker.sh; then
    err "Docker infra failed — check 'docker compose logs'. Aborting."
    exit 1
  fi
else
  inf "SKIP_DOCKER=1 — assuming qdrant/redis already up"
fi

# ---------------------------------------------------------------------------
# 2. Probe OPTIONAL external hops (deployed by other teams, may be up or
#    down). Print status; NEVER fail because of them.
# ---------------------------------------------------------------------------
probe_http() {
  # Echo "UP (HTTP <code>)" if anything answers (any status code counts —
  # a 404 from a live server is still a live server), else "DOWN".
  local url="$1"
  local code
  code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "$url" 2>/dev/null || echo 000)
  if [ "$code" != "000" ]; then echo "UP (HTTP $code)"; else echo "DOWN"; fi
}

DIGIRUNNER_URL="http://127.0.0.1:18080"
DIFY_URL="http://127.0.0.1:8088"

inf "Probing optional external services..."
DIGIRUNNER_STATUS=$(probe_http "$DIGIRUNNER_URL/")
DIFY_STATUS=$(probe_http "$DIFY_URL/")
ok "digiRunner $DIGIRUNNER_URL : $DIGIRUNNER_STATUS"
ok "Dify       $DIFY_URL : $DIFY_STATUS"

QDRANT_STATUS=$(probe_http "http://127.0.0.1:6333/healthz")
PG_PORT="${POSTGRES_HOST_PORT:-15432}"

# ---------------------------------------------------------------------------
# 3. Final status table — injected into start_demo.sh's "Demo ready" banner
#    via the EXTRA_SUMMARY hook, so it prints AFTER everything is up.
# ---------------------------------------------------------------------------
EXTRA_SUMMARY="  ── Service status ──────────────────────────────────────
  Frontend SPA  : http://localhost:5173/                  UP
  Gateway API   : http://127.0.0.1:8010/docs              UP
  AI Engine     : http://127.0.0.1:8011/docs              UP
  Qdrant        : http://127.0.0.1:6333/dashboard         ${QDRANT_STATUS}
  Redis         : redis://127.0.0.1:6379                  UP (compose healthy)
  Postgres      : localhost:${PG_PORT} (optional audit)        UP (compose healthy)
  digiRunner    : ${DIGIRUNNER_URL}                  ${DIGIRUNNER_STATUS}
  Dify CE       : ${DIFY_URL}                   ${DIFY_STATUS}
  ─────────────────────────────────────────────────────────
  (digiRunner/Dify are optional hops deployed separately —
   DOWN does not block this demo.)"
export EXTRA_SUMMARY

# ---------------------------------------------------------------------------
# 4. Delegate app bring-up to the existing demo launcher (blocks until
#    Ctrl+C, which also tears down ai_engine/gateway/vite).
# ---------------------------------------------------------------------------
inf "Handing over to scripts/start_demo.sh ..."
exec bash scripts/start_demo.sh
