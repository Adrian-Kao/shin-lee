#!/usr/bin/env bash
# LIVE smoke test for the Dify inference path (Phase 3, LLM_MODE=dify).
#
# Starts NOTHING. Assumes:
#   - Dify CE is up on $DIFY_API_URL (default http://localhost:8088)
#     (cd D:/patentmind-infra/dify/docker && docker compose up -d)
#   - scripts/setup_dify.py has run (DIFY_API_KEY_ANALYZE present in .env)
#   - Ollama is serving qwen2.5:7b on localhost:11434
#
# Posts data/oa_samples/sample_oa_tw.txt through the AI engine with
# LLM_MODE=dify and asserts at least one rejection is parsed AND that the
# response was NOT degraded to mock (model_used must contain "dify" and
# not "DEGRADED").
#
# If the AI engine service (:8011) is running it is used over HTTP
# (X-Internal-Token from .env); otherwise the same code path is exercised
# in-process via backend.ai_engine.oa_analyzer.
#
# Usage: bash scripts/smoke_dify.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Load the env the backend would load.
if [ -f .env ]; then
  set -a; source <(grep -E '^[A-Za-z_]+=' .env); set +a
fi
export LLM_MODE=dify
export PYTHONUTF8=1

DIFY_API_URL="${DIFY_API_URL:-http://localhost:8088}"
AI_ENGINE_URL="${AI_ENGINE_URL:-http://localhost:8011}"

if [ -z "${DIFY_API_KEY_ANALYZE:-}" ]; then
  echo "FAIL: DIFY_API_KEY_ANALYZE not set in .env — run: python scripts/setup_dify.py" >&2
  exit 1
fi

# 1. Dify reachable?
code=$(curl -s -o /dev/null -w '%{http_code}' "$DIFY_API_URL/console/api/setup" || true)
if [ "$code" != "200" ]; then
  echo "FAIL: Dify not reachable at $DIFY_API_URL (got $code)" >&2
  exit 1
fi
echo "[ok] Dify reachable at $DIFY_API_URL"

# 2. Run parse_oa on the TW sample.
if curl -s -o /dev/null -m 3 "$AI_ENGINE_URL/v1/health"; then
  echo "[i] AI engine is up at $AI_ENGINE_URL — testing over HTTP"
  python - <<'PY'
import json, os, pathlib, sys
import httpx

oa = pathlib.Path("data/oa_samples/sample_oa_tw.txt").read_text(encoding="utf-8")
r = httpx.post(
    os.environ.get("AI_ENGINE_URL", "http://localhost:8011") + "/v1/parse_oa",
    json={"oa_text": oa, "tenant_id": "tenant_a", "case_id": "case-001",
          "target_patent_no": "TW113141617", "security_level": "public"},
    headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
    timeout=float(os.environ.get("DIFY_TIMEOUT_SEC", "300")) + 30,
)
r.raise_for_status()
body = r.json()
rejections = body["oa"]["rejections"]
model = body.get("model_used", "")
print(f"model_used={model}  rejections={len(rejections)}")
for rej in rejections:
    print(f"  - {rej['rejection_type']} claims={rej['affected_claims']}")
assert rejections, "no rejection parsed"
assert "dify" in model.lower(), f"expected dify model, got {model}"
assert "DEGRADED" not in model, f"Dify path degraded to mock: {model}"
print("SMOKE PASS (HTTP): Dify parsed the TW OA")
PY
else
  echo "[i] AI engine service not running — exercising the code path in-process"
  python - <<'PY'
import pathlib
from backend.ai_engine import oa_analyzer

oa = pathlib.Path("data/oa_samples/sample_oa_tw.txt").read_text(encoding="utf-8")
rejections, meta = oa_analyzer.parse_oa(oa, "TW113141617", security_level="public")
model = meta.get("model_used", "")
print(f"model_used={model}  rejections={len(rejections)}")
for rej in rejections:
    print(f"  - {rej.rejection_type.value} claims={rej.affected_claims}")
assert rejections, "no rejection parsed"
assert "dify" in model.lower(), f"expected dify model, got {model}"
assert "DEGRADED" not in model, f"Dify path degraded to mock: {model}"
print("SMOKE PASS (in-process): Dify parsed the TW OA")
PY
fi
