#!/usr/bin/env bash
# LIVE smoke test for the real Keycloak OIDC path (Q12 P0, OIDC_MODE=keycloak).
#
# Bring the IdP up first (realm `patentmind` auto-imports from
# keycloak/realm-patentmind.json):
#     docker compose up -d keycloak
#
# What this verifies, end to end:
#   1. discovery        — {issuer}/.well-known/openid-configuration answers
#                         and self-declares the configured issuer
#   2. token exchange   — password grant for alice proves realm import +
#                         confidential client secret + direct access grants
#   3. full code flow   — headless browser-less authorization-code flow:
#                         gateway /v1/auth/oidc/begin → Keycloak login form
#                         (cookie jar + form POST) → redirect with ?code= →
#                         gateway /v1/auth/oidc/callback → OUR gateway JWT
#   4. ACL still bites  — the federated session 403s on a case outside
#                         alice's ACL (invariant #6) and the role/tenant are
#                         the server-pinned ones (attorney / tenant_a)
#
# If the gateway (:8010) is not already running in OIDC_MODE=keycloak, an
# EPHEMERAL gateway is started on :18010 just for this test and torn down on
# exit. Keycloak being down is a SKIP (exit 0), not a failure — mirrors the
# pytest live-tier convention.
#
# Usage: bash scripts/smoke_keycloak.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Load the env the backend would load.
if [ -f .env ]; then
  set -a; source <(grep -E '^[A-Za-z_]+=' .env); set +a
fi
export PYTHONUTF8=1

KC_ISSUER="${OIDC_KEYCLOAK_ISSUER:-http://localhost:8081/realms/patentmind}"
KC_CLIENT_ID="${OIDC_KEYCLOAK_CLIENT_ID:-patentmind-gateway}"
# Dev secret shipped in keycloak/realm-patentmind.json.
KC_CLIENT_SECRET="${OIDC_KEYCLOAK_CLIENT_SECRET:-patentmind-gateway-dev-secret-change-me}"

# ---------------------------------------------------------------------------
# 1. Keycloak reachable? (not reachable => SKIP, exit 0)
# ---------------------------------------------------------------------------
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$KC_ISSUER/.well-known/openid-configuration" || true)
if [ "$code" != "200" ]; then
  echo "SKIP: Keycloak not reachable at $KC_ISSUER (got $code)."
  echo "      Start it with: docker compose up -d keycloak"
  exit 0
fi
echo "[ok] 1/4 discovery document served at $KC_ISSUER"

# ---------------------------------------------------------------------------
# 2-4 run in python (httpx): cookie jar + HTML form parsing beat curl/sed on
# Windows Git Bash. Subprocesses inherit PYTHONUTF8=1 (cp950 locale guard).
# ---------------------------------------------------------------------------
GATEWAY_URL_DEFAULT="${GATEWAY_URL:-http://localhost:8010}"
EPHEMERAL_PORT=18010
EPHEMERAL_PID=""

cleanup() {
  if [ -n "$EPHEMERAL_PID" ]; then
    kill "$EPHEMERAL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Is a gateway already up AND in keycloak mode? (its /begin must return the
# realm's authorize endpoint). Otherwise boot an ephemeral one on :18010.
GW="$GATEWAY_URL_DEFAULT"
begin_url=$(curl -s -m 3 "$GW/v1/auth/oidc/begin" | python -c "import sys,json;\
print(json.load(sys.stdin).get('authorize_url',''))" 2>/dev/null || true)
if [[ "$begin_url" != "$KC_ISSUER"* ]]; then
  echo "[i] no keycloak-mode gateway on $GW — starting ephemeral gateway on :$EPHEMERAL_PORT"
  OIDC_MODE=keycloak \
  OIDC_KEYCLOAK_ISSUER="$KC_ISSUER" \
  OIDC_KEYCLOAK_CLIENT_ID="$KC_CLIENT_ID" \
  OIDC_KEYCLOAK_CLIENT_SECRET="$KC_CLIENT_SECRET" \
  OIDC_REDIRECT_URI="http://localhost:5173/auth/oidc/callback" \
  JWT_SECRET="${JWT_SECRET:-smoke-keycloak-ephemeral-$(date +%s)-secret}" \
  LLM_MODE=mock \
  python -m uvicorn backend.gateway.main:app --host 127.0.0.1 --port "$EPHEMERAL_PORT" \
    >/tmp/smoke_keycloak_gateway.log 2>&1 &
  EPHEMERAL_PID=$!
  GW="http://127.0.0.1:$EPHEMERAL_PORT"
  for _ in $(seq 1 30); do
    curl -s -o /dev/null -m 1 "$GW/v1/health" && break
    sleep 1
  done
fi
echo "[i] gateway under test: $GW"

KC_ISSUER="$KC_ISSUER" KC_CLIENT_ID="$KC_CLIENT_ID" KC_CLIENT_SECRET="$KC_CLIENT_SECRET" GW="$GW" \
python - <<'PY'
import html
import os
import re
import sys

import httpx

issuer = os.environ["KC_ISSUER"]
client_id = os.environ["KC_CLIENT_ID"]
client_secret = os.environ["KC_CLIENT_SECRET"]
gw = os.environ["GW"]

disc = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10).json()
assert disc["issuer"] == issuer, f"issuer mismatch: {disc['issuer']}"

