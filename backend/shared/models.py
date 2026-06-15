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
from typing import Any, Literal

from pydantic import BaseModel, Field

# Cap matching `settings.MAX_BODY_BYTES` / Pydantic v2 default validation
# semantics. 5MB of OA text is ~1M tokens — far above any real OA document
# (typical: 5-30 pages, ~25k chars) but well below the body-size middleware
# cap. Picked as a defence-in-depth tier between "Content-Length too large"
# (413) and "field too long" (422).
_MAX_OA_TEXT_CHARS = 5 * 1024 * 1024


# ---------- Auth / User ----------


class UserRole(str, Enum):
    ATTORNEY = "attorney"  # 律師：可上傳 OA、看分析、簽核
    PARALEGAL = "paralegal"  # 法務助理：協助上傳、查詢
    IT_ADMIN = "it_admin"  # 客戶 IT：管理 connector、看儀表板
    AUDITOR = "auditor"  # 合規：唯讀 audit log


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

    NOVELTY_102 = "102_novelty"  # 新穎性 (US §102 / TW §22-1)
    OBVIOUSNESS_103 = "103_obviousness"  # 進步性 / 非顯而易見 (US §103 / TW §22-2)
    INDEFINITENESS_112 = "112_indefiniteness"  # 明確性 (US §112(b) / TW §26-2 之一般情形)
    ANTECEDENT_BASIS = (
        "antecedent_basis"  # 缺先行詞 (TW §26-2 / US §112(b) 之 antecedent basis 子類)
    )
    SUBJECT_MATTER_101 = "101_subject_matter"  # 適格性
    DOUBLE_PATENTING = "double_patenting"
    OTHER = "other"


class Rejection(BaseModel):
    model_config = {"extra": "forbid"}

    rejection_id: str = Field(..., max_length=128)
    rejection_type: RejectionType
    affected_claims: list[int]
    cited_prior_art: list[str]  # patent numbers
    examiner_argument: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)  # 審查官論點摘要 (已 redact)
    confidence: float  # AI 解析的信心度 0-1


class OADocument(BaseModel):
    model_config = {"extra": "forbid"}

    oa_id: str = Field(..., max_length=128)
    case_id: str = Field(..., max_length=256)
    tenant_id: str = Field(..., max_length=64)
    received_date: datetime  # Q17: 期日計算起算
    deadline: datetime  # Q17: 答辯截止
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
    is_local: bool  # True = on-prem 客戶內部專利, False = 公開引證案


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
        ...,
        max_length=_MAX_OA_TEXT_CHARS,
        description="OA 全文，會在 Gateway 被 redact",
    )
    case_id: str = Field(..., max_length=256)
    target_patent_no: str = Field(..., max_length=64)  # 被 OA 的本案專利號
    filing_date: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "本案申請/優先權日 (ISO-8601, e.g. '2024-03-01')。提供時，前案檢索硬性排除"
            "publication_date 晚於此日的引證 (專利法 §22/§23：前案須早於申請日)。"
            "省略則不做日期過濾 (向後相容)。"
        ),
    )
    user_hint: str | None = Field(default=None, max_length=8000)  # 律師補充說明


class DraftResponse(BaseModel):
    """AI Engine 對單一 rejection 的答辯草稿。Q14 / Q16。"""

    model_config = {"extra": "forbid"}

    rejection_id: str = Field(..., max_length=128)
    strategy: str = Field(..., max_length=8192)  # 答辯策略摘要
    draft_text: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)  # 答辯文字草稿
    grounded_citations: list[str]  # 引用的法條 / prior art，必須在 retrieval set 中
    confidence: float
    requires_attorney_review: bool = True  # Q16: 永遠 True

    # ---- Q14 verifier transparency ----
    # Populated by the gateway orchestrator AFTER the verifier (Q14 layer 3)
    # runs; the defaults keep the AI-engine draft constructor and the degraded
    # placeholder valid (they have no verifier output yet). These surface the
    # "hallucination wall" to the front-end so the attorney can SEE what the
    # verifier stripped and how confident the (separate) verifier model was —
    # instead of only an anonymous [CITATION_REMOVED] marker in draft_text.
    invalid_citations: list[str] = Field(default_factory=list)  # citations stripped by the verifier
    verifier_confidence: float | None = (
        None  # standalone verifier confidence (≠ folded `confidence`)
    )
    verifier_model: str | None = None  # which model performed verification


