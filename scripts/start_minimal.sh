#!/usr/bin/env bash
# Start the minimal MVP backend on :8010.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "▶ PatentMind minimal MVP backend"

# MVP: 預設啟用地端 Ollama
export LLM_MODE="${LLM_MODE:-local}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434/v1}"

echo "  LLM_MODE=$LLM_MODE"
if [ "$LLM_MODE" = "local" ]; then
  echo "  checking Ollama at $OLLAMA_BASE_URL ..."
  if ! curl -sf "${OLLAMA_BASE_URL%/v1}/api/tags" >/dev/null 2>&1; then
    echo ""
    echo "  ⚠ Ollama 不在 ${OLLAMA_BASE_URL%/v1}"
    echo "    請先安裝 Ollama (https://ollama.com/download)，然後："
    echo "      ollama pull llama3.1:8b"
    echo "    Ollama 安裝後會自動 serve 在 :11434。"
    echo ""
    echo "    若要先用 mock 跑：LLM_MODE=mock bash scripts/start_minimal.sh"
    exit 1
  fi
  echo "  ✓ Ollama is up"
fi

echo "  ROOT=$ROOT"
if ! python -c "import fastapi, uvicorn, jwt, numpy" 2>/dev/null; then
  echo "  installing python deps…"
  pip install --break-system-packages -q -r backend/requirements.txt
fi

echo "  starting minimal backend on :8010"
python -m uvicorn backend.minimal.main:app --host 127.0.0.1 --port 8010
