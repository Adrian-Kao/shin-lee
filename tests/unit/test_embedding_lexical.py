"""Lexical embedding backend (EMBEDDING_BACKEND=lexical) — REAL semantics proof.

The mock backend is deterministic SHA-256 noise: cosine between any two distinct
texts is near-random, so it only proves retrieval WIRING, not quality. The
`lexical` backend is a dependency-free (numpy-only) hashing vectorizer that gives
genuine lexical-overlap semantics — texts that share terms have HIGHER cosine —
so retrieval actually works in an air-gapped / no-GPU demo without torch/bge-m3.

These tests are the load-bearing assertions for that backend:

  * determinism + unit norm + dim == EMBEDDING_DIM (same contract as mock);
  * the headline: cos(related) > cos(unrelated), for BOTH Latin words and CJK
    bigrams (the property mock SHA-256 lacks);
  * H-3: same text under two tenants → different vectors, yet within ONE tenant
    the related>unrelated ordering still holds (tenant salt permutes buckets
    consistently, so within-tenant cosines are preserved);
  * a retrieval-level proof: index patents under lexical, query with text that
    overlaps ONE patent, assert that patent ranks first.

Selection is purely via the env var EMBEDDING_BACKEND=lexical (settings reads it
as a free-form str), so these tests monkeypatch ``settings.EMBEDDING_BACKEND``
and rebuild the rag module singletons (the reset idiom the other rag tests use).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.ai_engine import rag
from backend.ai_engine.rag import Embedder, _lexical_tokens
from backend.shared.config import settings


def _cos(a, b) -> float:
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


@pytest.fixture
def lexical_embedder(monkeypatch):
    """An Embedder pinned to the lexical backend, with a clean embedding cache.

    The cache keys on (backend, tenant_id, text), so lexical vectors can't be
    served a stale mock entry — but we clear it anyway for hermetic hit/miss.
    """
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "lexical")
    rag.clear_embedding_cache()
    emb = Embedder()
    assert emb.backend == "lexical"
    yield emb
    rag.clear_embedding_cache()


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
def test_tokenizer_emits_latin_words_and_cjk_bigrams():
    toks = _lexical_tokens("Cooling 系統 ok")
    # Latin words lowercased + namespaced.
    assert "w:cooling" in toks
    assert "w:ok" in toks
    # CJK run "系統" -> one bigram.
    assert "b:系統" in toks


def test_tokenizer_namespaces_prevent_latin_cjk_collision():
    # A Latin token and a CJK bigram can never be the same string (different
    # prefixes), so they occupy disjoint slices of the hash space.
    latin = set(_lexical_tokens("abc def"))
    cjk = set(_lexical_tokens("中文字詞"))
    assert all(t.startswith("w:") for t in latin)
    assert all(t.startswith("b:") for t in cjk)
    assert latin.isdisjoint(cjk)


def test_tokenizer_single_cjk_char_is_not_dropped():
    # A lone CJK char (run length 1) still yields a unigram token.
    assert "b:電" in _lexical_tokens("電 abc")


# ---------------------------------------------------------------------------
# Contract: determinism, unit norm, dim
# ---------------------------------------------------------------------------
def test_lexical_is_deterministic_same_tenant(lexical_embedder):
    text = "a microchannel cooling system for an electric vehicle battery"
    v1 = lexical_embedder.embed_one(text, tenant_id="t1")
    v2 = lexical_embedder.embed_one(text, tenant_id="t1")
    assert v1 == v2, "same (text, tenant) must produce an identical vector"


def test_lexical_vector_is_unit_norm_and_correct_dim(lexical_embedder):
    v = lexical_embedder.embed_one("solid copper heat sink with extruded fins", tenant_id="t1")
    assert len(v) == settings.EMBEDDING_DIM
    assert lexical_embedder.dim == settings.EMBEDDING_DIM
    norm = float(np.linalg.norm(np.array(v)))
    assert norm == pytest.approx(1.0, abs=1e-5), f"vector must be L2-normalised, got {norm}"


# ---------------------------------------------------------------------------
# Headline: REAL semantics — related texts are more similar than unrelated.
# ---------------------------------------------------------------------------
def test_related_texts_have_higher_cosine_than_unrelated_latin(lexical_embedder):
    base = "microchannel cooling system for electric vehicle battery with coolant"
    related = "microchannel coolant cooling channels for a vehicle battery pack"
    unrelated = "wireless charging coil alignment controller and position sensor"

    cos_related = _cos(
        lexical_embedder.embed_one(base, tenant_id="t1"),
        lexical_embedder.embed_one(related, tenant_id="t1"),
    )
    cos_unrelated = _cos(
        lexical_embedder.embed_one(base, tenant_id="t1"),
        lexical_embedder.embed_one(unrelated, tenant_id="t1"),
    )
    assert cos_related > cos_unrelated, (
        f"lexical semantics broken: related cos {cos_related:.4f} must exceed "
        f"unrelated cos {cos_unrelated:.4f} (this is the property mock lacks)"
    )


def test_related_texts_have_higher_cosine_than_unrelated_cjk(lexical_embedder):
    # CJK pair: shared 中文 terminology must yield higher cosine, proving the
    # bigram tokenization captures term overlap (no whitespace in CJK).
    base = "電動車充電站之充電管理方法 伺服器 能源管理方案 負載管理 第一參考值"
    related = "電動車充電站 充電管理 伺服器 負載管理 能源管理方案 特定事件"
    unrelated = "微流道板 電池模組 冷卻結構 非均勻截面 直接散熱"

    cos_related = _cos(
        lexical_embedder.embed_one(base, tenant_id="t1"),
        lexical_embedder.embed_one(related, tenant_id="t1"),
    )
    cos_unrelated = _cos(
        lexical_embedder.embed_one(base, tenant_id="t1"),
        lexical_embedder.embed_one(unrelated, tenant_id="t1"),
    )
    assert cos_related > cos_unrelated, (
        f"CJK bigram semantics broken: related cos {cos_related:.4f} must exceed "
        f"unrelated cos {cos_unrelated:.4f}"
    )


# ---------------------------------------------------------------------------
# H-3 tenant isolation, with within-tenant ordering preserved.
# ---------------------------------------------------------------------------
def test_h3_same_text_different_tenant_yields_different_vector(lexical_embedder):
    text = "a method for predicting battery degradation using a model"
    va = lexical_embedder.embed_one(text, tenant_id="tenant_a")
    vb = lexical_embedder.embed_one(text, tenant_id="tenant_b")
    assert va != vb, "H-3: same text under two tenants must differ (tenant salt)"
    # Load-bearing: the salt must actually move the vector apart, not flip one
    # bucket that normalises away. Distinct salts permute buckets independently,
    # so cosine should be far below 1.0.
    sim = _cos(va, vb)
    assert sim < 0.9999, f"cross-tenant cosine {sim:.6f} must be < 1.0 (H-3)"


def test_h3_within_tenant_ordering_is_preserved(lexical_embedder):
    """The tenant salt permutes buckets CONSISTENTLY for all of a tenant's
    texts, so the related>unrelated ordering must still hold inside ONE tenant.
    """
    base = "microchannel cooling system for electric vehicle battery coolant"
    related = "microchannel coolant cooling for a vehicle battery pack"
    unrelated = "wireless charging coil alignment position sensor controller"

    for tenant in ("tenant_a", "tenant_b"):
        cos_related = _cos(
            lexical_embedder.embed_one(base, tenant_id=tenant),
            lexical_embedder.embed_one(related, tenant_id=tenant),
        )
        cos_unrelated = _cos(
            lexical_embedder.embed_one(base, tenant_id=tenant),
            lexical_embedder.embed_one(unrelated, tenant_id=tenant),
        )
        assert cos_related > cos_unrelated, (
            f"within {tenant}: related {cos_related:.4f} must exceed "
            f"unrelated {cos_unrelated:.4f} — salt must preserve relative sims"
        )


# ---------------------------------------------------------------------------
# Retrieval-level proof: the overlapping patent ranks first.
# ---------------------------------------------------------------------------
@pytest.fixture
def lexical_rag(monkeypatch):
    """Pin lexical + rebuild the module singletons (_embedder / _store) so
    index_patent/retrieve run under the lexical backend with a clean store.

    Mirrors the reset idiom: settings.EMBEDDING_BACKEND is monkeypatched, then
    rag._embedder and rag._store are rebuilt and restored on teardown.
    """
    orig_embedder = rag._embedder
    orig_store = rag._store
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "lexical")
    rag.clear_embedding_cache()
    rag._embedder = rag.Embedder()
    rag._store = rag.MemoryVectorStore()
    assert rag._embedder.backend == "lexical"
    yield rag
    rag._embedder = orig_embedder
    rag._store = orig_store
    rag.clear_embedding_cache()


def _patent(pno, title, abstract, claims, jurisdiction="US"):
    from datetime import datetime

    from backend.shared.models import Patent

    return Patent(
        patent_no=pno,
        title=title,
        abstract=abstract,
        claims=claims,
        jurisdiction=jurisdiction,
        publication_date=datetime(2020, 1, 1),
        is_local=False,
    )


def test_retrieval_ranks_overlapping_patent_first(lexical_rag):
    tenant = "tenant_a"
    p_micro = _patent(
        "US-MICRO",
        "Microchannel cooling system for electric vehicle battery",
        "A cooling system with microchannels of non-uniform cross-section to "
        "induce turbulent coolant flow in an electric vehicle battery pack.",
        [
            "A cooling system comprising a base plate having a plurality of "
            "microchannels with non-uniform cross-section and a coolant manifold."
        ],
    )
    p_heat = _patent(
        "US-HEAT",
        "Solid copper heat sink for power electronics",
        "A solid copper heat sink with parallel extruded fins for conductive "
        "cooling of power electronics.",
        ["A heat sink comprising a solid copper block with parallel extruded fins."],
    )
    p_wireless = _patent(
        "US-WIFI",
        "Wireless charging coil alignment system",
        "A wireless charging system with active coil alignment and a position "
        "sensor for misalignment tolerance.",
        [
            "A wireless charging system comprising a transmitting coil array and a "
            "position sensor and a controller."
        ],
    )

    lexical_rag.index_patent(tenant, p_micro)
    lexical_rag.index_patent(tenant, p_heat)
    lexical_rag.index_patent(tenant, p_wireless)

    # Query overlaps ONLY the microchannel patent's terminology.
    query = "microchannel coolant cooling channels for electric vehicle battery pack"
    hits = lexical_rag.retrieve(tenant, query, top_k=5)
    assert hits, "retrieve returned no hits"
    assert hits[0].patent_no == "US-MICRO", (
        "lexical retrieval failed to rank the term-overlapping patent first; "
        f"top hits = {[h.patent_no for h in hits]!r}"
    )


def test_retrieval_ranks_overlapping_patent_first_cjk(lexical_rag):
    tenant = "tenant_a"
    p_charge = _patent(
        "TW-CHARGE",
        "電動車充電站之充電管理方法及系統",
        "一種電動車充電站之充電管理方法，伺服器執行能源管理方案以對充電場域中之"
        "電動車充電站執行負載管理作業，並依據裝置資料決定可變動之第一參考值。",
        [
            "一種電動車充電站之充電管理方法，由伺服器執行能源管理方案，取得第一特定"
            "電動車充電站之第一裝置資料，並依據第一裝置資料決定第一參考值。"
        ],
        jurisdiction="TW",
    )
    p_cool = _patent(
        "TW-COOL",
        "電動車電池模組冷卻結構",
        "一種電動車電池模組冷卻結構，包括具備非均勻截面之微流道板，提供電池芯之直接散熱。",
        ["一種電池冷卻結構，包含基板，其上設置複數個微流道，每一微流道沿長度方向具有不均勻截面。"],
        jurisdiction="TW",
    )

    lexical_rag.index_patent(tenant, p_charge)
    lexical_rag.index_patent(tenant, p_cool)

    query = "電動車充電站 充電管理 伺服器 能源管理方案 負載管理 第一參考值"
    hits = lexical_rag.retrieve(tenant, query, top_k=5)
    assert hits, "retrieve returned no hits"
    assert hits[0].patent_no == "TW-CHARGE", (
        "CJK lexical retrieval failed to rank the term-overlapping patent first; "
        f"top hits = {[h.patent_no for h in hits]!r}"
    )


# ---------------------------------------------------------------------------
# Observability: stats() reflects the lexical backend.
# ---------------------------------------------------------------------------
def test_stats_reports_lexical_backend(lexical_rag):
    s = lexical_rag.stats()
    assert s["embedding_backend"] == "lexical"
    assert s["embedding_dim"] == settings.EMBEDDING_DIM
