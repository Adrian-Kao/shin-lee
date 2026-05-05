#!/usr/bin/env bash
# Boot the gateway + ai_engine + seed demo patents.
# Run this in one terminal; in another: cd frontend && npm install && npm run dev
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Windows: force UTF-8 mode so Python doesn't choke on cp950 default codec
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "▶ PatentMind backend boot"
echo "  ROOT=$ROOT"

# 1. Install Python deps if missing
if ! python -c "import fastapi, jwt, numpy, httpx" 2>/dev/null; then
  echo "  installing python deps…"
  pip install --break-system-packages -q -r backend/requirements.txt || \
    pip install --break-system-packages -q fastapi uvicorn pydantic httpx numpy PyJWT
fi

# 2. Boot ai_engine on :8011
echo "  starting ai_engine on :8011 (logs → /tmp/patentmind.ai.log)"
python -m uvicorn backend.ai_engine.main:app --host 127.0.0.1 --port 8011 \
  > /tmp/patentmind.ai.log 2>&1 &
AI_PID=$!

# 3. Boot gateway on :8010
echo "  starting gateway on :8010  (logs → /tmp/patentmind.gw.log)"
python -m uvicorn backend.gateway.main:app --host 127.0.0.1 --port 8010 \
  > /tmp/patentmind.gw.log 2>&1 &
GW_PID=$!

trap "echo '  stopping…'; kill $AI_PID $GW_PID 2>/dev/null; wait 2>/dev/null; exit 0" INT TERM

# 4. Wait for them to come up
sleep 3
for url in http://127.0.0.1:8010/v1/health http://127.0.0.1:8011/v1/health; do
  if ! curl -fs $url > /dev/null; then
    echo "✗ $url not responding. Check logs."
    kill $AI_PID $GW_PID 2>/dev/null || true
    exit 1
  fi
done

# 5. Seed
echo "  seeding patents…"
python -m backend.patent_db.seed

echo
echo "✓ ready"
echo "  gateway:    http://127.0.0.1:8010/docs"
echo "  ai_engine:  http://127.0.0.1:8011/docs"
echo "  frontend:   cd frontend && npm install && npm run dev (then http://localhost:5173)"
echo
echo "Press Ctrl+C to stop."
wait
