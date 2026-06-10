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
import math
import re
import sqlite3
import zlib
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

    # Claims → claim-tree (Q6: "每 claim 一 chunk 帶依附項").
    #
    # Two chunk families are emitted, kept deliberately separate:
    #
    #   1. Per-claim `claim_N` chunks (claim_no=N) — ONE claim text each.
    #      These are the source of truth for the claim-tree UI: `get_claim_tree`
    #      pulls them via `list_claim_chunks` (which filters claim_no is not
    #      None) and re-runs `parse_claim_dependencies` over their `.text`.
    #      They MUST stay single-claim or the tree parser mis-parses, so they
    #      are emitted verbatim below, exactly as before.
    #
    #   2. Bundle `claim_N_tree` chunks (claim_no=None) — for each INDEPENDENT
    #      claim, the independent claim text PLUS the text of all its
    #      transitively-dependent claims, concatenated. This is what retrieval
    #      should embed: querying a limitation that lives only in a dependent
    #      claim ("...further comprising temperature sensors") should still
    #      surface the independent claim's family. claim_no=None keeps these
    #      out of `list_claim_chunks`, so the tree path never sees them.
    #
    # Dependency edges come from `parse_claim_dependencies` (parser-derived,
    # more reliable than the `_looks_independent` heuristic). We still record
    # the heuristic flag on per-claim chunks for backwards compatibility, but
    # independence for bundling is decided by the parser (a node with
    # depends_on is None is independent).
    from backend.ai_engine.claim_tree import parse_claim_dependencies

    tree_nodes = parse_claim_dependencies(list(patent.claims))
    # Map: parent claim_no -> list of direct child claim_nos.
    children: dict[int, list[int]] = {}
    for node in tree_nodes:
        parent = node["depends_on"]
        if parent is not None:
            children.setdefault(parent, []).append(node["claim_no"])

    def _transitive_dependents(root: int) -> list[int]:
        """BFS over the child graph; returns dependent claim_nos in claim
        order, excluding the root. Cycle-safe via a visited set (the parser
        forbids forward refs so cycles shouldn't occur, but be defensive)."""
        seen: set[int] = set()
        out: list[int] = []
        queue = list(children.get(root, []))
        while queue:
            c = queue.pop(0)
            if c in seen or c == root:
                continue
            seen.add(c)
            out.append(c)
            queue.extend(children.get(c, []))
        return sorted(out)

    claim_text_by_no = {node["claim_no"]: node["text"] for node in tree_nodes}

    for i, claim in enumerate(patent.claims):
        cno = i + 1
        # (1) Per-claim chunk — UNCHANGED. Single claim text, claim_no=cno.
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

    # (2) Bundle chunks — one per independent claim, carrying its dependents.
    for node in tree_nodes:
        if not node["is_independent"]:
            continue
        cno = node["claim_no"]
        dependents = _transitive_dependents(cno)
        if not dependents:
            # No dependents → the bundle would equal the per-claim chunk; the
            # per-claim `claim_N` chunk already covers retrieval, so skip to
            # avoid a redundant near-duplicate vector. (Pure independent claim.)
            continue
        parts = [claim_text_by_no.get(cno, "")]
        parts.extend(claim_text_by_no.get(d, "") for d in dependents)
        bundle_text = "\n\n".join(p for p in parts if p)
        chunks.append(Chunk(
            chunk_id=f"{patent.patent_no}#claim_{cno}_tree",
            patent_no=patent.patent_no,
            section=f"claim_{cno}_tree",
            claim_no=None,  # excluded from list_claim_chunks → tree path safe
            text=bundle_text,
            jurisdiction=patent.jurisdiction,
            metadata={"pub_date": patent.publication_date.isoformat(),
                      "is_independent": True,
                      "root_claim_no": cno,
                      "dependent_claims": dependents},
        ))

    return chunks


def _looks_independent(claim_text: str) -> bool:
    """Heuristic: dependent claims usually contain '依據申請專利範圍第' or 'according to claim'."""
    return not re.search(r"\baccording to claim\b|\b依.{0,5}請求項\b|\bdepending on claim\b", claim_text, re.I)


