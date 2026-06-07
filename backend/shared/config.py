"""Centralised settings. Every magic number lives here.

各設定後面標 (Qxx) 對應 docs/DECISIONS.md
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import FrozenSet, Iterable, Union

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PATENT_DB_PATH = DATA_DIR / "patentmind.db"
AUDIT_DB_PATH = DATA_DIR / "audit.db"
MAPPING_DB_PATH = DATA_DIR / "redaction_mapping.db"  # Q10: 不上雲的 mapping table
# Q13 — durable write-ahead outbox for audit rows whose primary SQLite write
# failed (disk full / locked / trigger refusal). Appending to a flat JSONL is
# far more robust than the SQLite write that just failed; a separate
# replay_outbox() drains it back into the audit DB once the DB recovers.
# Kept beside the audit DB so an on-prem operator can back both up together.
AUDIT_OUTBOX_PATH = DATA_DIR / "audit_outbox.jsonl"
# Q13 WORM archive: sealed, immutable audit segments (POC of S3 Object Lock).
AUDIT_ARCHIVE_DIR = DATA_DIR / "audit_archive"
# Q20 DR/backup: snapshot+restore+drill target (per-timestamp backup sets).
BACKUP_DIR = DATA_DIR / "backups"
# Q10: per-tenant uploadable masking dictionaries live here as
# <tenant_id>.json (white-glove onboarding = file drop + reload, no deploy).
TENANT_DICTS_DIR = DATA_DIR / "tenant_dicts"


# ---------------------------------------------------------------------------
# Trusted-upstream IP parsing.
#
# Exposed at module level (NOT inside Settings) because the auth module needs
# to call it without owning an import cycle back to Settings, and because the
# boot-time guard below also calls it before `settings = Settings()` returns.
# ---------------------------------------------------------------------------
_IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _parse_trusted_ips(
    raw: Union[str, Iterable[str]],
) -> FrozenSet[_IPAddress]:
    """Parse TRUSTED_UPSTREAM_IPS into a set of ``ipaddress.IPv*Address``
    objects.

    Returns an empty frozenset when ``raw`` is empty (= upstream-trust
    kill switch).

    Plain IPs are accepted; CIDR ranges (e.g. ``'10.0.0.0/24'``) are NOT
    supported and raise :class:`ValueError` at config-load time. Operators
    who expect CIDR support should be told loudly rather than have it
    silently fail closed (which would force every legitimate upstream
    request down the JWT path with no log signal).

    Returning ``IPv*Address`` objects (not strings) lets the auth layer
    normalise the peer address through ``ipaddress.ip_address`` and compare
    on equality, which transparently handles IPv4-mapped-IPv6 (``::ffff:``)
    peers that uvicorn surfaces on dual-stack sockets.
    """
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        items = [s.strip() for s in raw if s and s.strip()]
    out: set[_IPAddress] = set()
    for item in items:
        if "/" in item:
            raise ValueError(
                f"TRUSTED_UPSTREAM_IPS does not support CIDR ranges; got "
                f"{item!r}. List each IP individually."
            )
        out.add(ipaddress.ip_address(item))
    return frozenset(out)


class Settings:
    # Service ports
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8010"))
    AI_ENGINE_PORT: int = int(os.getenv("AI_ENGINE_PORT", "8011"))
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://localhost:8010")
    AI_ENGINE_URL: str = os.getenv("AI_ENGINE_URL", "http://localhost:8011")

    # Auth (Q12)
    JWT_SECRET: str = os.getenv("JWT_SECRET", "changeme-generate-with-openssl-rand-hex-32")
    JWT_ALGO: str = "HS256"
    JWT_EXPIRES_MIN: int = 30
    # Q12: magic-link single-use token TTL (small-firm "no IdP, no password"
    # login path — /v1/auth/magic/request → /v1/auth/magic/consume).
    MAGIC_LINK_TTL_MIN: int = int(os.getenv("MAGIC_LINK_TTL_MIN", "15"))

    # Rate limit / Quota (Q18 全套)
    DEFAULT_RPM: int = 30                   # per-user request/minute
    # Day 8 post-review (Chunk A/B Important #1): login is pre-auth so
    # /v1/auth/login can't use DEFAULT_RPM (no user_id yet). Key on client
    # IP, stricter cap — brute-forcing demo-{user_id} passwords needs to
    # be very expensive even when the attacker reaches the gateway.
    LOGIN_RPM: int = int(os.getenv("LOGIN_RPM", "10"))
    DEFAULT_DAILY_TOKENS: int = 100_000     # per-user daily token quota
    TENANT_MONTHLY_TOKENS: int = 50_000_000 # per-tenant monthly cap
    REQUEST_HARD_LIMIT_TOKENS: int = 32_000 # single prompt hard cap
    COST_CIRCUIT_DAILY_USD: float = 100.0   # 日成本斷路器閾值（POC 用低值方便測）

    # LLM router (Q15 多模型 + 機密走地端)
    # Defaults below assume cloud Anthropic SDK (LLM_MODE=anthropic). They are
    # ignored when LLM_MODE=mock (MockLLM uses its own internal labels) and
    # when LLM_MODE=local (Ollama uses LLM_MODEL_LOCAL).
    LLM_MODE: str = os.getenv("LLM_MODE", "mock")  # mock | openai | anthropic | local
    LLM_MODEL_REASONING: str = os.getenv("LLM_MODEL_REASONING", "claude-sonnet-4-6")
    LLM_MODEL_CHEAP: str = os.getenv("LLM_MODEL_CHEAP", "claude-haiku-4-5-20251001")
    LLM_MODEL_LOCAL: str = os.getenv("LLM_MODEL_LOCAL", "llama3.1:8b")
    LLM_MODEL_VERIFIER: str = os.getenv("LLM_MODEL_VERIFIER", "claude-haiku-4-5-20251001")  # Q14 — MUST differ from REASONING
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")

    # Ollama / local LLM (MVP)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_TIMEOUT_SEC: int = int(os.getenv("OLLAMA_TIMEOUT_SEC", "600"))  # 600s 容 CPU 冷啟動

    # Cache (Q9)
    CACHE_BACKEND: str = os.getenv("CACHE_BACKEND", "memory")  # memory | redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL_RESPONSE_SEC: int = 3600        # LLM response cache 1hr
    CACHE_TTL_RETRIEVAL_SEC: int = 86400      # retrieval result 24hr
    CACHE_EMBEDDING_PERMANENT: bool = True    # patent embedding 永久

    # Vector store (Q7)
    VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "memory")  # memory | qdrant
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))  # mock 用 384；bge-m3 自動回報 1024
    # Q7 data-loss guard: when an existing Qdrant collection's vector dim
    # mismatches the current embedder (e.g. mock 384 ↔ bge-m3 1024),
    # QdrantVectorStore REFUSES by default rather than silently dropping the
    # tenant's index. Set QDRANT_ALLOW_REINDEX=true ONLY for a deliberate,
    # operator-driven re-index where data loss is acceptable.
    QDRANT_ALLOW_REINDEX: bool = os.getenv("QDRANT_ALLOW_REINDEX", "false").lower() in ("1", "true", "yes")

    # Embedding (Q5/Q7 — POC 預設 mock；切 bge-m3 用 SentenceTransformer)
    EMBEDDING_BACKEND: str = os.getenv("EMBEDDING_BACKEND", "mock")  # mock | bge-m3
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    # Storage (Q13 archive / Q20 backups)
    AUDIT_BACKEND: str = os.getenv("AUDIT_BACKEND", "sqlite")  # sqlite | postgres
    POSTGRES_URL: str = os.getenv(
        "POSTGRES_URL",
        "postgresql://patentmind:patentmind@localhost:5432/patentmind",
    )

    # Holiday calendar (Q17)
    HOLIDAY_CALENDAR_VERSION: str = "2025.1"
    SUPPORTED_JURISDICTIONS: tuple[str, ...] = ("TW", "US", "JP")  # 其他國家留 stub

    # Tenants（POC 預設兩家事務所做 demo）
    DEMO_TENANTS: dict[str, dict] = {
        "tenant_a": {"name": "Apex Patent Law Firm", "monthly_token_cap": 50_000_000},
        "tenant_b": {"name": "BetaLegal IP Group", "monthly_token_cap": 50_000_000},
    }

    # Security level mapping (Q15 router)
    LOCAL_LLM_FOR_SECURITY_LEVELS: tuple[str, ...] = ("confidential", "top_secret")

    # Upstream auth trust (Compat Refactor 3 — digiRunner migration prep).
    # Trusted upstream IPs that may set x-user-id / x-tenant-id / x-user-role
    # headers (= digiRunner-validated identity). Anyone NOT from these IPs
    # falls back to JWT auth. Comma-separated; empty = upstream-header auth
    # disabled. Localhost-only by default — DO NOT add 0.0.0.0 / wildcards.
    TRUSTED_UPSTREAM_IPS: tuple[str, ...] = tuple(
        ip.strip()
        for ip in os.getenv("TRUSTED_UPSTREAM_IPS", "127.0.0.1,::1").split(",")
        if ip.strip()
    )

    # Optional defence-in-depth shared secret. When set, requests claiming
    # upstream identity must also present a matching `x-upstream-auth-token`
    # header or the upstream-trust path declines. Empty = secret check
    # disabled (relies on IP trust alone — acceptable for loopback-only
    # deployments). REQUIRED when TRUSTED_UPSTREAM_IPS contains any
    # non-loopback entry in non-mock mode (enforced at boot below).
    UPSTREAM_AUTH_SHARED_SECRET: str = os.getenv("UPSTREAM_AUTH_SHARED_SECRET", "")

    # PDF upload (Day 2)
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "30"))
    MIN_CHARS_PER_PAGE_FOR_TEXT: int = int(os.getenv("MIN_CHARS_PER_PAGE_FOR_TEXT", "30"))
    OCR_PARALLELISM: int = int(os.getenv("OCR_PARALLELISM", "4"))
    # OCR backend (Q8 / invariant #7). mock = deterministic placeholder (tests/
    # demo); tesseract = on-prem local OCR (the ONLY path allowed for
    # confidential scanned PDFs — cloud is forbidden for them); vision = cloud
    # Claude Vision. Default mock keeps the suite hermetic.
    OCR_BACKEND: str = os.getenv("OCR_BACKEND", "mock")  # mock | tesseract | vision
    OCR_TESSERACT_LANG: str = os.getenv("OCR_TESSERACT_LANG", "chi_tra+eng")

    # AI Engine prompt introspection (Compat Refactor 1)
    # When false, GET /v1/prompts and GET /v1/prompts/{intent} return 404 so
    # the system-prompt text never leaves the box, even via the intra-VPC
    # surface. Default is true to keep Dify import + dev sanity flows working.
    EXPOSE_PROMPT_API: bool = os.getenv("EXPOSE_PROMPT_API", "true").lower() in ("1", "true", "yes")

    # ------------------------------------------------------------------
    # Security Chunk A — C-1 / C-2 / H-8
    # ------------------------------------------------------------------
    # Frictionless demo login. When set, /v1/auth/login accepts an
    # `X-Demo-Secret` header instead of a password for any known user, so
    # the SPA's "click Alice" flow keeps working without typing. Leave
    # UNSET in production — the password path remains available unconditionally.
    DEMO_LOGIN_SECRET: str = os.getenv("DEMO_LOGIN_SECRET", "")

    # Shared secret on outbound gateway -> AI Engine calls. AI Engine's
    # middleware refuses any non-`/v1/health` request that lacks a matching
    # `X-Internal-Token`. Empty + mock mode = permit (so pytest's in-process
    # ASGITransport works). Empty + non-mock mode = refuse everything except
    # health (loud failure, see notes below).
    INTERNAL_TOKEN: str = os.getenv("INTERNAL_TOKEN", "")

    # ------------------------------------------------------------------
    # Security Chunk C — H-1 / H-2 / M-1 / M-9
    # ------------------------------------------------------------------
    # CORS allow-list. Comma-separated origin tuple, default localhost dev
    # SPA. Production deployments MUST set this to their actual SPA origin
    # (e.g. "https://patentmind.example.com"). Wildcards (`*`) are honoured
    # by Starlette's CORSMiddleware as-is but disabled here by convention —
    # the explicit list closes H-1 in the audit (CORS allowing `*`
    # methods + headers from any origin).
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = tuple(
        s.strip()
        for s in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
        if s.strip()
    )

    # Request-body bytes cap (H-2). FastAPI's body parsing is unbounded by
    # default — a 1 GB JSON POST would buffer 1 GB in memory before Pydantic
    # rejects it on `max_length`. The MaxBodySizeMiddleware rejects oversized
    # bodies with 413 BEFORE any parse using the `Content-Length` header,
    # falling back to a streaming check when the header is absent.
    # Default 100MB is generous for multipart PDF uploads (cap = MAX_UPLOAD_MB
    # which is 30MB by default) while still bounding memory blowup.
    MAX_BODY_BYTES: int = int(os.getenv("MAX_BODY_BYTES", str(100 * 1024 * 1024)))

    # uvicorn bind host (M-9). The `python -m backend.gateway.main` /
    # `__main__` blocks used to default to 0.0.0.0 — i.e. exposed on every
    # network interface. Production binds 127.0.0.1 and exposes via a
    # reverse proxy (digiRunner / nginx) on the actual public port. Override
    # to 0.0.0.0 only when the host is intentionally a public edge.
    LISTEN_HOST: str = os.getenv("LISTEN_HOST", "127.0.0.1")

    # ------------------------------------------------------------------
    # Security Chunk D — H-3 / H-4 / M-3 / M-6 / M-7 / M-8
    # ------------------------------------------------------------------
    # Per-tenant ceiling on the in-memory cache (M-8). When a tenant hits
    # the cap the oldest entry is evicted FIFO. 1000 is generous for the
    # POC workload (cached responses live an hour; the response size
    # averages ~50KB so worst case is ~50MB per tenant). Set to 0 to
    # disable the cap (NOT recommended in production — one tenant's
    # bursty traffic will starve another).
    MAX_CACHE_ENTRIES_PER_TENANT: int = int(os.getenv("MAX_CACHE_ENTRIES_PER_TENANT", "1000"))

    # Egress guard (Q3 / invariant #3 enforcement). When True, the gateway's
    # single egress point to the AI Engine (AIEngineClient.call) recursively
    # scans every outbound string value for raw PII patterns (the same
    # PII_RULES used by the masking layer). A hit means redaction escaped —
    # the call is BLOCKED (EgressGuardError) and an error-level alert logged.
    # This turns invariant #3 from a grep-by-convention into a hard,
    # fail-closed technical chokepoint. Kept ON even in mock mode so the demo
    # shows enforcement. Set EGRESS_GUARD_ENABLED=false ONLY for debugging.
    EGRESS_GUARD_ENABLED: bool = os.getenv("EGRESS_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")

    # Q11 prompt-injection layer 5 (canary) + layer 3 (output filter). When
    # True, oa_analyzer plants a per-call canary in the hardened system prompt
    # and scans every LLM response for it (and other injection signatures);
    # a hit FAILS CLOSED (InjectionDetected). Kept ON even in mock mode so the
    # demo shows enforcement. Set INJECTION_GUARD_ENABLED=false ONLY for debugging.
    INJECTION_GUARD_ENABLED: bool = os.getenv("INJECTION_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")

    # Mapping-table at-rest encryption (Q3/Q10 crown jewel). Master key for
    # the per-tenant HKDF derivation that encrypts the reversible un-redaction
    # map. Empty = POC derives a deterministic dev key (logs a WARNING).
    # Production MUST set this to a real secret (env / secret manager); the key
    # lives OUTSIDE the DB so theft of redaction_mapping.db alone is useless.
    MAPPING_ENCRYPTION_KEY: str = os.getenv("MAPPING_ENCRYPTION_KEY", "")

    # Redaction ruleset version (M-7). Embedded in the cache prompt hash
    # so a ruleset change (new PII rule, tenant dictionary refresh)
    # invalidates pre-change cached responses. Bump this any time
    # PII_RULES or TENANT_DICTIONARIES (in backend/gateway/masking.py)
    # changes in a way that affects redaction output for a previously
    # served input.
    REDACTION_VERSION: str = os.getenv("REDACTION_VERSION", "v1")


settings = Settings()


# --- Parse trusted-upstream IPs once at module load -----------------------
# Exposing the parsed frozenset here (rather than re-parsing per request in
# auth.py) means a malformed `TRUSTED_UPSTREAM_IPS` (e.g. CIDR notation) is
# caught at import-time — uvicorn fails to start with a clear ValueError,
# instead of running fine until the first request that triggers parsing.
# Tests that mutate `settings.TRUSTED_UPSTREAM_IPS` should re-derive the
# parsed set via `_parse_trusted_ips(settings.TRUSTED_UPSTREAM_IPS)` (the
# auth module does this lazily so monkeypatching keeps working).
_TRUSTED_IPS_PARSED: frozenset = _parse_trusted_ips(settings.TRUSTED_UPSTREAM_IPS)


# --- Boot-time guardrail: refuse to run with the placeholder JWT_SECRET ----
# Security Chunk A (C-4): previously this only fired in non-mock mode, but
# the demo IS mock mode — so the placeholder was effectively allowed in the
# config every visitor would see. .env.example publishes the placeholder
# string, which means anyone with read access to the repo could sign their
# own tokens and bypass C-1 entirely.
#
# Now: refuse in ALL modes. The single exception is pytest, which sets its
# own ephemeral secret (`test-secret-do-not-use-elsewhere-32bytes!!`) in
# tests/conftest.py — that string is distinct from the placeholder, so the
# guard never fires under the test harness even though PYTEST_CURRENT_TEST
# is exported per-test by pytest.
_PLACEHOLDER_JWT_SECRET = "changeme-generate-with-openssl-rand-hex-32"
if (
    "PYTEST_CURRENT_TEST" not in os.environ
    and settings.JWT_SECRET == _PLACEHOLDER_JWT_SECRET
):
    raise RuntimeError(
        "JWT_SECRET is the published placeholder string. Refusing to boot "
        "in ANY mode (mock included — that's the demo config and the "
        "string is public). Generate a real secret via:\n"
        "    openssl rand -hex 32\n"
        "then set JWT_SECRET in your .env. See scripts/start_demo.sh for "
        "the auto-generation path."
    )


# --- Boot-time guardrail: non-loopback upstream trust requires a secret ---
# Rationale: deployments often add a sidecar / mesh proxy between digiRunner
# and us. The moment ops adds that proxy's IP to the trust list without
# configuring a shared secret, every pod in the mesh can forge identities
# (the upstream-trust path will honour their x-user-id headers). Fail loud
# at boot, not silent in prod.
#
# Loopback (127.0.0.1, ::1, and the IPv4-mapped-IPv6 form ::ffff:127.0.0.1)
# is exempt: only processes on the same host can talk to it, so an attacker
# already needs local code execution to abuse the trust.
def _validate_upstream_trust_config() -> None:
    """Refuse to boot if TRUSTED_UPSTREAM_IPS includes a non-loopback IP
    without a shared secret AND we're not in mock/test mode."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return  # test fixtures handle their own trust config
    if settings.LLM_MODE == "mock":
        return  # POC / demo mode — trust is local-only by convention
    loopback_ips = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
        # IPv4-mapped-IPv6 of loopback. We compare on normalised
        # ip_address so an entry of ``::ffff:127.0.0.1`` in the trust list
        # is treated as loopback too.
        ipaddress.ip_address("::ffff:127.0.0.1").ipv4_mapped
        or ipaddress.ip_address("::ffff:127.0.0.1"),
    }
    non_loopback = {str(ip) for ip in _TRUSTED_IPS_PARSED if ip not in loopback_ips}
    if non_loopback and not settings.UPSTREAM_AUTH_SHARED_SECRET:
        raise RuntimeError(
            f"TRUSTED_UPSTREAM_IPS contains non-loopback IPs {sorted(non_loopback)} "
            f"but UPSTREAM_AUTH_SHARED_SECRET is empty. Set the secret OR remove "
            f"the non-loopback entries OR set LLM_MODE=mock. "
            f"See backend/gateway/auth.py for the trust model."
        )


_validate_upstream_trust_config()