# ---------- Q16 — Provenance / human-in-the-loop sign-off ----------

# Provenance source labels. These ARE the responsibility boundary (責任界線)
# the Q16 decision requires: every exported sentence is tagged with who is
# accountable for it.
#   ai_generated     — produced by the AI Engine draft, accepted verbatim by
#                      the reviewer (AI is the author; the human accepted).
#   attorney_edited  — an AI sentence the ATTORNEY rewrote (shared authorship;
#                      the EDIT is the feedback signal Q16 wants mined later).
#   attorney_added   — a sentence the ATTORNEY wrote from scratch.
#   paralegal_edited — an AI sentence a PARALEGAL rewrote while preparing the
#                      draft for attorney sign-off (multi-person responsibility
#                      chain: paralegal drafts → attorney reviews/signs).
#   paralegal_added  — a sentence a PARALEGAL wrote from scratch.
# The paralegal_* variants make the human contribution visible PER ROLE so the
# exported document's responsibility boundary distinguishes "王(助理)擬稿 →
# 林(律師)改寫 → 陳(合夥人)簽核" rather than collapsing all human edits to
# "attorney". The attorney still owns final sign-off (the export gate).
ProvenanceSource = Literal[
    "ai_generated",
    "attorney_edited",
    "attorney_added",
    "paralegal_edited",
    "paralegal_added",
]


class ProvenanceSegment(BaseModel):
    """One sentence/paragraph of a draft, tagged with its authorship.

    Q16 requires the system to record "哪些段落是 AI 生成、哪些是律師改寫"
    (the responsibility boundary). The FRONT-END tracks per-sentence edits in
    the DraftEditor and supplies the segments at EXPORT time — they are NOT
    regenerated by the AI. `accepted=False` segments are excluded from the
    assembled document (the attorney rejected that sentence outright).
    """

    model_config = {"extra": "forbid"}

    segment_id: str = Field(..., max_length=128)
    text: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)
    source: ProvenanceSource
    accepted: bool = True


class ExportRequest(BaseModel):
    """Body for POST /v1/oa/export — the mandatory-sign-off export gate (Q16).

    `attorney_signoff` is the enforced checkbox ("我已逐項確認"): the gateway
    refuses to assemble any document unless it is exactly ``True``. The
    `segments` carry the per-sentence provenance the attorney curated in the
    DraftEditor; the gateway concatenates the accepted ones into the final
    document and records the provenance SUMMARY (counts only) in the audit row.

    `rejection_id` ties the export back to the specific OA rejection the draft
    answered; `draft_set_id` is an optional handle for a multi-rejection bundle.
    At least one of the two should be supplied so the audit trail can correlate
    the export with the analysis that produced it (not enforced as a hard
    constraint to keep older callers working).
    """

    model_config = {"extra": "forbid"}

    case_id: str = Field(..., max_length=256)
    rejection_id: str | None = Field(default=None, max_length=128)
    draft_set_id: str | None = Field(default=None, max_length=128)
    # Cap the segment count so a hostile body can't push thousands of
    # max-sized segments through the assembler / hasher.
    segments: list[ProvenanceSegment] = Field(..., max_length=10_000)
    attorney_signoff: bool = False


class ProvenanceSummary(BaseModel):
    """Aggregate provenance counts — the responsibility boundary, distilled.

    These counts (NOT the raw text) are what lands in the audit row. The
    ``attorney_edited`` + ``attorney_added`` counts are also the lightweight
    feedback signal Q16 asks for: a future loop can mine exports with high
    edit ratios to find where the AI draft is weakest, without needing a full
    training pipeline today.
    """

    model_config = {"extra": "forbid"}

    total_segments: int = 0
    accepted_segments: int = 0
    ai_generated: int = 0
    attorney_edited: int = 0
    attorney_added: int = 0
    paralegal_edited: int = 0
    paralegal_added: int = 0


class ExportResponse(BaseModel):
    """Result of a successful POST /v1/oa/export.

    `document` is the assembled draft (accepted segments concatenated). It is
    returned to the caller but NEVER stored raw in the audit log — only its
    SHA-256 (`content_sha256`) and the provenance summary are persisted.
    """

    model_config = {"extra": "forbid"}

    case_id: str = Field(..., max_length=256)
    rejection_id: str | None = Field(default=None, max_length=128)
    draft_set_id: str | None = Field(default=None, max_length=128)
    document: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)
    content_sha256: str = Field(..., max_length=64)
    provenance_summary: ProvenanceSummary
    signed_off_by: str = Field(..., max_length=64)
    attorney_signoff: bool


