"""AI Engine main entrypoint (Dify mock).

Single-step inference endpoints called by the Gateway orchestrator.
No business state lives here. No multi-step flow control here.

Endpoints:
    POST /v1/parse_oa             → list[Rejection]
    POST /v1/retrieve_prior_art   → list[RetrievalHit]
    POST /v1/draft_response       → DraftResponse
    POST /v1/verify_citations     → cleaned draft + valid/invalid citations
    POST /v1/deadline             → DeadlineInfo
    GET  /v1/health
"""
from __future__ import annotations

import hmac
import time
from datetime import datetime
from typing import Any, Optional

import base64

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.ai_engine import deadline as deadline_mod
from backend.ai_engine import oa_analyzer, pdf_parser, rag
from backend.ai_engine.prompt_loader import list_intents, load_prompt
from backend.shared.config import settings
from backend.shared.models import Rejection, RetrievalHit
from backend.shared.observability import init_sentry

# Day 5: init Sentry before FastAPI() so import-time exceptions are caught.
_SENTRY_ACTIVE = init_sentry("ai_engine")


# Content types we know how to extract. Anything else → 400 from the AI engine
# (the gateway will have already 415'd at the edge, but we re-check here as a
# defense-in-depth on the AI Engine boundary).
_PDF_MIME = "application/pdf"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


app = FastAPI(
    title="PatentMind Dify (mock) — AI Engine",
    version="0.1.0",
    description="Single-step AI inference. Called by gateway orchestrator.",
)


# ---------------------------------------------------------------------------
# Security Chunk A — C-2. Internal-token middleware.
#
# AI Engine has historically had ZERO per-endpoint auth on the assumption
# that it's only reachable via the gateway inside our VPC. That assumption
# breaks the moment the operator binds :8011 to 0.0.0.0, runs in
# docker-compose without an internal network, or exposes a debugging port.
# The blast radius (RAG poisoning, confidential-routing bypass, Anthropic
# cost abuse) is severe enough that we now require an explicit shared
# secret on every non-health request.
#
# Token-source rules:
#   - `/v1/health`  is always allowed without a token so liveness probes
#     work from anywhere.
#   - When `INTERNAL_TOKEN` is set, every other request must carry a
#     matching `X-Internal-Token` header. Mismatch + missing header both
#     return 401 with an identical body (no oracle on which one failed).
#   - When `INTERNAL_TOKEN` is empty AND `LLM_MODE=mock`, the middleware
#     permits all requests. This is the local-dev / pytest case where
#     TestClient mounts the app in-process via ASGITransport and there is
#     no realistic attacker.
#   - When `INTERNAL_TOKEN` is empty AND `LLM_MODE != mock`, the middleware
#     refuses every non-health request. This is intentional: we will NOT
#     fall back to "permit" silently in production mode — the operator must
#     either generate a token (`openssl rand -hex 32`) or explicitly stay
#     on mock.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _internal_token_middleware(request: Request, call_next):
    if request.url.path == "/v1/health":
        return await call_next(request)
    expected = settings.INTERNAL_TOKEN
    if not expected and settings.LLM_MODE == "mock":
        # Local-dev / pytest with no token configured — permit. Anyone
        # running mock mode in production is already in the "demo, not
        # prod" world C-4 closes off, so the blast radius is bounded.
        return await call_next(request)
    supplied = request.headers.get("x-internal-token", "")
    # `hmac.compare_digest` requires both operands to be non-empty strings
    # of the same type — guarded by the `expected and` short-circuit so an
    # empty `expected` in non-mock mode falls through to the 401 below.
    if not (expected and hmac.compare_digest(supplied, expected)):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized"},
        )
    return await call_next(request)


# ---------- Schemas ----------

class ParseOARequest(BaseModel):
    oa_text: str
    tenant_id: str
    case_id: str
    target_patent_no: str
    security_level: str = "public"


class RetrieveRequest(BaseModel):
    tenant_id: str
    rejection: dict       # Rejection serialised
    target_patent_no: str
    top_k: int = 5


class DraftRequest(BaseModel):
    tenant_id: str
    user_id: str
    case_id: str
    rejection: dict
    grounded_set: list[dict]
    user_hint: Optional[str] = None
    security_level: str = "public"


class VerifyRequest(BaseModel):
    draft: dict
    grounded_set: list[dict]


class DeadlineRequest(BaseModel):
    received_date_iso: str
    jurisdiction: str = "TW"
    calendar_version: str = "2025.1"


class ExtractTextRequest(BaseModel):
    file_bytes_b64: str
    content_type: str
    max_pages: int = 100
    # Defense in depth — gateway already refuses confidential uploads at the
    # edge, but the AI engine must also refuse so a misconfigured caller can't
    # leak privileged pages to the cloud OCR endpoint.
    security_level: str = "public"


# ---------- Endpoints ----------

@app.get("/v1/health")
def health():
    return {"ok": True, "service": "ai_engine", "rag_stats": rag.stats()}


# ---------------------------------------------------------------------------
# Prompt introspection (intra-VPC ONLY — see CLAUDE.md §1 / §6).
#
# AI Engine has no per-endpoint auth because it's reachable ONLY via the
# Gateway HTTP proxy inside our VPC. NEVER expose port 8001 to the public
# internet without an auth layer in front (digiRunner / nginx /
# Cloudflare Access). Prompts reveal our system-prompt strategy which is
# competitive information.
#
# Operators who want belt-and-braces — e.g. prod environments where even
# the intra-VPC blast radius is too big — can set EXPOSE_PROMPT_API=false
# to make both endpoints return 404 unconditionally.
# ---------------------------------------------------------------------------

