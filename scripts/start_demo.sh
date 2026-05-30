#!/usr/bin/env bash
# One-click demo launcher for PatentMind internal demo.
#
# Boots:
#   - ai_engine  :8011  (FastAPI, mock LLM unless ANTHROPIC_API_KEY is set)
#   - gateway    :8010  (FastAPI, audit/cache/redaction/rate-limit)
#   - frontend   :5173  (Vite dev server)
#
# Backend uses in-process backends (SQLite audit, in-memory cache+vectors).
# Docker stack (Postgres/Redis/Qdrant) is OPTIONAL — bash scripts/start_docker.sh
# first if you want the production-grade infra.
#
# Ctrl+C cleanly shuts down all three processes.
#
# Env overrides:
#   LLM_MODE              mock (default if no key) | anthropic | local
#   ANTHROPIC_API_KEY     auto-flips LLM_MODE to anthropic when present
#   SKIP_BROWSER=1        don't auto-open the browser
#   SEED                  1 (default) — seed demo patents; 0 to skip
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Windows: force UTF-8 so Python doesn't choke on cp950 default codec.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Load .env if present so the same vars reach backend + scripts.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# ----- Colors -----
GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✓${NC} $*"; }
inf() { echo -e "${YEL}▶${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*"; }

# ----- LLM mode auto-detect -----
if [ -z "${LLM_MODE:-}" ]; then
  if [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${LLM_API_KEY:-}" ]; then
    export LLM_MODE=anthropic
  else
    export LLM_MODE=mock
  fi
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  PatentMind Demo Launcher"
echo "════════════════════════════════════════════════════════════"
echo "  ROOT          : $ROOT"
echo "  LLM_MODE      : $LLM_MODE"
if [ "$LLM_MODE" = "anthropic" ]; then
  echo "  Anthropic     : key present (${#ANTHROPIC_API_KEY:-0} chars)"
fi
echo "  Browser open  : ${SKIP_BROWSER:+SKIPPED }${SKIP_BROWSER:-auto}"
echo ""

# ----- 1. Python deps -----
inf "Checking Python deps..."
if ! python -c "import fastapi, jwt, numpy, httpx, fitz" 2>/dev/null; then
  inf "Installing backend deps (one-time, ~30s)..."
  pip install --break-system-packages -q -r backend/requirements.txt
fi
ok "Python deps ready"

# ----- 2. Boot AI Engine -----
mkdir -p tmp
inf "Starting ai_engine :8011 → tmp/ai_engine.log"
python -m uvicorn backend.ai_engine.main:app --host 127.0.0.1 --port 8011 \
  > tmp/ai_engine.log 2>&1 &
AI_PID=$!

# ----- 3. Boot Gateway -----
inf "Starting gateway :8010 → tmp/gateway.log"
python -m uvicorn backend.gateway.main:app --host 127.0.0.1 --port 8010 \
  > tmp/gateway.log 2>&1 &
GW_PID=$!

# ----- Cleanup trap (must come AFTER PIDs exist) -----
cleanup() {
  echo ""
  inf "Shutting down..."
  [ -n "${FE_PID:-}" ] && kill "$FE_PID" 2>/dev/null || true
  kill "$AI_PID" "$GW_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  ok "All stopped"
  exit 0
}
trap cleanup INT TERM

# ----- 4. Wait for backend health -----
DEADLINE=$((SECONDS + 90))
for url in http://127.0.0.1:8011/v1/health http://127.0.0.1:8010/v1/health; do
  inf "Waiting for $url ..."
  while ! curl -fs "$url" > /dev/null 2>&1; do
    if [ $SECONDS -ge $DEADLINE ]; then
      err "$url not responding within 90s — check tmp/ai_engine.log / tmp/gateway.log"
      cleanup
    fi
    if ! kill -0 "$AI_PID" 2>/dev/null || ! kill -0 "$GW_PID" 2>/dev/null; then
      err "backend process died — check tmp/ai_engine.log / tmp/gateway.log"
      cleanup
    fi
    sleep 1
  done
  ok "$url"
done

# ----- 5. Seed demo patents -----
if [ "${SEED:-1}" = "1" ]; then
  inf "Seeding demo patents..."
  python -m backend.patent_db.seed > tmp/seed.log 2>&1 || {
    err "seed failed — check tmp/seed.log"
    cleanup
  }
  ok "Patents seeded"
fi

# ----- 6. Frontend -----
if [ ! -d frontend/node_modules ]; then
  inf "Installing frontend deps (one-time, ~60s)..."
  (cd frontend && npm install --silent)
fi

inf "Starting vite :5173 → tmp/frontend.log"
(cd frontend && npm run dev > ../tmp/frontend.log 2>&1) &
FE_PID=$!

# Wait for vite to bind.
DEADLINE=$((SECONDS + 30))
while ! curl -fs http://127.0.0.1:5173/ > /dev/null 2>&1; do
  if [ $SECONDS -ge $DEADLINE ]; then
    err "Vite not responding within 30s — check tmp/frontend.log"
    cleanup
  fi
  if ! kill -0 "$FE_PID" 2>/dev/null; then
    err "Vite process died — check tmp/frontend.log"
    cleanup
  fi
  sleep 1
done
ok "Vite up"

# ----- 7. Open browser -----
URL="http://localhost:5173/"
if [ -z "${SKIP_BROWSER:-}" ]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux*)    xdg-open "$URL" 2>/dev/null || true ;;
    Darwin*)   open "$URL" 2>/dev/null || true ;;
    MINGW*|MSYS*|CYGWIN*) start "$URL" 2>/dev/null || cmd //c "start $URL" 2>/dev/null || true ;;
    *)         echo "  (open $URL manually)" ;;
  esac
fi

# ----- Summary -----
echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "${GREEN}  Demo ready${NC}"
echo "════════════════════════════════════════════════════════════"
echo "  Frontend     : $URL"
echo "  Gateway      : http://127.0.0.1:8010/docs"
echo "  AI Engine    : http://127.0.0.1:8011/docs"
echo "  Logs         : tmp/{gateway,ai_engine,frontend,seed}.log"
echo ""
echo "  Demo flow    : 1. Login as Alice"
echo "                 2. Upload docs/初審審查意見通知函.pdf (drag-drop)"
echo "                 3. Click 「分析 OA」"
echo "                 4. See rejections + grounded citations + deadline"
echo ""
echo "  Pre-demo check: bash scripts/smoke_demo.sh"
echo ""
echo "  Press Ctrl+C to stop everything."
echo "════════════════════════════════════════════════════════════"
echo ""

wait