# ---------- Embedding ----------
# Three backends behind one interface (settings.EMBEDDING_BACKEND = mock | lexical | bge-m3).
# - mock:    deterministic SHA-256 → 384 dims. NOT semantic: cosine between any
#            two distinct texts is near-random noise. Proves wiring only.
# - lexical: dependency-free hashing vectorizer (numpy-only). REAL lexical-overlap
#            semantics — texts sharing terms have higher cosine — so retrieval
#            actually works in an air-gapped / no-GPU demo without torch/bge-m3.
# - bge-m3:  BAAI/bge-m3 via sentence-transformers, 1024 dims, multilingual.
#            Best quality but needs torch (which crashes on some boxes).
#
# `lexical` is selected purely by the env var EMBEDDING_BACKEND=lexical; it reads
# the same free-form settings.EMBEDDING_BACKEND string the other backends do, so
# no config.py enum change is needed.


# ---------- Lexical hashing-vectorizer helpers (numpy-only, stateless) ----------
# A stateless hashing vectorizer (a.k.a. "hashing trick"): no fitted IDF state,
# fully deterministic. Tokens are hashed straight into EMBEDDING_DIM buckets via
# a STABLE hash (zlib.crc32 — Python's builtin hash() is PYTHONHASHSEED-salted
# and would make vectors non-reproducible across processes). We accumulate
# sublinear TF (1 + log(count)) per bucket and L2-normalise, so cosine reflects
# lexical overlap. Two scripts are tokenized:
#   - English/Latin: lowercase \b\w+\b word tokens.
#   - CJK (TW/CN/KR/JP patents have no whitespace): character BIGRAMS, which
#     capture term overlap far better than unigrams (e.g. "充電管理" shares the
#     bigrams 充電/電管/管理 with "負載管理" only at 管理 — graded overlap).
# Both token streams are combined into one bag for a single text.

# A "CJK" char here = any non-ASCII letter (covers Han, Hiragana/Katakana, Hangul).
# We treat the whole non-ASCII-word run as bigram-able. Latin-1 accented letters
# would also fall in here, but patent corpora that use them still get word tokens
# from the \w+ pass, so the extra bigrams are harmless redundancy.
_LATIN_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_CHAR_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힣豈-﫿]")


def _lexical_tokens(text: str) -> list[str]:
    """Tokenize for BOTH scripts and return the combined token bag.

    - Latin/ASCII words → lowercased ``[a-z0-9]+`` tokens (prefixed ``w:``).
    - CJK runs → character BIGRAMS over each contiguous CJK run (prefixed
      ``b:``); a lone CJK char in its own run yields a single unigram so it is
      not silently dropped.

    Prefixes keep the two namespaces from colliding in the hash space (a Latin
    word can never alias a CJK bigram).
    """
    tokens: list[str] = []
    # Latin/ASCII word tokens (lowercased).
    for m in _LATIN_WORD_RE.finditer(text.lower()):
        tokens.append("w:" + m.group(0))
    # CJK bigrams: walk contiguous runs of CJK chars.
    run: list[str] = []

    def _flush_run():
        if not run:
            return
        if len(run) == 1:
            tokens.append("b:" + run[0])
        else:
            for i in range(len(run) - 1):
                tokens.append("b:" + run[i] + run[i + 1])

    for ch in text:
        if _CJK_CHAR_RE.match(ch):
            run.append(ch)
        else:
            _flush_run()
            run = []
    _flush_run()
    return tokens


def _lexical_embed(text: str, tenant_id: str, dim: int) -> list[float]:
    """Hashing vectorizer → L2-normalised dense vector of length ``dim``.

    Deterministic & numpy-only. Per-bucket value = sublinear TF (1+log(count)).

    H-3 tenant isolation: the tenant_id is folded into the bucket hash (like the
    mock salt), so the SAME text under tenant_a vs tenant_b lands in different
    buckets → different vectors (defeats the similarity-oracle). Because EVERY
    token of a given tenant shares the same salt, the permutation of buckets is
    consistent within a tenant, so pairwise cosines BETWEEN that tenant's texts
    are unchanged — within-tenant relative similarity (the thing retrieval needs)
    is preserved. ``tenant_id=""`` is its own namespace (chunker unit tests).
    """
    salt = f"{tenant_id}|".encode()
    counts: dict[int, int] = {}
    for tok in _lexical_tokens(text):
        # crc32 is a stable, process-independent 32-bit hash. Fold tenant salt
        # in so buckets are tenant-specific (H-3) while staying deterministic.
        bucket = zlib.crc32(tok.encode("utf-8"), zlib.crc32(salt)) % dim
        counts[bucket] = counts.get(bucket, 0) + 1
    vec = np.zeros(dim, dtype=np.float32)
    for bucket, c in counts.items():
        vec[bucket] = 1.0 + math.log(c)  # sublinear TF
    n = float(np.linalg.norm(vec))
    if n > 0:
        vec = vec / n
    return vec.tolist()