@app.get("/v1/prompts")
def list_prompts():
    """List all externalized prompt intents. Used by Dify import + sanity."""
    if not settings.EXPOSE_PROMPT_API:
        raise HTTPException(status_code=404, detail="Not Found")
    return {"intents": list_intents()}


@app.get("/v1/prompts/{intent}")
def get_prompt(intent: str):
    """Return one prompt YAML as JSON. Dify workflows can fetch + inline."""
    if not settings.EXPOSE_PROMPT_API:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        return load_prompt(intent)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intent: {intent}")


@app.post("/v1/parse_oa")
def parse_oa(req: ParseOARequest):
    rejections, meta = oa_analyzer.parse_oa(req.oa_text, req.target_patent_no)
    oa_doc = oa_analyzer.make_oa_document(
        tenant_id=req.tenant_id,
        case_id=req.case_id,
        target_patent_no=req.target_patent_no,
        oa_text=req.oa_text,
        rejections=rejections,
    )
    return {"oa": oa_doc.model_dump(mode="json"), **meta}


@app.post("/v1/retrieve_prior_art")
def retrieve_prior_art(req: RetrieveRequest):
    rej = Rejection(**req.rejection)
    # Build query from examiner argument + cited art numbers
    query = rej.examiner_argument + " " + " ".join(rej.cited_prior_art)
    hits = rag.retrieve(req.tenant_id, query, top_k=req.top_k)
    return {"hits": [h.model_dump(mode="json") for h in hits],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


@app.post("/v1/draft_response")
def draft_response_endpoint(req: DraftRequest):
    rej = Rejection(**req.rejection)
    grounded = [RetrievalHit(**g) for g in req.grounded_set]
    draft, meta = oa_analyzer.draft_response(
        rej, grounded, req.user_hint, req.security_level
    )
    return {"draft": draft.model_dump(mode="json"), **meta}


@app.post("/v1/verify_citations")
def verify_citations_endpoint(req: VerifyRequest):
    from backend.shared.models import DraftResponse
    draft = DraftResponse(**req.draft)
    grounded = [RetrievalHit(**g) for g in req.grounded_set]
    result, meta = oa_analyzer.verify_citations(draft, grounded)
    return {**result, **meta}


@app.post("/v1/deadline")
def deadline_endpoint(req: DeadlineRequest):
    received = datetime.fromisoformat(req.received_date_iso)
    return deadline_mod.calculate_deadline(received, req.jurisdiction, req.calendar_version)


@app.post("/v1/ai/extract_text")
async def extract_text_endpoint(req: ExtractTextRequest):
    """Day 2: parse a PDF/DOCX in memory, OCR scanned PDF pages via Claude
    Vision (Haiku). The gateway base64-encodes the multipart upload before
    POSTing here so we keep the AI engine surface JSON-only (consistent with
    the other endpoints in this file).
    """
    try:
        file_bytes = base64.b64decode(req.file_bytes_b64)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"file_bytes_b64 is not valid base64: {exc}",
        )

    if req.content_type == _PDF_MIME:
        try:
            result = await pdf_parser.extract_pdf_text(
                file_bytes,
                max_pages=req.max_pages,
                security_level=req.security_level,
            )
        except PermissionError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            # Cloud OCR refused (confidential), or a page failed mid-parse.
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    elif req.content_type == _DOCX_MIME:
        try:
            result = await pdf_parser.extract_docx_text(file_bytes)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unsupported content_type: {req.content_type!r}. "
            f"Expected {_PDF_MIME!r} or {_DOCX_MIME!r}.",
        )

    # 413 from the AI engine is unusual (gateway should have caught size first)
    # but we honour max_pages overflow as a 413 here too for symmetry with the
    # gateway-level upload limit.
    if any("truncated" in w for w in result["warnings"]) and req.max_pages <= 0:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"document exceeds max_pages={req.max_pages}",
        )

    return {
        "pages": result["pages"],
        "page_count": result["page_count"],
        "ocr_pages": result["ocr_pages"],
        "char_count": result["char_count"],
        "warnings": result["warnings"],
        "usage": result["usage"],
    }


# ---------- Index management (used by seed script) ----------

class IndexPatentRequest(BaseModel):
    tenant_id: str
    patent_no: str
    title: str
    abstract: str
    claims: list[str]
    publication_date: str
    jurisdiction: str
    is_local: bool = False
    spec_text: str = ""


@app.post("/v1/index/patent")
def index_patent(req: IndexPatentRequest):
    from backend.shared.models import Patent
    p = Patent(
        patent_no=req.patent_no,
        title=req.title,
        abstract=req.abstract,
        claims=req.claims,
        publication_date=datetime.fromisoformat(req.publication_date),
        jurisdiction=req.jurisdiction,
        is_local=req.is_local,
    )
    n = rag.index_patent(req.tenant_id, p, spec_text=req.spec_text)
    return {"chunks_indexed": n, "tenant_id": req.tenant_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.ai_engine.main:app", host="0.0.0.0", port=settings.AI_ENGINE_PORT, reload=False)
