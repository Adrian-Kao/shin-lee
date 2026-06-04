"""RAG layer (Q6 chunking + Q7 vector store).

Chunking strategy:
    - Specification: hierarchical — first split by section
      (Field of Invention / Background / Summary / Detailed Description / Claims),
      then sliding window for sections > 1000 tokens, retain parent metadata.
    - Claims: claim-tree — each independent claim gets its own chunk
      with all its dependent claims attached.
    - Each chunk is tagged with metadata:
      {patent_no, section, claim_no, jurisdiction, pub_date}

Vector store:
    - POC: numpy in-memory (simulates Qdrant interface).
    - Production: Qdrant self-host, one collection per tenant.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from backend.shared.config import PATENT_DB_PATH, settings
from backend.shared.models import Patent, RetrievalHit


# ---------- Chunking ----------

@dataclass
class Chunk:
    chunk_id: str
    patent_no: str
    section: str        # claim_1, spec_para_3, abstract, ...
    claim_no: Optional[int]
    text: str
    jurisdiction: str
    metadata: dict = field(default_factory=dict)


_SECTION_HEADINGS = [
    ("FIELD_OF_INVENTION", re.compile(r"\bField of (the )?Invention\b", re.I)),
    ("BACKGROUND", re.compile(r"\bBackground\b", re.I)),
    ("SUMMARY", re.compile(r"\bSummary\b", re.I)),
    ("DETAILED_DESCRIPTION", re.compile(r"\bDetailed Description\b", re.I)),
    ("CLAIMS", re.compile(r"\bWhat is claimed is\b|\bClaims:\b", re.I)),
]


def _split_spec_into_sections(spec_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    pos = 0
    sorted_marks = []
    for label, pat in _SECTION_HEADINGS:
        m = pat.search(spec_text)
        if m:
            sorted_marks.append((m.start(), label))
    sorted_marks.sort()
    if not sorted_marks:
        return {"BODY": spec_text}
    for i, (start, label) in enumerate(sorted_marks):
        end = sorted_marks[i + 1][0] if i + 1 < len(sorted_marks) else len(spec_text)
        sections[label] = spec_text[start:end].strip()
    return sections


def _sliding_window(text: str, target_tokens: int = 400, overlap: int = 50) -> list[str]:
    """Token-approximate sliding window. POC uses chars/3 as token proxy."""
    target_chars = target_tokens * 3
    overlap_chars = overlap * 3
    out = []
    start = 0
    while start < len(text):
        end = min(start + target_chars, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap_chars
    return out


def chunk_patent(patent: Patent, spec_text: str = "") -> list[Chunk]:
    """Q6: hierarchical (spec) + claim-tree (claims).

    Args:
        patent:    the Patent record.
        spec_text: full spec text (POC uses abstract+joined claims if not given).
    """
    chunks: list[Chunk] = []

    # Abstract → 1 chunk
    chunks.append(Chunk(
        chunk_id=f"{patent.patent_no}#abstract",
        patent_no=patent.patent_no,
        section="abstract",
        claim_no=None,
        text=patent.abstract,
        jurisdiction=patent.jurisdiction,
        metadata={"pub_date": patent.publication_date.isoformat()},
    ))

    # Spec → hierarchical
    if spec_text:
        sections = _split_spec_into_sections(spec_text)
        for sec_label, sec_text in sections.items():
            windows = _sliding_window(sec_text, target_tokens=400, overlap=50)
            for i, w in enumerate(windows):
                chunks.append(Chunk(
                    chunk_id=f"{patent.patent_no}#{sec_label}_{i}",
                    patent_no=patent.patent_no,
                    section=sec_label.lower(),
                    claim_no=None,
                    text=w,
                    jurisdiction=patent.jurisdiction,
                    metadata={"section_label": sec_label, "window_idx": i,
                              "pub_date": patent.publication_date.isoformat()},
                ))

    # Claims → claim-tree
    # POC: each claim text is one chunk; in production we attach dependency tree.
    for i, claim in enumerate(patent.claims):
        cno = i + 1
        chunks.append(Chunk(
            chunk_id=f"{patent.patent_no}#claim_{cno}",
            patent_no=patent.patent_no,
            section=f"claim_{cno}",
            claim_no=cno,
            text=claim,
            jurisdiction=patent.jurisdiction,
            metadata={"pub_date": patent.publication_date.isoformat(),
                      "is_independent": _looks_independent(claim)},
        ))

    return chunks


def _looks_independent(claim_text: str) -> bool:
    """Heuristic: dependent claims usually contain '依據申請專利範圍第' or 'according to claim'."""
    return not re.search(r"\baccording to claim\b|\b依.{0,5}請求項\b|\bdepending on claim\b", claim_text, re.I)


# ---------- Embedding ----------
# Two backends behind one interface (settings.EMBEDDING_BACKEND = mock | bge-m3).
# - mock:    deterministic SHA-256 → 384 dims (POC reproducibility, mask real RAG quality)
# - bge-m3:  BAAI/bge-m3 via sentence-transformers, 1024 dims, multilingual

class Embedder:
    def __init__(self):
        self.backend = settings.EMBEDDING_BACKEND
        self._st_model = None
        if self.backend == "bge-m3":
            self._load_st()  # eager load: surfaces missing model / dep at boot

    def _load_st(self):
        from sentence_transformers import SentenceTransformer
        self._st_model = SentenceTransformer(settings.EMBEDDING_MODEL)

    @property
    def dim(self) -> int:
        if self.backend == "bge-m3":
            return self._st_model.get_sentence_embedding_dimension()
        return settings.EMBEDDING_DIM

    def embed_one(self, text: str, tenant_id: str = "") -> list[float]:
        """Embed text; ``tenant_id`` only affects the mock backend.

        Security audit H-3: in mock mode the embedding was a pure function of
        the text (sha256 → float vec). Two tenants indexing the same patent
        thus shared identical vectors, which (a) lets an attacker who can
        reach the AI Engine confirm whether a given patent is in *some*
        tenant's index by submitting the known text and matching the vector,
        and (b) means a tenant-isolation regression in the storage layer
        would silently leak similarity scores across tenants.

        Real bge-m3 embeddings are intentionally content-only (semantic
        similarity is the whole point), so the per-tenant collection split
        (Q5 stub) is the actual production defence. The mock backend is the
        only path where we can cheaply add a tenant salt without lying
        about embedding quality.
        """
        if self.backend == "bge-m3":
            v = self._st_model.encode(text, normalize_embeddings=True, show_progress_bar=False)
            return v.tolist()
        # mock: SHA-256 → padded float vec, unit-normalised.
        # H-3 fix: salt with tenant_id so different tenants get different
        # vectors for the same input text. ``tenant_id=""`` (the default,
        # used by callers that have no tenant context — e.g. unit tests of
        # the chunker) reproduces the old behaviour exactly.
        seed = f"{tenant_id}:{text}" if tenant_id else text
        h = hashlib.sha256(seed.encode()).digest()
        raw = list(h) * (settings.EMBEDDING_DIM // len(h) + 1)
        vec = np.array(raw[: settings.EMBEDDING_DIM], dtype=np.float32) / 255.0
        n = np.linalg.norm(vec)
        if n > 0:
            vec = vec / n
        return vec.tolist()


_embedder = Embedder()


def embed(text: str, tenant_id: str = "") -> list[float]:
    """Module-level embed helper. ``tenant_id`` is plumbed through to the
    mock backend so per-tenant salting (H-3 fix) takes effect; bge-m3
    ignores it. Callers that have a tenant context (``index_patent``,
    ``retrieve``) MUST pass it — leaving the default empty string is
    only safe in standalone chunker tests."""
    return _embedder.embed_one(text, tenant_id=tenant_id)


# ---------- Vector store ----------
# Two backends behind one interface (settings.VECTOR_BACKEND = memory | qdrant).
# Q5 + Q7: production runs Qdrant with one collection per tenant.

import uuid

_QDRANT_NS = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _chunk_point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


class MemoryVectorStore:
    def __init__(self):
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}
        self._tenant_index: dict[str, set[str]] = {}

    def upsert(self, tenant_id: str, chunks: list[Chunk], vectors: list[list[float]]):
        for ch, vec in zip(chunks, vectors):
            self._chunks[ch.chunk_id] = ch
            self._vectors[ch.chunk_id] = np.array(vec, dtype=np.float32)
            self._tenant_index.setdefault(tenant_id, set()).add(ch.chunk_id)

    def search(self, tenant_id, query_vec, top_k=5, metadata_filter=None):
        ids = self._tenant_index.get(tenant_id, set())
        if not ids:
            return []
        q = np.array(query_vec, dtype=np.float32)
        scored = []
        for cid in ids:
            ch = self._chunks[cid]
            if metadata_filter:
                ok = True
                for k, v in metadata_filter.items():
                    if getattr(ch, k, None) != v and ch.metadata.get(k) != v:
                        ok = False
                        break
                if not ok:
                    continue
            v = self._vectors[cid]
            score = float(np.dot(q, v))
            scored.append((ch, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def stats(self) -> dict:
        return {
            "backend": "memory",
            "total_chunks": len(self._chunks),
            "tenants_indexed": list(self._tenant_index.keys()),
            "per_tenant_count": {k: len(v) for k, v in self._tenant_index.items()},
        }

    def list_claim_chunks(self, tenant_id: str, patent_no: str) -> list[Chunk]:
        """Return all claim-section chunks for one patent, sorted by claim_no.

        Used by the claim-tree endpoint to recover the indexed patent's
        flat claim list. Returns [] if the patent wasn't indexed for this
        tenant (caller treats that as "no tree available").
        """
        out: list[Chunk] = []
        for cid in self._tenant_index.get(tenant_id, set()):
            ch = self._chunks[cid]
            if ch.patent_no == patent_no and ch.claim_no is not None:
                out.append(ch)
        out.sort(key=lambda c: c.claim_no or 0)
        return out


class QdrantVectorStore:
    """Q7: Qdrant per-tenant collection, payload-stored chunk fields."""

    def __init__(self, url: str, dim: int):
        from qdrant_client import QdrantClient  # lazy import: keeps memory mode dep-free
        from qdrant_client.http import models as qm

        self._qm = qm
        self._client = QdrantClient(url=url)
        self._dim = dim
        self._known_tenants: set[str] = set()

    def _coll(self, tenant_id: str) -> str:
        return f"patentmind_{tenant_id}"

    def _ensure_collection(self, tenant_id: str):
        name = self._coll(tenant_id)
        if name in self._known_tenants:
            return
        existing = {c.name for c in self._client.get_collections().collections}
        if name in existing:
            # Drop+recreate if dim drifted (e.g. switched mock 384 ↔ bge-m3 1024)
            info = self._client.get_collection(collection_name=name)
            existing_dim = info.config.params.vectors.size
            if existing_dim != self._dim:
                self._client.delete_collection(collection_name=name)
                existing.discard(name)
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=self._qm.VectorParams(size=self._dim, distance=self._qm.Distance.COSINE),
            )
        self._known_tenants.add(name)

    def upsert(self, tenant_id: str, chunks: list[Chunk], vectors: list[list[float]]):
        self._ensure_collection(tenant_id)
        points = [
            self._qm.PointStruct(
                id=_chunk_point_id(ch.chunk_id),
                vector=vec,
                payload={
                    "chunk_id": ch.chunk_id,
                    "patent_no": ch.patent_no,
                    "section": ch.section,
                    "claim_no": ch.claim_no,
                    "text": ch.text,
                    "jurisdiction": ch.jurisdiction,
                    "metadata": ch.metadata,
                },
            )
            for ch, vec in zip(chunks, vectors)
        ]
        self._client.upsert(collection_name=self._coll(tenant_id), points=points)

    def search(self, tenant_id, query_vec, top_k=5, metadata_filter=None):
        coll = self._coll(tenant_id)
        existing = {c.name for c in self._client.get_collections().collections}
        if coll not in existing:
            return []
        flt = None
        if metadata_filter:
            conds = []
            for k, v in metadata_filter.items():
                # Search top-level payload first; fallback to metadata.k
                conds.append(self._qm.FieldCondition(key=k, match=self._qm.MatchValue(value=v)))
            flt = self._qm.Filter(should=[
                self._qm.Filter(must=[c]) for c in conds
            ] + [
                self._qm.Filter(must=[self._qm.FieldCondition(
                    key=f"metadata.{k}", match=self._qm.MatchValue(value=v),
                )]) for k, v in metadata_filter.items()
            ])
        res = self._client.search(
            collection_name=coll,
            query_vector=query_vec,
            limit=top_k,
            query_filter=flt,
        )
        out: list[tuple[Chunk, float]] = []
        for p in res:
            pl = p.payload or {}
            ch = Chunk(
                chunk_id=pl.get("chunk_id", str(p.id)),
                patent_no=pl.get("patent_no", ""),
                section=pl.get("section", ""),
                claim_no=pl.get("claim_no"),
                text=pl.get("text", ""),
                jurisdiction=pl.get("jurisdiction", ""),
                metadata=pl.get("metadata", {}),
            )
            out.append((ch, float(p.score)))
        return out

    def stats(self) -> dict:
        existing = [c.name for c in self._client.get_collections().collections]
        per = {}
        tenants = []
        for name in existing:
            if not name.startswith("patentmind_"):
                continue
            tenant = name[len("patentmind_"):]
            tenants.append(tenant)
            try:
                info = self._client.count(collection_name=name, exact=True)
                per[tenant] = info.count
            except Exception:
                per[tenant] = -1
        return {
            "backend": "qdrant",
            "total_chunks": sum(v for v in per.values() if v >= 0),
            "tenants_indexed": tenants,
            "per_tenant_count": per,
        }

    def list_claim_chunks(self, tenant_id: str, patent_no: str) -> list[Chunk]:
        """Scroll through this tenant's collection and return claim chunks
        for the given patent, sorted by claim_no. Returns [] when the
        tenant collection or the patent has no claim chunks.
        """
        coll = self._coll(tenant_id)
        existing = {c.name for c in self._client.get_collections().collections}
        if coll not in existing:
            return []
        flt = self._qm.Filter(must=[
            self._qm.FieldCondition(
                key="patent_no", match=self._qm.MatchValue(value=patent_no),
            ),
        ])
        out: list[Chunk] = []
        # Qdrant `scroll` is the read-all-by-filter primitive; cap pages at
        # 256 so a misconfigured caller scrolling a 100k-claim corpus can't
        # OOM us. Real patents top out around 50 claims, so 256 is generous.
        offset = None
        for _ in range(8):  # 8 * 32 = 256 chunks max — bounded.
            scroll_res, offset = self._client.scroll(
                collection_name=coll,
                scroll_filter=flt,
                limit=32,
                with_payload=True,
                offset=offset,
            )
            for p in scroll_res:
                pl = p.payload or {}
                if pl.get("claim_no") is None:
                    continue
                out.append(Chunk(
                    chunk_id=pl.get("chunk_id", str(p.id)),
                    patent_no=pl.get("patent_no", ""),
                    section=pl.get("section", ""),
                    claim_no=pl.get("claim_no"),
                    text=pl.get("text", ""),
                    jurisdiction=pl.get("jurisdiction", ""),
                    metadata=pl.get("metadata", {}),
                ))
            if offset is None:
                break
        out.sort(key=lambda c: c.claim_no or 0)
        return out


def _make_store():
    if settings.VECTOR_BACKEND == "qdrant":
        return QdrantVectorStore(url=settings.QDRANT_URL, dim=_embedder.dim)
    return MemoryVectorStore()


_store = _make_store()


# ---------- Public RAG API ----------

def index_patent(tenant_id: str, patent: Patent, spec_text: str = "") -> int:
    chunks = chunk_patent(patent, spec_text=spec_text)
    # H-3: salt mock embeddings with tenant_id (no-op for bge-m3). Indexing
    # the same patent in tenant_a vs tenant_b now produces distinct vectors,
    # so a similarity-oracle attack against /v1/retrieve_prior_art cannot
    # confirm cross-tenant content.
    vectors = [embed(c.text, tenant_id=tenant_id) for c in chunks]
    _store.upsert(tenant_id, chunks, vectors)
    return len(chunks)


def retrieve(
    tenant_id: str,
    query: str,
    top_k: int = 5,
    jurisdiction: Optional[str] = None,
    prefer_patent_no: Optional[str] = None,
) -> list[RetrievalHit]:
    """RAG retrieval with optional same-patent boost.

    `prefer_patent_no` (typically the case's target patent) gets a score
    boost so its chunks float to the top even when the embedding signal is
    weak — important on mock embeddings where cosine scores cluster within
    ~0.02 and rankings are near random.
    """
    # H-3: salt the query vector with the same tenant_id used at index time
    # so retrieval scores are computed in the tenant's vector space. Without
    # this the query vector would be tenant-independent but the index vectors
    # would be tenant-salted, producing zero similarity by construction.
    qvec = embed(query, tenant_id=tenant_id)
    base_filter: dict = {"jurisdiction": jurisdiction} if jurisdiction else {}

    semantic_hits = _store.search(
        tenant_id, qvec, top_k=top_k, metadata_filter=base_filter or None
    )

    if prefer_patent_no:
        target_filter = {**base_filter, "patent_no": prefer_patent_no}
        target_hits = _store.search(
            tenant_id, qvec, top_k=top_k, metadata_filter=target_filter
        )
        # OR-merge: boost target chunks so they outrank pure semantic on mock embeddings.
        boost = 0.20
        merged: dict[str, tuple] = {}
        for ch, s in semantic_hits:
            merged[ch.chunk_id] = (ch, s)
        for ch, s in target_hits:
            merged[ch.chunk_id] = (ch, s + boost)
        hits = sorted(merged.values(), key=lambda x: -x[1])[:top_k]
    else:
        hits = semantic_hits

    return [
        RetrievalHit(
            patent_no=ch.patent_no,
            section=ch.section,
            text=ch.text,
            score=score,
            metadata={
                "chunk_id": ch.chunk_id,
                "claim_no": ch.claim_no,
                "jurisdiction": ch.jurisdiction,
                **ch.metadata,
            },
        )
        for ch, score in hits
    ]


def get_claim_tree(tenant_id: str, patent_no: str) -> list[dict]:
    """Return the indexed patent's claims as a list of ClaimNode dicts.

    Pulls the patent's claim_* chunks out of the vector store (sorted by
    `claim_no`) and runs the pure-Python `parse_claim_dependencies` parser
    over them. Returns an empty list when the patent hasn't been indexed
    for this tenant — the frontend treats "[]" as "no tree to render"
    so callers don't have to special-case it.
    """
    from backend.ai_engine.claim_tree import parse_claim_dependencies

    chunks = _store.list_claim_chunks(tenant_id, patent_no)
    if not chunks:
        return []
    return parse_claim_dependencies([c.text for c in chunks])


def stats() -> dict:
    s = _store.stats()
    s["embedding_backend"] = _embedder.backend
    s["embedding_dim"] = _embedder.dim
    return s
