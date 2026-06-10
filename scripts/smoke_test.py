"""MVP smoke test — direct llm_client invocation, no backend needed.

Usage: python scripts/smoke_test.py
Requires: Ollama running on localhost:11434 with llama3.1:8b pulled.
"""
import os
os.environ["LLM_MODE"] = "local"

import sys
import time
from backend.ai_engine.llm_client import chat

print("=== Smoke test: direct Ollama call via llm_client ===")
t0 = time.monotonic()
try:
    r = chat(
        system="You output JSON only. No prose, no markdown fences.",
        user='Respond with exactly: {"hello": "world", "ok": true}',
        intent="parse_oa",
        security_level="public",
    )
except Exception as e:
    print(f"FAILED: {e}", file=sys.stderr)
    sys.exit(1)
print(f"model         : {r.model}")
print(f"latency_ms    : {r.latency_ms}")
print(f"prompt_tokens : {r.prompt_tokens}")
print(f"completion    : {r.completion_tokens}")
print(f"text          : {r.text[:300]}")
elapsed = time.monotonic() - t0
print(f"\ntotal elapsed : {elapsed:.1f}s")
if r.model.endswith("-mock"):
    print("\nWARN: got mock response — LLM_MODE may not be 'local' or Ollama not reachable")
    sys.exit(2)
print("\n[PASS]")