# --- 2. password grant (realm import + client secret sanity) ---------------
r = httpx.post(
    disc["token_endpoint"],
    data={
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": "alice",
        "password": "demo-alice",
        "scope": "openid",
    },
    timeout=15,
)
assert r.status_code == 200, f"password grant failed: {r.status_code} {r.text[:300]}"
assert r.json().get("id_token"), "no id_token (scope=openid?)"
print("[ok] 2/4 password grant: realm users + client secret valid")

# --- 3. full authorization-code flow through the gateway --------------------
begin = httpx.get(f"{gw}/v1/auth/oidc/begin", timeout=10)
assert begin.status_code == 200, f"/begin failed: {begin.status_code} {begin.text[:300]}"
begin = begin.json()
assert begin["authorize_url"].startswith(issuer), begin["authorize_url"]

# Keycloak marks its auth cookies `Secure; SameSite=None` even on plain http
# (real browsers treat localhost as a secure context and still send them;
# httpx's cookiejar correctly refuses Secure-over-http). Headless workaround:
# capture Set-Cookie ourselves and replay them in a manual Cookie header.
cookies: dict[str, str] = {}


def _collect(resp: httpx.Response) -> None:
    for sc in resp.headers.get_list("set-cookie"):
        nv = sc.split(";", 1)[0]
        if "=" in nv:
            name, value = nv.split("=", 1)
            cookies[name.strip()] = value.strip()


def _cookie_header() -> dict[str, str]:
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())} if cookies else {}


with httpx.Client(timeout=15, follow_redirects=False) as browser:
    page = browser.get(begin["authorize_url"])
    _collect(page)
    while page.status_code in (302, 303):
        page = browser.get(page.headers["location"], headers=_cookie_header())
        _collect(page)
    assert page.status_code == 200, f"authorize page: {page.status_code}"
    m = re.search(r'action="([^"]+)"', page.text)
    assert m, "could not find Keycloak login form action"
    form_action = html.unescape(m.group(1))
    login = browser.post(
        form_action,
        data={"username": "alice", "password": "demo-alice", "credentialId": ""},
        headers=_cookie_header(),
    )
    assert login.status_code in (302, 303), f"login POST: {login.status_code} {login.text[:300]}"
    location = login.headers["location"]
    code_m = re.search(r"[?&]code=([^&]+)", location)
    state_m = re.search(r"[?&]state=([^&]+)", location)
    assert code_m and state_m, f"redirect carries no code/state: {location}"
    assert state_m.group(1) == begin["state"], "state did not round-trip"

cb = httpx.post(
    f"{gw}/v1/auth/oidc/callback",
    json={"code": code_m.group(1), "state": begin["state"]},
    timeout=15,
)
assert cb.status_code == 200, f"/callback failed: {cb.status_code} {cb.text[:300]}"
session = cb.json()
assert session["user_id"] == "alice", session
assert session["role"] == "attorney", session     # pinned server-side
assert session["tenant_id"] == "tenant_a", session
token = session["token"]
print("[ok] 3/4 code flow: Keycloak login -> code -> gateway JWT "
      f"(user={session['user_id']}, role={session['role']})")

# --- 4. case ACL still enforced on the federated session (invariant #6) ----
headers = {"Authorization": f"Bearer {token}"}
denied = httpx.post(
    f"{gw}/v1/oa/analyze",
    headers=headers,
    json={
        "oa_text": "Claim 1 is rejected under 35 U.S.C. 103.",
        "case_id": "CASE-2025-999",
        "target_patent_no": "US1234567",
    },
    timeout=15,
)
assert denied.status_code == 403, f"expected 403 on foreign case, got {denied.status_code}"
# A replayed state must be refused (single-use CSRF) — uniform 401.
replay = httpx.post(
    f"{gw}/v1/auth/oidc/callback",
    json={"code": code_m.group(1), "state": begin["state"]},
    timeout=15,
)
assert replay.status_code == 401, f"replayed state must 401, got {replay.status_code}"
print("[ok] 4/4 case ACL enforced (403 on foreign case) + state replay refused (401)")
print("ALL KEYCLOAK SMOKE CHECKS PASSED")
PY
