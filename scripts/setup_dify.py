"""Bootstrap the self-hosted Dify CE instance for PatentMind (Phase 3).

Idempotent — safe to re-run. Automates EVERYTHING:

  1. First-run admin setup (POST /console/api/setup) — credentials are read
     from / written to the repo .env (DIFY_ADMIN_EMAIL / DIFY_ADMIN_PASSWORD).
  2. Console login (cookie + CSRF token auth, Dify >= 1.14).
  3. Ollama model-provider plugin install from the Dify marketplace.
  4. Model registration: qwen2.5:7b (LLM) + nomic-embed-text (embedding),
     both pointing at host.docker.internal:11434 (the host's Ollama).
  5. Imports the `patentmind-analyze-oa` WORKFLOW app via DSL (generated
     in-process from backend/ai_engine/prompts/*.yaml so the Dify prompts are
     always in sync with the repo's prompt YAMLs at import time).
  6. Publishes the workflow and mints a Service API key.
  7. Writes DIFY_API_KEY_ANALYZE (+ admin creds) back into the repo .env.

Usage:
    PYTHONUTF8=1 python scripts/setup_dify.py [--dify-url http://localhost:8088]

Prereqs: Dify CE running (cd D:/patentmind-infra/dify/docker && docker compose up -d)
         and Ollama running on the host with qwen2.5:7b + nomic-embed-text pulled.

See scripts/setup_dify.md for the manual fallback for each step.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PROMPTS_DIR = ROOT / "backend" / "ai_engine" / "prompts"

APP_NAME = "patentmind-analyze-oa"
OLLAMA_PLUGIN_ID = "langgenius/ollama"
# Fallback identifier (verified against marketplace 2026-06-11); the script
# tries the live marketplace API first and only uses this when offline.
OLLAMA_PLUGIN_IDENTIFIER_FALLBACK = (
    "langgenius/ollama:1.0.0@ae50a2db261bffa7289677f2b0a60e60762ceb187b602113b72425ccbe772dc3"
)
OLLAMA_PROVIDER = "langgenius/ollama/ollama"
OLLAMA_BASE_URL_FROM_DIFY = "http://host.docker.internal:11434"
LLM_MODEL = "qwen2.5:7b"
EMBED_MODEL = "nomic-embed-text"


# ---------------------------------------------------------------------------
# .env helpers (tiny, dependency-free)
# ---------------------------------------------------------------------------


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def upsert_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                seen.add(k)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Dify console client (cookie session + X-CSRF-Token, Dify >= 1.14)
# ---------------------------------------------------------------------------


class DifyConsole:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=120.0, follow_redirects=True)

    def _csrf(self) -> dict[str, str]:
        token = self.http.cookies.get("csrf_token")
        return {"X-CSRF-Token": token} if token else {}

    def get(self, path: str, **kw):
        return self.http.get(f"/console/api{path}", headers=self._csrf(), **kw)

    def post(self, path: str, json_body=None, **kw):
        return self.http.post(f"/console/api{path}", json=json_body, headers=self._csrf(), **kw)

    # -- steps ---------------------------------------------------------------

    def setup_status(self) -> str:
        r = self.get("/setup")
        r.raise_for_status()
        return r.json()["step"]

    def setup(self, email: str, name: str, password: str) -> None:
        r = self.post(
            "/setup", {"email": email, "name": name, "password": password, "language": "zh-Hant"}
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"setup failed: {r.status_code} {r.text[:300]}")

    def login(self, email: str, password: str) -> None:
        b64 = base64.b64encode(password.encode()).decode()
        r = self.post("/login", {"email": email, "password": b64})
        if r.status_code != 200 or r.json().get("result") != "success":
            raise RuntimeError(f"login failed: {r.status_code} {r.text[:300]}")

    # -- plugin --------------------------------------------------------------

    def installed_plugins(self) -> list[dict]:
        r = self.get("/workspaces/current/plugin/list")
        r.raise_for_status()
        body = r.json()
        return body.get("plugins") or body.get("data", {}).get("plugins", []) or []

    def marketplace_identifier(self) -> str:
        try:
            r = httpx.get(
                f"https://marketplace.dify.ai/api/v1/plugins/{OLLAMA_PLUGIN_ID}",
                timeout=30.0,
                verify=True,
            )
            ident = r.json()["data"]["plugin"]["latest_package_identifier"]
            if ident:
                return ident
        except Exception as e:  # offline → pinned fallback
            print(f"  marketplace lookup failed ({e}); using pinned identifier")
        return OLLAMA_PLUGIN_IDENTIFIER_FALLBACK

    def install_ollama_plugin(self) -> None:
        if any(p.get("plugin_id") == OLLAMA_PLUGIN_ID for p in self.installed_plugins()):
            print("  [ok] ollama plugin already installed")
            return
        ident = self.marketplace_identifier()
        print(f"  installing {ident} ...")
        r = self.post(
            "/workspaces/current/plugin/install/marketplace", {"plugin_unique_identifiers": [ident]}
        )
        if r.status_code != 200:
            # The api container may be unable to reach marketplace.dify.ai
            # (proxy / TLS environment). Fall back: download the signed
            # .difypkg HOST-side and push it through upload/pkg + install/pkg.
            print(
                f"  marketplace-side install failed ({r.text[:160]}) — "
                "falling back to host-side download + pkg upload"
            )
            self._install_via_local_pkg(ident)
            return
        task = r.json()
        if task.get("all_installed"):
            print("  [ok] plugin installed (immediate)")
            return
        self._wait_plugin_task(task.get("task_id"))

    def _install_via_local_pkg(self, ident: str) -> None:
        url = f"https://marketplace.dify.ai/api/v1/plugins/download?unique_identifier={ident}"
        cached = Path("D:/patentmind-infra/ollama.difypkg")
        if cached.exists() and cached.stat().st_size > 0:
            content = cached.read_bytes()
        else:
            dl = httpx.get(url, timeout=120.0, follow_redirects=True)
            dl.raise_for_status()
            content = dl.content
            cached.write_bytes(content)
        up = self.http.post(
            "/console/api/workspaces/current/plugin/upload/pkg",
            files={"pkg": ("ollama.difypkg", content, "application/octet-stream")},
            headers=self._csrf(),
        )
        if up.status_code != 200:
            raise RuntimeError(f"pkg upload failed: {up.status_code} {up.text[:300]}")
        uploaded_ident = up.json().get("unique_identifier") or ident
        r = self.post(
            "/workspaces/current/plugin/install/pkg",
            {"plugin_unique_identifiers": [uploaded_ident]},
        )
        if r.status_code != 200:
            raise RuntimeError(f"pkg install failed: {r.status_code} {r.text[:300]}")
        task = r.json()
        if task.get("all_installed"):
            print("  [ok] plugin installed from local pkg (immediate)")
            return
        self._wait_plugin_task(task.get("task_id"))

    def _wait_plugin_task(self, task_id: str) -> None:
        for _ in range(60):
            time.sleep(2)
            tr = self.get(f"/workspaces/current/plugin/tasks/{task_id}")
            t = tr.json().get("task", {})
            status = t.get("status")
            if status == "success":
                print("  [ok] plugin installed")
                return
            if status == "failed":
                raise RuntimeError(f"plugin install task failed: {json.dumps(t)[:400]}")
        raise RuntimeError("plugin install timed out after 120s")

    # -- models --------------------------------------------------------------

    def add_model(self, model: str, model_type: str, credentials: dict) -> None:
        r = self.get(f"/workspaces/current/model-providers/{OLLAMA_PROVIDER}/models")
        if r.status_code == 200:
            existing = [m.get("model") for m in r.json().get("data", [])]
            if model in existing:
                print(f"  [ok] model {model} already registered")
                return
        r = self.post(
            f"/workspaces/current/model-providers/{OLLAMA_PROVIDER}/models/credentials",
            {
                "model": model,
                "model_type": model_type,
                "credentials": credentials,
                "name": f"ollama-{model_type}",
            },
        )
        if r.status_code in (200, 201):
            print(f"  [ok] model {model} registered + validated")
        else:
            raise RuntimeError(f"add model {model} failed: {r.status_code} {r.text[:400]}")

    # -- app -----------------------------------------------------------------

    def find_app(self) -> str | None:
        r = self.get("/apps", params={"page": 1, "limit": 100, "name": APP_NAME})
        if r.status_code != 200:
            return None
        for a in r.json().get("data", []):
            if a.get("name") == APP_NAME:
                return a["id"]
        return None

    def import_dsl(self, yaml_content: str) -> str:
        r = self.post("/apps/imports", {"mode": "yaml-content", "yaml_content": yaml_content})
        body = r.json()
        if r.status_code not in (200, 202) or body.get("status") == "failed":
            raise RuntimeError(f"DSL import failed: {r.status_code} {json.dumps(body)[:500]}")
        if body.get("status") == "pending":
            r2 = self.post(f"/apps/imports/{body['id']}/confirm")
            body = r2.json()
            if body.get("status") == "failed":
                raise RuntimeError(f"DSL import confirm failed: {json.dumps(body)[:500]}")
        print(f"  [ok] DSL imported (status={body.get('status')}) app_id={body.get('app_id')}")
        return body["app_id"]

    def publish_workflow(self, app_id: str) -> None:
        r = self.post(
            f"/apps/{app_id}/workflows/publish",
            {"marked_name": "setup_dify.py", "marked_comment": "automated publish"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"publish failed: {r.status_code} {r.text[:300]}")
        print("  [ok] workflow published")

    def service_api_key(self, app_id: str) -> str:
        r = self.get(f"/apps/{app_id}/api-keys")
        if r.status_code == 200:
            for k in r.json().get("data", []):
                if k.get("token"):
                    return k["token"]
        r = self.post(f"/apps/{app_id}/api-keys")
        if r.status_code not in (200, 201):
            raise RuntimeError(f"api-key creation failed: {r.status_code} {r.text[:300]}")
        return r.json()["token"]


# ---------------------------------------------------------------------------
# DSL generation — prompts injected from backend/ai_engine/prompts/*.yaml
# ---------------------------------------------------------------------------


def load_prompt(intent: str) -> str:
    doc = yaml.safe_load((PROMPTS_DIR / f"{intent}.yaml").read_text(encoding="utf-8"))
    return doc["system"]


def _llm_node(
    node_id: str,
    title: str,
    system_text: str,
    start_id: str,
    temperature: float,
    num_predict: int,
    y: int,
) -> dict:
    return {
        "data": {
            "context": {"enabled": False, "variable_selector": []},
            "desc": "",
            "model": {
                "provider": OLLAMA_PROVIDER,
                "name": LLM_MODEL,
                "mode": "chat",
                "completion_params": {
                    "temperature": temperature,
                    # keep generations modest: qwen2.5:7b is slow on long outputs
                    "num_predict": num_predict,
                },
            },
            "prompt_template": [
                {"id": str(uuid.uuid4()), "role": "system", "text": system_text},
                {"id": str(uuid.uuid4()), "role": "user", "text": f"{{{{#{start_id}.query#}}}}"},
            ],
            "selected": False,
            "title": title,
            "type": "llm",
            "variables": [],
            "vision": {"enabled": False},
        },
        "height": 90,
        "id": node_id,
        "position": {"x": 680, "y": y},
        "positionAbsolute": {"x": 680, "y": y},
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": 244,
    }


def _end_node(node_id: str, llm_id: str, y: int) -> dict:
    return {
        "data": {
            "desc": "",
            "outputs": [
                {"value_selector": [llm_id, "text"], "value_type": "string", "variable": "text"}
            ],
            "selected": False,
            "title": "End",
            "type": "end",
        },
        "height": 90,
        "id": node_id,
        "position": {"x": 1000, "y": y},
        "positionAbsolute": {"x": 1000, "y": y},
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": 244,
    }


def _edge(src: str, handle: str, dst: str, src_type: str, dst_type: str) -> dict:
    return {
        "data": {
            "isInIteration": False,
            "isInLoop": False,
            "sourceType": src_type,
            "targetType": dst_type,
        },
        "id": f"{src}-{handle}-{dst}-target",
        "source": src,
        "sourceHandle": handle,
        "target": dst,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


def build_dsl(plugin_identifier: str) -> str:
    start_id, if_id = "1001", "1002"
    llm_parse_id, llm_draft_id = "1003", "1004"
    end_parse_id, end_draft_id = "1005", "1006"

    graph = {
        "edges": [
            _edge(start_id, "source", if_id, "start", "if-else"),
            _edge(if_id, "true", llm_parse_id, "if-else", "llm"),
            _edge(if_id, "false", llm_draft_id, "if-else", "llm"),
            _edge(llm_parse_id, "source", end_parse_id, "llm", "end"),
            _edge(llm_draft_id, "source", end_draft_id, "llm", "end"),
        ],
        "nodes": [
            {
                "data": {
                    "desc": "intent: parse_oa | draft_response. query: the full user message (OA text / rejection + grounded set).",
                    "selected": False,
                    "title": "Start",
                    "type": "start",
                    "variables": [
                        {
                            "label": "intent",
                            "variable": "intent",
                            "type": "select",
                            "required": True,
                            "max_length": None,
                            "options": ["parse_oa", "draft_response"],
                        },
                        {
                            "label": "query",
                            "variable": "query",
                            "type": "paragraph",
                            "required": True,
                            "max_length": None,
                            "options": [],
                        },
                    ],
                },
                "height": 116,
                "id": start_id,
                "position": {"x": 80, "y": 250},
                "positionAbsolute": {"x": 80, "y": 250},
                "selected": False,
                "sourcePosition": "right",
                "targetPosition": "left",
                "type": "custom",
                "width": 244,
            },
            {
                "data": {
                    "cases": [
                        {
                            "case_id": "true",
                            "conditions": [
                                {
                                    "comparison_operator": "is",
                                    "id": str(uuid.uuid4()),
                                    "value": "parse_oa",
                                    "varType": "string",
                                    "variable_selector": [start_id, "intent"],
                                }
                            ],
                            "id": "true",
                            "logical_operator": "and",
                        }
                    ],
                    "desc": "route by intent",
                    "selected": False,
                    "title": "IF intent == parse_oa",
                    "type": "if-else",
                },
                "height": 126,
                "id": if_id,
                "position": {"x": 380, "y": 250},
                "positionAbsolute": {"x": 380, "y": 250},
                "selected": False,
                "sourcePosition": "right",
                "targetPosition": "left",
                "type": "custom",
                "width": 244,
            },
            _llm_node(
                llm_parse_id, "LLM parse_oa", load_prompt("parse_oa"), start_id, 0.2, 1536, 120
            ),
            _llm_node(
                llm_draft_id,
                "LLM draft_response",
                load_prompt("draft_response"),
                start_id,
                0.3,
                2048,
                400,
            ),
            _end_node(end_parse_id, llm_parse_id, 120),
            _end_node(end_draft_id, llm_draft_id, 400),
        ],
    }

    dsl = {
        "app": {
            "description": (
                "PatentMind OA analysis (Phase 3). Routes parse_oa / draft_response "
                "to qwen2.5:7b on local Ollama. System prompts synced from "
                "backend/ai_engine/prompts/*.yaml by scripts/setup_dify.py. "
                "verify_citations deliberately stays in the PatentMind AI engine "
                "(Q14 deterministic hard wall)."
            ),
            "icon": "📄",
            "icon_background": "#E0F2FE",
            "mode": "workflow",
            "name": APP_NAME,
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [
            {
                "current_identifier": None,
                "type": "marketplace",
                "value": {"marketplace_plugin_unique_identifier": plugin_identifier},
            }
        ],
        "kind": "app",
        "version": "0.6.0",
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [],
            "features": {
                "file_upload": {"enabled": False},
                "opening_statement": "",
                "retriever_resource": {"enabled": False},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": [],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": graph,
        },
    }
    return yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dify-url", default=None)
    args = ap.parse_args()

    env = read_env()
    dify_url = args.dify_url or env.get("DIFY_API_URL") or "http://localhost:8088"
    email = env.get("DIFY_ADMIN_EMAIL") or "admin@patentmind.local"
    password = env.get("DIFY_ADMIN_PASSWORD") or f"PatentMind-{secrets.token_hex(6)}"

    c = DifyConsole(dify_url)

    print(f"[1/7] setup status @ {dify_url}")
    step = c.setup_status()
    if step == "not_started":
        print("  creating admin account ...")
        c.setup(email, "PatentMind Admin", password)
        upsert_env({"DIFY_ADMIN_EMAIL": email, "DIFY_ADMIN_PASSWORD": password})
        print(f"  [ok] admin created: {email} (credentials saved to .env)")
    else:
        if not env.get("DIFY_ADMIN_PASSWORD"):
            print("  ERROR: Dify already set up but DIFY_ADMIN_PASSWORD missing from .env")
            return 1
        password = env["DIFY_ADMIN_PASSWORD"]
        email = env.get("DIFY_ADMIN_EMAIL", email)
        print("  [ok] already set up")

    print("[2/7] console login")
    c.login(email, password)
    print("  [ok] logged in")

    print("[3/7] ollama plugin")
    c.install_ollama_plugin()

    print("[4/7] register models")
    llm_credentials = {
        "base_url": OLLAMA_BASE_URL_FROM_DIFY,
        "mode": "chat",
        "context_size": "32768",
        "max_tokens": "8192",
    }
    c.add_model(LLM_MODEL, "llm", llm_credentials)
    try:
        c.add_model(
            EMBED_MODEL,
            "text-embedding",
            {
                "base_url": OLLAMA_BASE_URL_FROM_DIFY,
                "context_size": "8192",
            },
        )
    except Exception as e:
        print(f"  [warn] embedding model registration failed (non-fatal): {e}")

    print("[5/7] workflow app")
    app_id = c.find_app()
    if app_id:
        print(f"  [ok] app already exists: {app_id}")
    else:
        ident = c.marketplace_identifier()
        app_id = c.import_dsl(build_dsl(ident))

    print("[6/7] publish workflow")
    c.publish_workflow(app_id)

    print("[7/7] service API key")
    key = c.service_api_key(app_id)
    upsert_env(
        {
            "DIFY_API_URL": dify_url,
            "DIFY_API_KEY_ANALYZE": key,
            "DIFY_ADMIN_EMAIL": email,
            "DIFY_ADMIN_PASSWORD": password,
        }
    )
    print(f"  [ok] key saved to .env: {key[:12]}…")
    print()
    print("DONE. To run the AI engine against Dify:")
    print("  set LLM_MODE=dify in .env (or env var) and restart the backend.")
    print(f"  Dify console: {dify_url}  ({email})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