class Embedder:
    def __init__(self):
        self.backend = settings.EMBEDDING_BACKEND
        self._st_model = None
        if self.backend == "bge-m3":
            self._load_st()  # eager load: surfaces missing model / dep at boot

    def _load_st(self):
        from sentence_transformers import SentenceTransformer
        try:
            # Offline-first: if the model is already in the local HF cache
            # (see scripts/prefetch_bge_m3.py) load it WITHOUT any hub round
            # trip. Boot must not depend on huggingface.co reachability —
            # air-gapped / proxied on-prem deployments (Q3 posture); the
            # online adapter-config probe is a known flake behind firewalls.
            self._st_model = SentenceTransformer(
                settings.EMBEDDING_MODEL, local_files_only=True
            )
        except Exception:
            # Model not cached yet — fall back to a normal downloading load.
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
        cache_key = _embedding_cache_key(self.backend, tenant_id, text)
        cached = _EMBEDDING_CACHE.get(cache_key)
        if cached is not None:
            _EMBEDDING_CACHE_STATS["hits"] += 1
            return cached
        _EMBEDDING_CACHE_STATS["misses"] += 1
        if self.backend == "bge-m3":
            v = self._st_model.encode(text, normalize_embeddings=True, show_progress_bar=False)
            vec_list = v.tolist()
        elif self.backend == "lexical":
            # Dependency-free hashing vectorizer with REAL lexical-overlap
            # semantics (unlike mock). Tenant-salted for H-3, same contract as
            # mock (list[float] of length EMBEDDING_DIM). See _lexical_embed.
            vec_list = _lexical_embed(text, tenant_id, settings.EMBEDDING_DIM)
        else:
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
            vec_list = vec.tolist()
        _EMBEDDING_CACHE[cache_key] = vec_list
        return vec_list


# ---------- Embedding cache (Q9) ----------
# Q9 caches embeddings permanently — patents don't change post-publication, and
# recomputing the same vector on every retrieve/index is pure waste. The gateway
# owns the production cache (backend/gateway/cache.py, Redis-bound), but the AI
# Engine MUST NOT import gateway business state (CLAUDE.md §4 invariant: "AI
# Engine holds no business state"). So we keep a small, self-contained, in-process
# memo HERE, keyed identically in spirit to gateway/cache.py's tenant-namespaced
# emb: key. Production swaps this dict for Redis using the SAME tenant-aware key
# scheme so the two layers can't disagree about isolation.
#
# H-3 / CRITICAL: the key folds in tenant_id, so tenant_a and tenant_b NEVER
# share an entry. In mock mode their vectors genuinely differ (per-tenant salt);
# caching across tenants would serve tenant_a's vector to tenant_b and silently
# break the isolation that test_cross_tenant.py protects. bge-m3 is content-only
# and would be safe to share, but we always namespace by tenant for simplicity
# and correctness. tenant_id="" is its own ("") namespace (standalone chunker
# tests), so it never collides with a real tenant.
_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_STATS = {"hits": 0, "misses": 0}


def _embedding_cache_key(backend: str, tenant_id: str, text: str) -> str:
    h = hashlib.sha256(f"{tenant_id}|{text}".encode()).hexdigest()
    return f"{backend}:{h}"


def clear_embedding_cache() -> None:
    """Reset the in-process embedding cache and its hit/miss counters.

    Test hygiene: lets unit tests assert hit/miss behaviour from a known
    empty state. Production never calls this (the memo is process-lifetime;
    Redis handles eviction)."""
    _EMBEDDING_CACHE.clear()
    _EMBEDDING_CACHE_STATS["hits"] = 0
    _EMBEDDING_CACHE_STATS["misses"] = 0


def embedding_cache_stats() -> dict:
    """Observable hit/miss counters + entry count, so the cache is demonstrably
    working (the Q9 hit test asserts against this)."""
    return {
        "hits": _EMBEDDING_CACHE_STATS["hits"],
        "misses": _EMBEDDING_CACHE_STATS["misses"],
        "entries": len(_EMBEDDING_CACHE),
    }


