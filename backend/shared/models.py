"""Shared Pydantic models — the contract between Gateway and AI Engine.

Q1 / Q2: This file defines the API surface that both digiRunner mock and Dify mock
agree on. Keeping it shared lets you swap either side without touching the other.

Security Chunk C — H-2
-----------------------
Every BaseModel in this file uses `extra="forbid"` so an unknown field
triggers a 422 instead of being silently dropped. String fields carry
`max_length` caps so a multi-MB blob can't smuggle past the body-size
middleware (which uses Content-Length) and into the hash-chained audit
log. Pick caps based on a generous upper bound for realistic patent-prosecution
content — they're not tight; they just have to be SOMETHING below ∞.

The `model_used` field on AuditEntry collides with Pydantic v2's protected
`model_` namespace, so AuditEntry (and any future model carrying a
`model_*` field) sets `protected_namespaces=()` in addition to
`extra="forbid"`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# Cap matching `settings.MAX_BODY_BYTES` / Pydantic v2 default validation
# semantics. 5MB of OA text is ~1M tokens — far above any real OA document
# (typical: 5-30 pages, ~25k chars) but well below the body-size middleware
# cap. Picked as a defence-in-depth tier between "Content-Length too large"
# (413) and "field too long" (422).
_MAX_OA_TEXT_CHARS = 5 * 1024 * 1024


# ---------- Auth / User ----------

class UserRole(str, Enum):
    ATTORNEY = "attorney"        # 律師：可上傳 OA、看分析、簽核
    PARALEGAL = "paralegal"      # 法務助理：協助上傳、查詢
    IT_ADMIN = "it_admin"        # 客戶 IT：管理 connector、看儀表板
    AUDITOR = "auditor"          # 合規：唯讀 audit log


class User(BaseModel):
    # `extra="forbid"` here closes a subtle issue: this model is round-tripped
    # through dict() / model_dump() inside the JWT path and the audit row
    # serialisation; an attacker who could smuggle extra fields would pollute
    # downstream consumers. forbid + the per-field caps below means a
    # forged `User` dict with a 1GB `display_name` is rejected at parse time.
    model_config = {"extra": "forbid"}

    user_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=64)  # Q5: tenant 隔離
    role: UserRole
    display_name: str = Field(..., max_length=256)
    daily_token_quota: int = 100_000  # Q18


# ---------- OA Document ----------

class RejectionType(str, Enum):
    """USPTO 駁回類型；台灣 TIPO 大致對應。"""
    NOVELTY_102 = "102_novelty"               # 新穎性 (US §102 / TW §22-1)
    OBVIOUSNESS_103 = "103_obviousness"       # 進步性 / 非顯而易見 (US §103 / TW §22-2)
    INDEFINITENESS_112 = "112_indefiniteness" # 明確性 (US §112(b) / TW §26-2 之一般情形)
    ANTECEDENT_BASIS = "antecedent_basis"     # 缺先行詞 (TW §26-2 / US §112(b) 之 antecedent basis 子類)
    SUBJECT_MATTER_101 = "101_subject_matter" # 適格性
    DOUBLE_PATENTING = "double_patenting"
    OTHER = "other"


class Rejection(BaseModel):
    model_config = {"extra": "forbid"}

    rejection_id: str = Field(..., max_length=128)
    rejection_type: RejectionType
    affected_claims: list[int]
    cited_prior_art: list[str]  # patent numbers
    examiner_argument: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)  # 審查官論點摘要 (已 redact)
    confidence: float            # AI 解析的信心度 0-1


class OADocument(BaseModel):
    model_config = {"extra": "forbid"}

    oa_id: str = Field(..., max_length=128)
    case_id: str = Field(..., max_length=256)
    tenant_id: str = Field(..., max_length=64)
    received_date: datetime      # Q17: 期日計算起算
    deadline: datetime           # Q17: 答辯截止
    raw_text_hash: str = Field(..., max_length=128)  # SHA-256，原文不上雲
    rejections: list[Rejection] = []


# ---------- Patent / Prior Art ----------

class Patent(BaseModel):
    # NOT extra=forbid: external patent feeds (USPTO XML, TIPO API) carry
    # provider-specific extra metadata that we tolerate-and-ignore at ingest.
    # Length caps still bound the per-field blast radius.
    patent_no: str = Field(..., max_length=64)
    title: str = Field(..., max_length=2048)
    abstract: str = Field(..., max_length=32_768)
    claims: list[str]
    publication_date: datetime
    jurisdiction: str = Field(..., max_length=8)  # US, EP, TW, JP, CN, ...
    is_local: bool     # True = on-prem 客戶內部專利, False = 公開引證案


class RetrievalHit(BaseModel):
    """RAG retrieval 結果。Q6 / Q14：每個 hit 都要能對回原文。"""
    model_config = {"extra": "forbid"}

    patent_no: str = Field(..., max_length=64)
    section: str = Field(..., max_length=128)  # "claim_1", "spec_para_3", ...
    text: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)
    score: float
    metadata: dict[str, Any] = {}


# ---------- Analysis Request / Response ----------

class AnalysisRequest(BaseModel):
    """前端 → Gateway → AI Engine 的請求.

    `extra="forbid"` plus per-field caps closes H-2 (no body size cap,
    `oa_text` unbounded). The MaxBodySizeMiddleware in `backend/gateway/main.py`
    catches gigabyte-scale bodies before they reach Pydantic; these caps catch
    "small body, huge field" abuse where the Content-Length header is honest
    but one specific string is sized to OOM downstream consumers (e.g. the
    audit hash chain, the LLM tokeniser, the cache key hasher).
    """
    model_config = {"extra": "forbid"}

    oa_text: str = Field(
        ..., max_length=_MAX_OA_TEXT_CHARS,
        description="OA 全文，會在 Gateway 被 redact",
    )
    case_id: str = Field(..., max_length=256)
    target_patent_no: str = Field(..., max_length=64)  # 被 OA 的本案專利號
    user_hint: Optional[str] = Field(default=None, max_length=8000)  # 律師補充說明


class DraftResponse(BaseModel):
    """AI Engine 對單一 rejection 的答辯草稿。Q14 / Q16。"""
    model_config = {"extra": "forbid"}

    rejection_id: str = Field(..., max_length=128)
    strategy: str = Field(..., max_length=8192)               # 答辯策略摘要
    draft_text: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)  # 答辯文字草稿
    grounded_citations: list[str]       # 引用的法條 / prior art，必須在 retrieval set 中
    confidence: float
    requires_attorney_review: bool = True  # Q16: 永遠 True


class AnalysisResponse(BaseModel):
    # NOT extra=forbid: AI Engine responses are versioned; we want to tolerate
    # the engine sending NEW fields (forward compatibility) while still
    # rejecting client-supplied request shapes.
    request_id: str = Field(..., max_length=128)
    oa: OADocument
    drafts: list[DraftResponse]
    related_prior_art: list[RetrievalHit]
    deadline_summary: "DeadlineInfo"
    cost_meta: "CostMeta"


# ---------- Deadline (Q17) ----------

class DeadlineInfo(BaseModel):
    model_config = {"extra": "forbid"}

    received_date: datetime
    statutory_deadline: datetime         # 法定期日（含可延展前）
    recommended_internal_deadline: datetime  # 內部建議完成日（早 7 天）
    days_remaining: int
    holiday_calendar_version: str = Field(..., max_length=32)  # Q17: 假日表版本
    warnings: list[str] = []


# ---------- Cost / Token (Q18) ----------

class CostMeta(BaseModel):
    model_config = {"protected_namespaces": (), "extra": "forbid"}

    prompt_tokens: int
    completion_tokens: int
    model: str = Field(..., max_length=128)
    estimated_cost_usd: float
    cache_hit: bool = False


# ---------- Audit (Q13) ----------

class AuditEntry(BaseModel):
    # `model_used` collides with Pydantic v2's protected `model_` namespace;
    # disabling the protected-namespace check silences the import-time
    # warning that 89-test baseline was emitting. `extra="forbid"` keeps the
    # invariant from the AuditAppendRequest schema (no forged columns).
    model_config = {"protected_namespaces": (), "extra": "forbid"}

    audit_id: str = Field(..., max_length=128)
    timestamp_utc: datetime
    timestamp_local: datetime
    user_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=64)
    case_id: Optional[str] = Field(default=None, max_length=256)
    endpoint: str = Field(..., max_length=256)
    request_hash: str = Field(..., max_length=128)               # SHA-256 of request body
    response_hash: str = Field(..., max_length=128)              # SHA-256 of response
    masked_field_rules: list[str]   # 哪些 mask 規則被觸發 (rule id, 不存內容)
    model_used: Optional[str] = Field(default=None, max_length=128)
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    latency_ms: int
    policy_decisions: dict[str, bool]  # {"rate_limit_passed": True, "authz_passed": True}


# resolve forward refs
AnalysisResponse.model_rebuild()