class ClaimNode(BaseModel):
    """One node in the claim dependency tree (UX_RESEARCH §4.1 / §5 #2).

    Produced by `backend.ai_engine.claim_tree.parse_claim_dependencies`. The
    front-end ClaimTree component renders these as a vertical tree, colored
    by rejection status. `depends_on` is the FIRST parent for tree layout;
    `parents` carries all parents for multi-parent claims so the UI can
    surface cascade-risk highlighting when an independent claim is rejected.
    """

    model_config = {"extra": "forbid"}

    claim_no: int
    depends_on: int | None = None
    parents: list[int] = Field(default_factory=list)
    text: str = Field(..., max_length=_MAX_OA_TEXT_CHARS)
    is_independent: bool
    depth: int = 0


class RedactionSummary(BaseModel):
    """Day 9C — CHUNK-8 trust band feed.

    Aggregate count of PII / customer-dictionary entities that the gateway
    redacted from the OA before any text left on-prem. Surfaced to the SPA
    so the trust band can show `Redaction: N entities masked` instead of
    a generic "redaction active" badge — gives the attorney evidence the
    invariant fired on THEIR document, not just in the abstract.

    `rules_triggered` lists the rule ids only (e.g. ``email``, ``tw_phone``)
    — never the matched values. CLAUDE.md invariant #3 forbids the
    matched content from leaving the gateway.
    """

    model_config = {"extra": "forbid"}

    masked_entity_count: int = 0
    rules_triggered: list[str] = Field(default_factory=list, max_length=128)


class AnalysisResponse(BaseModel):
    # NOT extra=forbid: AI Engine responses are versioned; we want to tolerate
    # the engine sending NEW fields (forward compatibility) while still
    # rejecting client-supplied request shapes.
    request_id: str = Field(..., max_length=128)
    oa: OADocument
    drafts: list[DraftResponse]
    related_prior_art: list[RetrievalHit]
    deadline_summary: DeadlineInfo
    cost_meta: CostMeta
    # UX_RESEARCH §5 #2 — claim dependency tree for left-rail rendering.
    # default_factory=list keeps the field optional from the AI Engine's
    # point of view (older engines that don't populate it will still
    # validate) and from the SPA's point of view (older clients that don't
    # render it will simply ignore the field).
    claim_tree: list[ClaimNode] = Field(default_factory=list)
    # CHUNK-8 trust band. Default = empty summary so legacy callers keep
    # working and so cached responses missing this field still validate.
    redaction_summary: RedactionSummary = Field(default_factory=RedactionSummary)


# ---------- Deadline (Q17) ----------


class DeadlineInfo(BaseModel):
    model_config = {"extra": "forbid"}

    received_date: datetime
    statutory_deadline: datetime  # 法定期日（含可延展前）
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
    # M-3 fix: provenance label that tells billing dashboards whether to
    # trust `estimated_cost_usd` at face value.
    #
    #   "exact"    — model matched _MODEL_PRICING_USD_PER_M; cost is the
    #                published Anthropic list price.
    #   "fallback" — unknown model; cost was computed from the conservative
    #                sonnet-equivalent fallback table. Likely a typo in
    #                LLM_MODEL_* env or a model whose pricing isn't entered
    #                yet. WARNING is logged by rate_limit._pricing_for.
    #   "mock"     — model is a mock identifier (LLM_MODE=mock or local
    #                Ollama); cost is synthetic and MUST NOT be invoiced.
    #
    # Default "exact" keeps every existing test snapshot stable — the
    # CostMeta(...) call sites that don't supply provenance are the ones
    # building canned mock responses where the field is informational
    # only.
    cost_provenance: str = Field(default="exact", max_length=16)


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
    case_id: str | None = Field(default=None, max_length=256)
    endpoint: str = Field(..., max_length=256)
    request_hash: str = Field(..., max_length=128)  # SHA-256 of request body
    response_hash: str = Field(..., max_length=128)  # SHA-256 of response
    masked_field_rules: list[str]  # 哪些 mask 規則被觸發 (rule id, 不存內容)
    model_used: str | None = Field(default=None, max_length=128)
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    policy_decisions: dict[str, bool]  # {"rate_limit_passed": True, "authz_passed": True}


# resolve forward refs
AnalysisResponse.model_rebuild()