_embedder = Embedder()


def embed(text: str, tenant_id: str = "") -> list[float]:
    """Module-level embed helper. ``tenant_id`` is plumbed through to the
    mock backend so per-tenant salting (H-3 fix) takes effect; bge-m3
    ignores it. Callers that have a tenant context (``index_patent``,
    ``retrieve``) MUST pass it — leaving the default empty string is
    only safe in standalone chunker tests.

    Q9: results are memoised in a tenant-namespaced in-process cache (see
    ``_EMBEDDING_CACHE``); repeated embeds of the same (tenant, text) are
    served from cache, and cross-tenant reads never hit."""
    return _embedder.embed_one(text, tenant_id=tenant_id)


# ---------- Vector store ----------
# Two backends behind one interface (settings.VECTOR_BACKEND = memory | qdrant).
# Q5 + Q7: production runs Qdrant with one collection per tenant.

import abc
import logging
import uuid

_QDRANT_NS = uuid.UUID("00000000-0000-0000-0000-000000000001")

logger = logging.getLogger(__name__)


def _chunk_point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


class VectorStore(abc.ABC):
    """Formal contract for a swappable tenant-scoped vector store (Q7).

    The Q7 decision is "Milvus/Qdrant self-host, interface abstraction so the
    backend is swappable". This ABC makes that swappability *provable*: every
    concrete backend (MemoryVectorStore, QdrantVectorStore) must implement the
    exact same surface, so they cannot silently drift apart. The shared
    contract test suite (tests/unit/test_vector_store_contract.py) runs the
    same assertions against any subclass.

    All operations are tenant-scoped: a tenant never sees another tenant's
    chunks. In Qdrant this maps to one collection per tenant.
    """

    @abc.abstractmethod
    def upsert(
        self, tenant_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        """Insert or update `chunks` (with parallel `vectors`) for `tenant_id`.

        `chunks` and `vectors` are positionally aligned (zip). Re-upserting a
        chunk with the same `chunk_id` overwrites it.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def search(
        self,
        tenant_id: str,
        query_vec: list[float],
        top_k: int = 5,
        metadata_filter: Optional[dict] = None,
    ) -> list[tuple[Chunk, float]]:
        """Return up to `top_k` nearest chunks for `tenant_id`.

        Return contract: ``list[tuple[Chunk, float]]`` — each tuple is
        ``(chunk, score)``, sorted by descending score (highest first).
        `metadata_filter`, when given, is an AND over field/value pairs matched
        against either a top-level Chunk attribute or the chunk's `metadata`
        dict. Returns ``[]`` when the tenant has no indexed chunks.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def stats(self) -> dict:
        """Return a backend-tagged summary dict (chunk counts per tenant)."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_claim_chunks(self, tenant_id: str, patent_no: str) -> list[Chunk]:
        """Return only the claim-section chunks (claim_no is not None) for one
        patent, sorted ascending by `claim_no`. Returns ``[]`` if the patent
        wasn't indexed for this tenant.
        """
        raise NotImplementedError


class VectorDimMismatch(ValueError):
    """Raised when a vector's length disagrees with the store's established dim.

    Both backends share this contract: a store fixes its vector dimension from
    the first vector it sees, and any later upsert/search vector of a different
    length is a programming error (usually an embedder swap without a re-index,
    e.g. mock 384 ↔ bge-m3 1024). We surface ONE clear, backend-agnostic
    exception instead of leaking a raw numpy shape error (memory) or a Qdrant
    server 400 — so the contract test can assert identical behaviour and the
    caller gets an actionable message.
    """


class MemoryVectorStore(VectorStore):
    def __init__(self):
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}
        self._tenant_index: dict[str, set[str]] = {}
        # Established vector dimension (set lazily from the first vector seen).
        # None until the first upsert. Mirrors Qdrant's fixed-size collection.
        self._dim: Optional[int] = None

    def _check_dim(self, vec) -> None:
        """Fix the store dim on first sight; reject any later size drift.

        Empty corpus + first vector establishes the dim. A subsequent vector
        of a different length raises VectorDimMismatch (the same guard Qdrant
        enforces server-side), turning a silent numpy broadcast bug into a
        loud, actionable error.
        """
        n = len(vec)
        if n == 0:
            raise VectorDimMismatch("vector has length 0; cannot index/search an empty vector")
        if self._dim is None:
            self._dim = n
        elif n != self._dim:
            raise VectorDimMismatch(
                f"vector dim mismatch: store dim={self._dim} but got length {n}. "
                f"This usually means the embedder changed (e.g. mock 384 ↔ "
                f"bge-m3 1024) without re-indexing. Re-index the tenant with a "
                f"consistent embedder."
            )

    def upsert(self, tenant_id: str, chunks: list[Chunk], vectors: list[list[float]]):
        # Validate ALL incoming vectors BEFORE mutating any state, so a bad
        # batch fails atomically (no half-written tenant index).
        pairs = list(zip(chunks, vectors))
        for _ch, vec in pairs:
            self._check_dim(vec)
        for ch, vec in pairs:
            self._chunks[ch.chunk_id] = ch
            self._vectors[ch.chunk_id] = np.array(vec, dtype=np.float32)
            self._tenant_index.setdefault(tenant_id, set()).add(ch.chunk_id)

    def search(self, tenant_id, query_vec, top_k=5, metadata_filter=None):
        ids = self._tenant_index.get(tenant_id, set())
        if not ids:
            return []
        # Guard the query vector against the established dim too — a search
        # with a mismatched query would otherwise raise a cryptic numpy error
        # deep in the dot product. (Only meaningful once something is indexed,
        # which the empty-tenant early-return above guarantees.)
        self._check_dim(query_vec)
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


def _should_drop_for_dim(existing_dim: int, new_dim: int, allow_reindex: bool) -> bool:
    """Decide whether a dim-mismatched Qdrant collection may be dropped.

    Pure helper so the data-loss guard is unit-testable without a real Qdrant.

    - dims match            → return False (no drop needed).
    - dims differ, no opt-in → raise RuntimeError (REFUSE: dropping would
      silently destroy the tenant's whole index).
    - dims differ, opt-in    → return True (caller drops+recreates; logs WARNING).
    """
    if existing_dim == new_dim:
        return False
    if not allow_reindex:
        raise RuntimeError(
            f"Qdrant collection vector dim mismatch: stored={existing_dim} "
            f"current_embedder={new_dim}. Refusing to drop the existing index "
            f"(this would destroy all stored vectors for this tenant). "
            f"If this dim change is deliberate, re-index explicitly by setting "
            f"QDRANT_ALLOW_REINDEX=true (env) — and only after confirming the "
            f"tenant's data can be safely rebuilt."
        )
    return True


class QdrantVectorStore(VectorStore):
    """Q7: Qdrant per-tenant collection, payload-stored chunk fields."""

    def __init__(self, url: str, dim: int):
        from qdrant_client import QdrantClient  # lazy import: keeps memory mode dep-free
        from qdrant_client.http import models as qm

        self._qm = qm
        # timeout=30 (default 5s REST): collection create/delete churn on a
        # loaded Docker Desktop box has been observed to exceed 5s (408s),
        # which surfaced as flaky upserts/searches. 30s rides out the stall
        # without masking a truly dead server.
        self._client = QdrantClient(url=url, timeout=30)
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
            # Dim drift (e.g. switched mock 384 ↔ bge-m3 1024). Dropping the
            # collection silently destroys the tenant's whole index, so refuse
            # by default; only drop+recreate when an operator opted in via
            # QDRANT_ALLOW_REINDEX.
            info = self._client.get_collection(collection_name=name)
            existing_dim = info.config.params.vectors.size
            if _should_drop_for_dim(existing_dim, self._dim, settings.QDRANT_ALLOW_REINDEX):
                logger.warning(
                    "QDRANT_ALLOW_REINDEX=true: dropping collection %s due to "
                    "vector dim change %s -> %s. All stored vectors for this "
                    "tenant will be lost and must be re-indexed.",
                    name, existing_dim, self._dim,
                )
                self._client.delete_collection(collection_name=name)
                existing.discard(name)
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=self._qm.VectorParams(size=self._dim, distance=self._qm.Distance.COSINE),
            )
        self._known_tenants.add(name)

    def upsert(self, tenant_id: str, chunks: list[Chunk], vectors: list[list[float]]):
        if not chunks:
            # Empty batch is a contract-level no-op (13H robustness). Qdrant
            # rejects an empty points PUT with 400 "Empty update request",
            # and we should not even create the collection for it.
            return
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
