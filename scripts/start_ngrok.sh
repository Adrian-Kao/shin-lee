#!/usr/bin/env bash
# Expose the local demo via ngrok for remote demo audience.
#
# Two tunnels at once (free ngrok plan supports this via a config file):
#   - frontend  :5173  → https://<random>.ngrok.app
#   - gateway   :8010  → https://<random>.ngrok.app (frontend's vite proxy
#                       hits localhost:8010 directly when run in the same
#                       machine, so tunnel is only needed if the audience
#                       wants to hit the gateway API independently)
#
# Prerequisite: install ngrok + authtoken (https://ngrok.com/download).
#   choco install ngrok       # Windows w/ chocolatey
#   ngrok config add-authtoken <YOUR_TOKEN>
#
# Usage:
#   bash scripts/start_demo.sh          # in terminal 1
#   bash scripts/start_ngrok.sh         # in terminal 2 (after demo is up)
#
# Vite dev server includes the ngrok host check by default; we pass
# `--host-header rewrite` so the upstream sees a localhost Host header
# and doesn't redirect.
set -euo pipefail

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✓${NC} $*"; }
inf() { echo -e "${YEL}▶${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*"; }

if ! command -v ngrok >/dev/null 2>&1; then
  err "ngrok not found. Install from https://ngrok.com/download"
  err "Then: ngrok config add-authtoken <YOUR_TOKEN>"
  exit 1
fi

# Verify demo is up.
if ! curl -fs http://127.0.0.1:5173/ >/dev/null 2>&1; then
  err "Frontend not on :5173. Run: bash scripts/start_demo.sh first."
  exit 1
fi

inf "Starting ngrok tunnel for frontend :5173..."
inf "(Ctrl+C to stop)"
echo ""

# Single-tunnel mode: vite proxy on the local machine handles /api calls,
# so we only need to tunnel the frontend port. Audience pastes the ngrok
# URL in their browser; their browser hits ngrok → our vite → our gateway.
exec ngrok http 5173 \
  --log=stdout \
  --host-header=rewrite
