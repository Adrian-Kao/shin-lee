"""Centralised settings. Every magic number lives here.

各設定後面標 (Qxx) 對應 docs/DECISIONS.md
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PATENT_DB_PATH = DATA_DIR / "patentmind.db"
AUDIT_DB_PATH = DATA_DIR / "audit.db"
MAPPING_DB_PATH = DATA_DIR / "redaction_mapping.db"  # Q10: 不上雲的 mapping table


class Settings:
    # Service ports
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8010"))
    AI_ENGINE_PORT: int = int(os.getenv("AI_ENGINE_PORT", "8011"))
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://localhost:8010")
    AI_ENGINE_URL: str = os.getenv("AI_ENGINE_URL", "http://localhost:8011")

    # Auth (Q12)
    JWT_SECRET: str = os.getenv("JWT_SECRET", "poc-secret-do-not-use-in-prod-32bytes!!")
    JWT_ALGO: str = "HS256"
    JWT_EXPIRES_MIN: int = 30

    # Rate limit / Quota (Q18 全套)
    DEFAULT_RPM: int = 30                   # per-user request/minute
    DEFAULT_DAILY_TOKENS: int = 100_000     # per-user daily token quota
    TENANT_MONTHLY_TOKENS: int = 50_000_000 # per-tenant monthly cap
    REQUEST_HARD_LIMIT_TOKENS: int = 32_000 # single prompt hard cap
    COST_CIRCUIT_DAILY_USD: float = 100.0   # 日成本斷路器閾值（POC 用低值方便測）

    # LLM router (Q15 多模型 + 機密走地端)
    LLM_MODE: str = os.getenv("LLM_MODE", "mock")  # mock | openai | anthropic | local
    LLM_MODEL_REASONING: str = os.getenv("LLM_MODEL_REASONING", "claude-sonnet-mock")
    LLM_MODEL_CHEAP: str = os.getenv("LLM_MODEL_CHEAP", "haiku-mock")
    LLM_MODEL_LOCAL: str = os.getenv("LLM_MODEL_LOCAL", "llama3.1:8b")
    LLM_MODEL_VERIFIER: str = os.getenv("LLM_MODEL_VERIFIER", "haiku-mock")  # Q14
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

    # Embedding (Q5/Q7 — POC 預設 mock；切 bge-m3 用 SentenceTransformer)
    EMBEDDING_BACKEND: str = os.getenv("EMBEDDING_BACKEND", "mock")  # mock | bge-m3
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    # Holiday calendar (Q17)
    HOLIDAY_CALENDAR_VERSION: str = "2025.1"
    SUPPORTED_JURISDICTIONS: tuple[str, ...] = ("TW", "US")  # 其他國家留 stub

    # Tenants（POC 預設兩家事務所做 demo）
    DEMO_TENANTS: dict[str, dict] = {
        "tenant_a": {"name": "Apex Patent Law Firm", "monthly_token_cap": 50_000_000},
        "tenant_b": {"name": "BetaLegal IP Group", "monthly_token_cap": 50_000_000},
    }

    # Security level mapping (Q15 router)
    LOCAL_LLM_FOR_SECURITY_LEVELS: tuple[str, ...] = ("confidential", "top_secret")


settings = Settings()
