"""Centralised settings. Every magic number lives here.

各設定後面標 (Qxx) 對應 docs/DECISIONS.md
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Union

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
) -> frozenset[_IPAddress]:
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
    # H-5: pin issuer + audience on session tokens. Without them a token signed
    # by ANY other service sharing JWT_SECRET would be accepted here
    # (confused-deputy). verify_token enforces both; env-overridable per
    # deployment so a multi-env estate can scope tokens to one environment.
    JWT_ISS: str = os.getenv("JWT_ISS", "patentmind-gateway")
    JWT_AUD: str = os.getenv("JWT_AUD", "patentmind-api")
    # H-5 phase 3: asymmetric signing. Set JWT_ALGO=RS256 (or ES256/PS256) and
    # supply PEM keys via env to sign with a private key and verify with the
    # public key — so a service that only needs to VERIFY tokens never holds a
    # key that can MINT them. Empty + HS256 (default) keeps the symmetric POC path.
    JWT_PRIVATE_KEY: str = os.getenv("JWT_PRIVATE_KEY", "")
    JWT_PUBLIC_KEY: str = os.getenv("JWT_PUBLIC_KEY", "")
    # Q12: magic-link single-use token TTL (small-firm "no IdP, no password"
    # login path — /v1/auth/magic/request → /v1/auth/magic/consume).
    MAGIC_LINK_TTL_MIN: int = int(os.getenv("MAGIC_LINK_TTL_MIN", "15"))

    # Rate limit / Quota (Q18 全套)
    DEFAULT_RPM: int = 30  # per-user request/minute
    # Day 8 post-review (Chunk A/B Important #1): login is pre-auth so
    # /v1/auth/login can't use DEFAULT_RPM (no user_id yet). Key on client
    # IP, stricter cap — brute-forcing demo-{user_id} passwords needs to
    # be very expensive even when the attacker reaches the gateway.
    LOGIN_RPM: int = int(os.getenv("LOGIN_RPM", "10"))
    DEFAULT_DAILY_TOKENS: int = 100_000  # per-user daily token quota
    TENANT_MONTHLY_TOKENS: int = 50_000_000  # per-tenant monthly cap
    REQUEST_HARD_LIMIT_TOKENS: int = 32_000  # single prompt hard cap
    COST_CIRCUIT_DAILY_USD: float = 100.0  # 日成本斷路器閾值（POC 用低值方便測）

    # LLM router (Q15 多模型 + 機密走地端)
    # Defaults below assume cloud Anthropic SDK (LLM_MODE=anthropic). They are
    # ignored when LLM_MODE=mock (MockLLM uses its own internal labels) and
    # when LLM_MODE=local (Ollama uses LLM_MODEL_LOCAL).
    LLM_MODE: str = os.getenv("LLM_MODE", "mock")  # mock | openai | anthropic | local | dify
    LLM_MODEL_REASONING: str = os.getenv("LLM_MODEL_REASONING", "claude-sonnet-4-6")
    LLM_MODEL_CHEAP: str = os.getenv("LLM_MODEL_CHEAP", "claude-haiku-4-5-20251001")
    LLM_MODEL_LOCAL: str = os.getenv("LLM_MODEL_LOCAL", "llama3.1:8b")
    LLM_MODEL_VERIFIER: str = os.getenv(
        "LLM_MODEL_VERIFIER", "claude-haiku-4-5-20251001"
    )  # Q14 — MUST differ from REASONING
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")

    # Ollama / local LLM (MVP)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_TIMEOUT_SEC: int = int(os.getenv("OLLAMA_TIMEOUT_SEC", "600"))  # 600s 容 CPU 冷啟動

    # ------------------------------------------------------------------
    # Dify (Phase 3 — LLM_MODE=dify routes parse_oa / draft_response through
    # a self-hosted Dify CE workflow app whose LLM nodes run on local Ollama).
    # The Q14 verifier stays IN OUR CODE (deterministic regex hard wall +
    # MockLLM second opinion) — see backend/ai_engine/llm_client.py:DifyLLM.
    # ------------------------------------------------------------------
    # Base URL of the Dify CE nginx (docker EXPOSE_NGINX_PORT). The Service
    # API lives under {DIFY_API_URL}/v1/* .
    DIFY_API_URL: str = os.getenv("DIFY_API_URL", "http://localhost:8088")
    # Service API key ("app-…") of the patentmind-analyze-oa WORKFLOW app.
    # Generated by scripts/setup_dify.py; one key per app.
    DIFY_API_KEY_ANALYZE: str = os.getenv("DIFY_API_KEY_ANALYZE", "")
    # Per-call wall-clock timeout (seconds). qwen2.5:7b on CPU can take
    # 60-120s for a long zh-TW draft, so the default is generous.
    DIFY_TIMEOUT_SEC: float = float(os.getenv("DIFY_TIMEOUT_SEC", "300"))
    # Label reported as `model_used` in response metadata when LLM_MODE=dify
    # (the actual model is configured inside the Dify workflow's LLM nodes).
    DIFY_MODEL_LABEL: str = os.getenv("DIFY_MODEL_LABEL", "dify/qwen2.5:7b")
    # Q15 defense-in-depth: operator's explicit claim that the Dify workflow's
    # LLM nodes point at a LOCAL provider (our deployment: Ollama on this
    # host). Flip to false if the workflow is repointed at a cloud model --
    # confidential (-CONF) cases will then hard-fail in llm_client instead of
    # silently egressing (review P2-1; mirrors the anthropic-path guard).
    DIFY_EGRESS_LOCAL: bool = os.getenv("DIFY_EGRESS_LOCAL", "true").lower() in ("1", "true", "yes")

    # Cache (Q9)
    CACHE_BACKEND: str = os.getenv("CACHE_BACKEND", "memory")  # memory | redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # [H-5] session-token revocation store. `memory` is per-process (lost on
    # restart, not shared across replicas) — fine for a single-replica POC.
    # `redis` makes the logout kill switch durable + fleet-wide, with each jti
    # auto-expiring at the token's own TTL so the set stays bounded.
    REVOCATION_BACKEND: str = os.getenv("REVOCATION_BACKEND", "memory")  # memory | redis
    CACHE_TTL_RESPONSE_SEC: int = 3600  # LLM response cache 1hr
    CACHE_TTL_RETRIEVAL_SEC: int = 86400  # retrieval result 24hr
    CACHE_EMBEDDING_PERMANENT: bool = True  # patent embedding 永久

    # Vector store (Q7)
    VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "memory")  # memory | qdrant
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))  # mock 用 384；bge-m3 自動回報 1024
    # Q7 data-loss guard: when an existing Qdrant collection's vector dim
    # mismatches the current embedder (e.g. mock 384 ↔ bge-m3 1024),
    # QdrantVectorStore REFUSES by default rather than silently dropping the
    # tenant's index. Set QDRANT_ALLOW_REINDEX=true ONLY for a deliberate,
    # operator-driven re-index where data loss is acceptable.
    QDRANT_ALLOW_REINDEX: bool = os.getenv("QDRANT_ALLOW_REINDEX", "false").lower() in (
        "1",
        "true",
        "yes",
    )

    # Embedding (Q5/Q7 — POC 預設 mock；切 bge-m3 用 SentenceTransformer)
    EMBEDDING_BACKEND: str = os.getenv("EMBEDDING_BACKEND", "mock")  # mock | bge-m3
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    # Storage (Q13 archive / Q20 backups)
    AUDIT_BACKEND: str = os.getenv("AUDIT_BACKEND", "sqlite")  # sqlite | postgres
    # Postgres DSN for AUDIT_BACKEND=postgres. NB: the compose container binds
    # host port 15432 on the delivery box (5432 is taken) — set
    # POSTGRES_URL=postgresql://patentmind:patentmind@localhost:15432/patentmind
    # in .env when enabling the postgres audit backend.
    POSTGRES_URL: str = os.getenv(
        "POSTGRES_URL",
        "postgresql://patentmind:patentmind@localhost:5432/patentmind",
    )

    # ------------------------------------------------------------------
    # Q13 WORM archive target (audit_archive.py).
    #   "local" (default) — sealed segments in AUDIT_ARCHIVE_DIR, files
    #                       flipped read-only (Object Lock simulation; zero infra).
    #   "s3"              — real S3-compatible Object Lock bucket (MinIO in the
    #                       delivery compose on :19000; AWS S3 in production).
    #                       Bucket MUST be created with Object Lock enabled:
    #                       python scripts/init_minio.py
    # ------------------------------------------------------------------
    ARCHIVE_BACKEND: str = os.getenv("ARCHIVE_BACKEND", "local")  # local | s3
    ARCHIVE_S3_ENDPOINT: str = os.getenv("ARCHIVE_S3_ENDPOINT", "http://localhost:19000")
    ARCHIVE_S3_ACCESS_KEY: str = os.getenv("ARCHIVE_S3_ACCESS_KEY", "patentmind")
    ARCHIVE_S3_SECRET_KEY: str = os.getenv("ARCHIVE_S3_SECRET_KEY", "patentmind-minio")
    ARCHIVE_S3_BUCKET: str = os.getenv("ARCHIVE_S3_BUCKET", "patentmind-audit-worm")
    ARCHIVE_S3_REGION: str = os.getenv("ARCHIVE_S3_REGION", "us-east-1")
    # Object Lock retention applied to every sealed segment/manifest object.
    # GOVERNANCE: a principal with s3:BypassGovernanceRetention can still
    #             remove (safe default for dev/MinIO — buckets stay cleanable).
    # COMPLIANCE: NOBODY (not even root) can remove until expiry — the
    #             production posture for the Q13 7-year retention.
    ARCHIVE_S3_RETENTION_MODE: str = os.getenv(
        "ARCHIVE_S3_RETENTION_MODE", "GOVERNANCE"
    )  # GOVERNANCE | COMPLIANCE
    # Retention period in days (mirrors AUDIT_WORM_RETENTION_DAYS' intent;
    # default = the Q13 7-year requirement).
    ARCHIVE_S3_RETENTION_DAYS: int = int(os.getenv("ARCHIVE_S3_RETENTION_DAYS", str(7 * 365)))

    # Holiday calendar (Q17)
    HOLIDAY_CALENDAR_VERSION: str = "2025.1"
    # Six jurisdictions are now fully implemented in backend/ai_engine/deadline.py
    # (TW/US with attorney-grade rules; JP/EP/CN/KR as documented POC
    # approximations). Anything outside this set falls through to the 60-day
    # naive stub + a loud warning.
    SUPPORTED_JURISDICTIONS: tuple[str, ...] = ("TW", "US", "JP", "EP", "CN", "KR")

    # ---- Agent C — holiday-provider source selection (Q17 production path) ----
    # Selects which HolidayProvider backs the deadline engine. ADDITIVE: the
    # default keeps the existing hermetic, version-locked behaviour byte-for-byte.
    #   "bundled" — StaticBundledProvider: hard-coded fallback + shipped JSON
    #               files in data/calendars/. Hermetic; what tests + CI use.
    #   "jsonfile" — JsonFileProvider: ONLY data/calendars/*.json (no hard-coded
    #               fallback), so a cron-refreshed file is authoritative and a
    #               missing file surfaces loudly. Still offline.
    #   "remote"  — RemoteHolidayProvider (STUB): would pull data.gov.tw (TW) /
    #               USPTO (US) live. NotImplementedError is swallowed by the
    #               caching layer so enabling it is safe-but-inert (falls through
    #               to the bundled calendars) until the real fetcher is wired.
    # Tests NEVER select "remote"; no network is ever touched by the suite.
    HOLIDAY_SOURCE: str = os.getenv("HOLIDAY_SOURCE", "bundled")  # bundled|jsonfile|remote
    # Remote endpoints (documentation only until RemoteHolidayProvider lands).
    HOLIDAY_REMOTE_TW_URL: str = os.getenv(
        "HOLIDAY_REMOTE_TW_URL",
        "https://data.gov.tw/dataset/14718",  # 行政院人事行政總處 政府行政機關辦公日曆表
    )
    HOLIDAY_REMOTE_US_URL: str = os.getenv(
        "HOLIDAY_REMOTE_US_URL",
        "https://www.uspto.gov/about-us/uspto-locations/hours-and-holidays",
    )
    # Network timeout the (future) remote provider would use, seconds.
    HOLIDAY_REMOTE_TIMEOUT_S: float = float(os.getenv("HOLIDAY_REMOTE_TIMEOUT_S", "10"))

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
    EGRESS_GUARD_ENABLED: bool = os.getenv("EGRESS_GUARD_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # Q11 prompt-injection layer 5 (canary) + layer 3 (output filter). When
    # True, oa_analyzer plants a per-call canary in the hardened system prompt
    # and scans every LLM response for it (and other injection signatures);
    # a hit FAILS CLOSED (InjectionDetected). Kept ON even in mock mode so the
    # demo shows enforcement. Set INJECTION_GUARD_ENABLED=false ONLY for debugging.
    INJECTION_GUARD_ENABLED: bool = os.getenv("INJECTION_GUARD_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )

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
    #
    # Agent A — Day 12A: bumped v1 -> v2. The Day 12A masking hardening
    # changes redaction OUTPUT for previously-served inputs (zero-width strip,
    # homoglyph fold, and new PII rules: phone_tw_landline / phone_intl /
    # tw_company_tax_id / passport / ipv4 / ipv6). Any response cached under v1
    # may contain now-redactable PII (or differ in normalisation), so v1 cache
    # entries MUST be invalidated. cache.hash_prompt's own default stays "v1"
    # (function-level back-compat); the orchestrator passes this setting.
    REDACTION_VERSION: str = os.getenv("REDACTION_VERSION", "v2")

    # -----------------------------------------------------------------------
    # Agent D — Q19 observability + Q20 DR/backup retention.
    # -----------------------------------------------------------------------
    # Structured logging (observability.configure_logging): "json" (default,
    # for log shippers) or "text" (human-readable dev). LOG_LEVEL gates verbosity.
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # Q20 retention: how many most-recent backup sets to keep when an operator
    # runs `python -m backend.gateway.backup snapshot --keep N` (or wires the
    # equivalent cron). Default 168 == one week of hourly snapshots; production
    # streams WAL + keeps 7yr offsite (see ops/DR_RUNBOOK.md). Pruning is opt-in
    # so a bare `snapshot` never deletes anything by surprise.
    BACKUP_RETENTION_KEEP: int = int(os.getenv("BACKUP_RETENTION_KEEP", "168"))
    # Opt-in to the official prometheus_client lib instead of the hand-rolled
    # registry (multiprocess / pushgateway features). Mirrored here for
    # discoverability; metrics.py reads the env var directly at import time.
    METRICS_USE_PROMETHEUS_CLIENT: bool = os.getenv(
        "METRICS_USE_PROMETHEUS_CLIENT", ""
    ).strip().lower() in ("1", "true", "yes")

    # ------------------------------------------------------------------
    # Agent B — Anthropic production-path tuning (Day 12B)
    # ------------------------------------------------------------------
    # These ONLY take effect under LLM_MODE=anthropic. LLM_MODE=mock (the
    # default used by the entire test suite) ignores them, so the suite stays
    # fully offline and deterministic.
    #
    # Per-request wall-clock timeout (seconds) handed to AsyncAnthropic. The
    # SDK default is 600s (10 min) — far too long for a synchronous OA parse: a
    # wedged connection would pin a gateway worker for ten minutes. A real
    # draft_response on Sonnet at 4096 max_tokens completes well under 120s, so
    # 120s is a generous ceiling that still fails fast. On timeout the SDK
    # raises anthropic.APITimeoutError, which our retry loop treats as transient.
    LLM_REQUEST_TIMEOUT_SEC: float = float(os.getenv("LLM_REQUEST_TIMEOUT_SEC", "120"))
    # Our own retry loop owns retry policy, so the SDK's built-in auto-retry is
    # disabled (max_retries=0 at client construction) to avoid retry-on-retry
    # amplification (SDK 2x × our 3 = up to 6 attempts otherwise). This is the
    # number of RETRIES our loop makes on a transient failure
    # (429 / 5xx / overloaded / connection drop / timeout); total attempts =
    # LLM_MAX_RETRIES + 1.
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
    # Exponential-backoff base (seconds): sleep ≈ base * 2**attempt + jitter.
    LLM_RETRY_BASE_SEC: float = float(os.getenv("LLM_RETRY_BASE_SEC", "1.0"))
    # Hard cap on any single backoff sleep so a hostile/huge Retry-After header
    # can't stall a worker for hours.
    LLM_RETRY_MAX_SLEEP_SEC: float = float(os.getenv("LLM_RETRY_MAX_SLEEP_SEC", "60"))
    # Full-jitter ceiling (seconds) added on top of each backoff to de-correlate
    # retries across concurrent workers (AWS "Exponential Backoff and Jitter").
    # Set to 0 to make backoff fully deterministic (used by the retry tests).
    LLM_RETRY_JITTER_SEC: float = float(os.getenv("LLM_RETRY_JITTER_SEC", "1.0"))

    # ------------------------------------------------------------------
    # Agent F — enterprise IdP (OIDC / SAML) hardening (Q12, Day 13F)
    # ------------------------------------------------------------------
    # These flesh out the named `/v1/auth/oidc/callback` + `/v1/auth/saml/acs`
    # stubs into testable, MOCKABLE paths. The identity provider is dependency-
    # injected (backend/gateway/auth.py: OIDCProvider / SAMLProvider protocols),
    # so the test suite verifies a SIGNED ASSERTION offline — no real network
    # to Keycloak / Okta / ADFS. Production swaps the stub provider for a real
    # one (Authlib for OIDC; python3-saml for SAML) WITHOUT touching the
    # callback handlers, which only ever see a validated identity claim.
    #
    # OIDC: the stub provider validates an authorization code by HMAC-verifying
    # a signed code blob (stands in for the real code->token exchange + ID-token
    # signature check against the IdP JWKS). The state/nonce CSRF + replay
    # guards live in the gateway handler and are provider-agnostic.
    OIDC_ENABLED: bool = os.getenv("OIDC_ENABLED", "true").lower() in ("1", "true", "yes")
    OIDC_PROVIDER: str = os.getenv("OIDC_PROVIDER", "stub")  # stub | authlib (prod)
    OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "patentmind-spa")
    OIDC_ISSUER: str = os.getenv("OIDC_ISSUER", "https://idp.example.com")

    # ------------------------------------------------------------------
    # Real Keycloak OIDC (P0 — replaces the stub IdP when selected).
    # ------------------------------------------------------------------
    # OIDC_MODE selects which provider get_oidc_provider() wires:
    #   "stub"     — offline HMAC stub (default; demo + the entire test suite
    #                run WITHOUT docker, behaviour unchanged).
    #   "keycloak" — real Keycloak: /auth/oidc/begin redirects to the realm's
    #                authorize endpoint (auto-discovered via
    #                {issuer}/.well-known/openid-configuration); /auth/oidc/
    #                callback does the code->token exchange, verifies the ID
    #                token signature against the realm JWKS (PyJWT, RS256),
    #                pins iss/aud/exp/nonce, maps realm/client roles + the
    #                tenant claim to our four roles, then issues OUR OWN
    #                gateway session JWT (the Keycloak token is never used as
    #                a gateway token). See backend/gateway/oidc_keycloak.py.
    OIDC_MODE: str = os.getenv("OIDC_MODE", "stub")  # stub | keycloak
    # Realm issuer URL. Discovery doc = {issuer}/.well-known/openid-configuration.
    # docker-compose maps Keycloak to host port 8081 (8080 is Dify-adjacent and
    # 18080 is digiRunner); realm `patentmind` is auto-imported from
    # keycloak/realm-patentmind.json via `start-dev --import-realm`.
    OIDC_KEYCLOAK_ISSUER: str = os.getenv(
        "OIDC_KEYCLOAK_ISSUER", "http://localhost:8081/realms/patentmind"
    )
    # Confidential client registered in the realm (client_secret_post auth at
    # the token endpoint). The compose realm import ships a dev secret; any
    # real deployment MUST rotate it in the Keycloak admin console + env.
    OIDC_KEYCLOAK_CLIENT_ID: str = os.getenv("OIDC_KEYCLOAK_CLIENT_ID", "patentmind-gateway")
    OIDC_KEYCLOAK_CLIENT_SECRET: str = os.getenv("OIDC_KEYCLOAK_CLIENT_SECRET", "")
    # redirect_uri sent in the authorize request AND the token exchange (must
    # match a registered redirect URI on the client, and must be byte-identical
    # in both legs or Keycloak rejects the exchange).
    OIDC_REDIRECT_URI: str = os.getenv(
        "OIDC_REDIRECT_URI", "http://localhost:5173/auth/oidc/callback"
    )
    # Wall-clock timeout for discovery / token / JWKS HTTP calls.
    OIDC_HTTP_TIMEOUT_SEC: float = float(os.getenv("OIDC_HTTP_TIMEOUT_SEC", "10"))
    # Claim names the role/tenant mapper reads from the ID token. A flat
    # `role` claim (protocol mapper) wins; otherwise client roles under
    # resource_access.<client>.roles, then realm_access.roles. Tenant comes
    # from a user-attribute protocol mapper (fallback claim name: "tenant").
    OIDC_ROLE_CLAIM: str = os.getenv("OIDC_ROLE_CLAIM", "role")
    OIDC_TENANT_CLAIM: str = os.getenv("OIDC_TENANT_CLAIM", "tenant_id")
    # Shared secret the stub OIDC provider HMAC-signs its code blobs with. In
    # production this is replaced by the IdP's published JWKS public key — the
    # stub uses a symmetric secret only so the suite needs no key material.
    OIDC_STUB_SIGNING_SECRET: str = os.getenv(
        "OIDC_STUB_SIGNING_SECRET", "oidc-stub-shared-secret-do-not-ship"
    )
    # TTL (seconds) of the server-issued `state` value that ties an OIDC
    # callback back to the browser that began the flow (CSRF defence). Short
    # because the round-trip through the IdP login page is interactive.
    OIDC_STATE_TTL_SEC: int = int(os.getenv("OIDC_STATE_TTL_SEC", "600"))

    # SAML: the stub provider validates an HMAC-signed assertion blob (stands in
    # for the real XML-DSig signature check). Replay protection keys on the
    # assertion ID (single-use, TTL-bounded) and the NotOnOrAfter window.
    SAML_ENABLED: bool = os.getenv("SAML_ENABLED", "true").lower() in ("1", "true", "yes")
    SAML_PROVIDER: str = os.getenv("SAML_PROVIDER", "stub")  # stub | python3-saml (prod)
    SAML_AUDIENCE: str = os.getenv("SAML_AUDIENCE", "patentmind-sp")
    SAML_STUB_SIGNING_SECRET: str = os.getenv(
        "SAML_STUB_SIGNING_SECRET", "saml-stub-shared-secret-do-not-ship"
    )
    # How long a consumed SAML assertion ID is remembered for replay defence.
    # Must exceed the assertion's own NotOnOrAfter window so a captured
    # assertion can't be replayed after its single-use record would have been
    # pruned but while the assertion is still inside its validity window.
    SAML_REPLAY_TTL_SEC: int = int(os.getenv("SAML_REPLAY_TTL_SEC", "600"))
    # Clock-skew tolerance (seconds) applied to both OIDC and SAML time-window
    # checks so a few seconds of NTP drift between the IdP and the gateway does
    # not reject an otherwise-valid assertion.
    IDP_CLOCK_SKEW_SEC: int = int(os.getenv("IDP_CLOCK_SKEW_SEC", "30"))
    # ------------------------------------------------------------------
    # Agent H — RAG retrieval-quality eval gate (Q6/Q7, Day 13H)
    # ------------------------------------------------------------------
    # Production quality targets for the retrieval-eval harness
    # (backend/ai_engine/retrieval_eval.py). These ONLY bite once
    # EMBEDDING_BACKEND=bge-m3 — on the mock backend embeddings are
    # deterministic SHA-256 noise so the numbers are meaningless (the harness
    # documents this loudly). retrieval_eval.py keeps its own module-level
    # DEFAULT_MIN_RECALL_AT_5 (low mock floor) + PROD_TARGET_RECALL_AT_5 (0.70,
    # the Q6 number); these mirror the prod targets here so an operator flipping
    # to bge-m3 can ratchet the CI gate from one place. nDCG / grounding-coverage
    # targets are advisory until a real embedder makes them informative.
    RAG_EVAL_TARGET_RECALL_AT_5: float = float(os.getenv("RAG_EVAL_TARGET_RECALL_AT_5", "0.70"))
    RAG_EVAL_TARGET_NDCG_AT_5: float = float(os.getenv("RAG_EVAL_TARGET_NDCG_AT_5", "0.60"))
    RAG_EVAL_TARGET_COVERAGE_AT_5: float = float(os.getenv("RAG_EVAL_TARGET_COVERAGE_AT_5", "0.40"))
    # ------------------------------------------------------------------
    # Agent I — Q18 rate-limit / quota atomicity + Q9 cache hardening (Day 13I)
    # ------------------------------------------------------------------
    # Which counter backend the quota / cost-breaker accounting uses. `memory`
    # (default) is a lock-protected in-process store — correct for a single
    # gateway replica and the entire test suite, but counters are NOT shared
    # across replicas. `redis` uses atomic INCR + Lua EVAL so a horizontally
    # scaled gateway fleet shares one source of truth and concurrent requests
    # cannot oversell a quota (the check-and-increment is a single atomic op).
    RATE_LIMIT_BACKEND: str = os.getenv("RATE_LIMIT_BACKEND", "memory")  # memory | redis
    # Degrade policy when the rate-limit Redis is unreachable. Quota / cost
    # accounting is a SAFETY control (it protects spend + fair-use), so the
    # safe default is FAIL-CLOSED: if we cannot atomically reserve quota we
    # reject (429) rather than let an unbounded request through. Set to "open"
    # ONLY if availability is valued over spend protection for your contract.
    #   "closed" (default) — Redis down ⇒ 429 (protect the budget).
    #   "open"             — Redis down ⇒ allow (protect availability).
    # NB: the CACHE path is the opposite (fail-OPEN) — a cache outage must
    # never 503 a request; it just means "no cache for that request". The two
    # controls have different safe defaults on purpose (see redis_cache.py).
    RATE_LIMIT_REDIS_DEGRADE: str = os.getenv("RATE_LIMIT_REDIS_DEGRADE", "closed")  # closed | open
    # ------------------------------------------------------------------
    # Agent J — PDF / OCR ingestion robustness (Q8, Day 13J)
    # ------------------------------------------------------------------
    # Additive-only knobs for the hardened pdf_parser ingest path. All have
    # safe defaults so existing callers are unaffected.
    #
    # Hard ceiling on PDF page count. Beyond MAX_PDF_PAGES we refuse the doc
    # outright (ValueError) rather than silently truncate — a 5000-page PDF is
    # almost always a malformed/zip-bomb-style payload, and silently dropping
    # pages in a legal workflow loses evidence. The per-call `max_pages`
    # argument still governs *truncation-with-warning* for normal large docs;
    # this is the absolute upper bound that no caller may exceed.
    MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "2000"))
    # A page that fell back to OCR but came back with fewer than this many
    # characters is flagged as a probable bad/blank scan via a per-page quality
    # warning, so a downstream caller can prompt the attorney to re-scan. This
    # does NOT fail the upload — it only surfaces a signal.
    OCR_LOW_TEXT_WARN_CHARS: int = int(os.getenv("OCR_LOW_TEXT_WARN_CHARS", "8"))
    # Fraction (0..1) of pages allowed to be OCR'd before the whole document is
    # flagged "likely a scanned document — extraction quality may be degraded".
    # Purely advisory; surfaced in warnings.
    OCR_SCANNED_DOC_WARN_RATIO: float = float(os.getenv("OCR_SCANNED_DOC_WARN_RATIO", "0.5"))


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
# Asymmetric mode (RS*/ES*/PS*) doesn't use JWT_SECRET — it needs a key PAIR.
# Refuse to boot if asymmetric is selected without both PEM keys.
if (
    "PYTEST_CURRENT_TEST" not in os.environ
    and not settings.JWT_ALGO.startswith("HS")
    and not (settings.JWT_PRIVATE_KEY and settings.JWT_PUBLIC_KEY)
):
    raise RuntimeError(
        f"JWT_ALGO={settings.JWT_ALGO} is asymmetric but JWT_PRIVATE_KEY / "
        "JWT_PUBLIC_KEY are not both set. Provide a PEM key pair, or use HS256."
    )
if (
    "PYTEST_CURRENT_TEST" not in os.environ
    and settings.JWT_ALGO.startswith("HS")
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


# --- Boot-time guardrail: stub IdP providers outside mock/test (review P2-5) -
# The stub OIDC/SAML providers HMAC-verify against secrets whose DEFAULTS are
# published in this file ("...-do-not-ship"). With OIDC_PROVIDER=stub and the
# default secret, anyone can mint a valid authorization code. Same posture as
# the JWT-placeholder guard: refuse the deployment shape, allow mock/test.
def _validate_stub_idp_config() -> None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return  # test fixtures exercise the stub providers by design
    if settings.LLM_MODE == "mock":
        return  # POC / demo mode -- IdP login is not the demo's front door
    problems = []
    if (
        settings.OIDC_ENABLED
        and settings.OIDC_MODE == "stub"
        and settings.OIDC_PROVIDER == "stub"
        and settings.OIDC_STUB_SIGNING_SECRET == "oidc-stub-shared-secret-do-not-ship"
    ):
        problems.append("OIDC_PROVIDER=stub with the published default OIDC_STUB_SIGNING_SECRET")
    if (
        settings.OIDC_ENABLED
        and settings.OIDC_MODE == "keycloak"
        and not settings.OIDC_KEYCLOAK_CLIENT_SECRET
    ):
        # A confidential client without its secret can never complete the
        # code->token exchange — every OIDC login would 401 with a server-side
        # log nobody reads until a user complains. Fail at boot instead.
        problems.append("OIDC_MODE=keycloak with an empty OIDC_KEYCLOAK_CLIENT_SECRET")
    if (
        settings.SAML_ENABLED
        and settings.SAML_PROVIDER == "stub"
        and settings.SAML_STUB_SIGNING_SECRET == "saml-stub-shared-secret-do-not-ship"
    ):
        problems.append("SAML_PROVIDER=stub with the published default SAML_STUB_SIGNING_SECRET")
    if problems:
        raise RuntimeError(
            "Refusing to boot outside mock/test mode: " + "; ".join(problems) + ". "
            "Anyone who reads the public repo can mint valid IdP assertions. "
            "Either disable the stub (OIDC_ENABLED=false / SAML_ENABLED=false), "
            "switch to a real provider, or set a private stub secret for staging."
        )


_validate_stub_idp_config()


# ---------------------------------------------------------------------------
# Agent G — audit-chain integrity / WORM archive / outbox durability tunables
# (Q13). Additive only; consumed by backend/gateway/audit_archive.py and
# backend/gateway/audit_outbox.py. Module-level constants (not Settings fields)
# to mirror AUDIT_DB_PATH / AUDIT_OUTBOX_PATH / AUDIT_ARCHIVE_DIR above and to
# stay honoured by conftest/test monkeypatching of this module.
# ---------------------------------------------------------------------------
# Ops alert threshold: when outbox_depth() exceeds this, the primary audit DB
# has been unhappy long enough that a human should look. Surfaced by health/
# metrics wiring (deferred — see report). 0 disables the alert.
AUDIT_OUTBOX_ALERT_DEPTH = int(os.getenv("AUDIT_OUTBOX_ALERT_DEPTH", "100"))
# WORM retention the production S3 Object Lock policy should enforce on each
# sealed segment. The POC chmods files read-only; this records the intended
# retention so the cron/archiver wiring can set the real Object Lock period.
AUDIT_WORM_RETENTION_DAYS = int(os.getenv("AUDIT_WORM_RETENTION_DAYS", str(7 * 365)))
