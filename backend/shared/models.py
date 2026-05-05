"""Shared Pydantic models — the contract between Gateway and AI Engine.

Q1 / Q2: This file defines the API surface that both digiRunner mock and Dify mock
agree on. Keeping it shared lets you swap either side without touching the other.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- Auth / User ----------

class UserRole(str, Enum):
    ATTORNEY = "attorney"        # 律師：可上傳 OA、看分析、簽核
    PARALEGAL = "paralegal"      # 法務助理：協助上傳、查詢
    IT_ADMIN = "it_admin"        # 客戶 IT：管理 connector、看儀表板
    AUDITOR = "auditor"          # 合規：唯讀 audit log


class User(BaseModel):
    user_id: str
    tenant_id: str  # Q5: tenant 隔離
    role: UserRole
    display_name: str
    daily_token_quota: int = 100_000  # Q18


# ---------- OA Document ----------

class RejectionType(str, Enum):
    """USPTO 駁回類型；台灣 TIPO 大致對應。"""
    NOVELTY_102 = "102_novelty"               # 新穎性
    OBVIOUSNESS_103 = "103_obviousness"       # 進步性 / 非顯而易見
    INDEFINITENESS_112 = "112_indefiniteness" # 明確性
    SUBJECT_MATTER_101 = "101_subject_matter" # 適格性
    DOUBLE_PATENTING = "double_patenting"
    OTHER = "other"


class Rejection(BaseModel):
    rejection_id: str
    rejection_type: RejectionType
    affected_claims: list[int]
    cited_prior_art: list[str]  # patent numbers
    examiner_argument: str       # 審查官論點摘要 (已 redact)
    confidence: float            # AI 解析的信心度 0-1


class OADocument(BaseModel):
    oa_id: str
    case_id: str
    tenant_id: str
    received_date: datetime      # Q17: 期日計算起算
    deadline: datetime           # Q17: 答辯截止
    raw_text_hash: str           # SHA-256，原文不上雲
    rejections: list[Rejection] = []


# ---------- Patent / Prior Art ----------

class Patent(BaseModel):
    patent_no: str
    title: str
    abstract: str
    claims: list[str]
    publication_date: datetime
    jurisdiction: str  # US, EP, TW, JP, CN, ...
    is_local: bool     # True = on-prem 客戶內部專利, False = 公開引證案


class RetrievalHit(BaseModel):
    """RAG retrieval 結果。Q6 / Q14：每個 hit 都要能對回原文。"""
    patent_no: str
    section: str         # "claim_1", "spec_para_3", ...
    text: str
    score: float
    metadata: dict[str, Any] = {}


# ---------- Analysis Request / Response ----------

class AnalysisRequest(BaseModel):
    """前端 → Gateway → AI Engine 的請求。"""
    oa_text: str = Field(..., description="OA 全文，會在 Gateway 被 redact")
    case_id: str
    target_patent_no: str  # 被 OA 的本案專利號
    user_hint: Optional[str] = None  # 律師補充說明


class DraftResponse(BaseModel):
    """AI Engine 對單一 rejection 的答辯草稿。Q14 / Q16。"""
    rejection_id: str
    strategy: str                       # 答辯策略摘要
    draft_text: str                     # 答辯文字草稿
    grounded_citations: list[str]       # 引用的法條 / prior art，必須在 retrieval set 中
    confidence: float
    requires_attorney_review: bool = True  # Q16: 永遠 True


class AnalysisResponse(BaseModel):
    request_id: str
    oa: OADocument
    drafts: list[DraftResponse]
    related_prior_art: list[RetrievalHit]
    deadline_summary: "DeadlineInfo"
    cost_meta: "CostMeta"


# ---------- Deadline (Q17) ----------

class DeadlineInfo(BaseModel):
    received_date: datetime
    statutory_deadline: datetime         # 法定期日（含可延展前）
    recommended_internal_deadline: datetime  # 內部建議完成日（早 7 天）
    days_remaining: int
    holiday_calendar_version: str         # Q17: 假日表版本，重算時用同版本
    warnings: list[str] = []


# ---------- Cost / Token (Q18) ----------

class CostMeta(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    model: str
    estimated_cost_usd: float
    cache_hit: bool = False


# ---------- Audit (Q13) ----------

class AuditEntry(BaseModel):
    audit_id: str
    timestamp_utc: datetime
    timestamp_local: datetime
    user_id: str
    tenant_id: str
    case_id: Optional[str]
    endpoint: str
    request_hash: str               # SHA-256 of request body
    response_hash: str              # SHA-256 of response
    masked_field_rules: list[str]   # 哪些 mask 規則被觸發 (rule id, 不存內容)
    model_used: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    latency_ms: int
    policy_decisions: dict[str, bool]  # {"rate_limit_passed": True, "authz_passed": True}


# resolve forward refs
AnalysisResponse.model_rebuild()
