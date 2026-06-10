"""Agent H (Day 13H) — vector-store robustness + Q5 RBAC isolation hardening.

Extends test_vector_store_contract.py with the production-grade edge cases the
shared contract must survive on EVERY backend:

  * dim-mismatch guard (memory store now raises VectorDimMismatch instead of a
    raw numpy broadcast error; Qdrant enforces this server-side),
  * empty corpus / empty batch upsert,
  * duplicate chunk_id upsert overwrites rather than duplicating,
  * unicode / CJK chunk text round-trips intact,
  * a query that matches nothing under a metadata filter returns [],
  * Q5 strict tenant isolation: a tenant can NEVER retrieve another tenant's
    vectors even when the query vector is IDENTICAL to the other tenant's chunk
    vector (the strongest isolation assertion — pure namespace separation, not
    score separation).

The memory backend is always exercised; Qdrant joins when reachable (skips
cleanly otherwise — keeps CI green with no container).
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.ai_engine.rag import (
    Chunk,
    MemoryVectorStore,
    QdrantVectorStore,
    VectorDimMismatch,
    VectorStore,
)
from backend.shared.config import settings
from tests.unit.qdrant_isolation import TenantNamespacedStore


DIM = 8


def _vec(seed: int, dim: int = DIM) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32).tolist()


def _chunk(chunk_id, patent_no="US1", section="claim_1", claim_no=1,
           text="t", jurisdiction="US", metadata=None):
    return Chunk(
        chunk_id=chunk_id, patent_no=patent_no, section=section,
        claim_no=claim_no, text=text, jurisdiction=jurisdiction,
        metadata=metadata or {},
    )


def _make_qdrant_or_skip() -> VectorStore:
    # Tenant ids are namespaced per-run: the shared dev Qdrant holds REAL demo
    # collections (tenant_a/tenant_b at bge-m3's 1024 dims) that these 8-dim
    # toy vectors must never collide with (the dim-drift guard would refuse).
    try:
        store = QdrantVectorStore(url=settings.QDRANT_URL, dim=DIM)
        store._client.get_collections()
    except Exception as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"Qdrant not reachable at {settings.QDRANT_URL}: {exc}")
    return TenantNamespacedStore(store)


_STORE_FACTORIES = [
    pytest.param(MemoryVectorStore, id="memory"),
    pytest.param(_make_qdrant_or_skip, id="qdrant"),
]


@pytest.fixture(params=_STORE_FACTORIES)
def store(request) -> VectorStore:
    s = request.param()
    yield s
    if isinstance(s, TenantNamespacedStore):
        s.cleanup()


# ---------------------------------------------------------------------------
# Empty-corpus / empty-batch behaviour
# ---------------------------------------------------------------------------

def test_empty_batch_upsert_is_noop(store):
    store.upsert("tenant_e", [], [])
    assert store.search("tenant_e", _vec(1), top_k=5) == []
    assert store.list_claim_chunks("tenant_e", "US1") == []


def test_search_before_any_upsert_is_empty(store):
    # A brand-new store with nothing indexed returns [] (not a crash).
    assert store.search("never_seen", _vec(2), top_k=5) == []


# ---------------------------------------------------------------------------
# Duplicate chunk_id overwrites (idempotent re-index)
# ---------------------------------------------------------------------------

def test_duplicate_chunk_id_overwrites(store):
    store.upsert("tenant_dup", [_chunk("c1", text="first")], [_vec(3)])
    store.upsert("tenant_dup", [_chunk("c1", text="second")], [_vec(3)])
    hits = store.search("tenant_dup", _vec(3), top_k=5)
    # Exactly ONE chunk with id c1 — the re-upsert overwrote, did not duplicate.
    ids = [h[0].chunk_id for h in hits]
    assert ids.count("c1") == 1
    assert hits[0][0].text == "second"


# ---------------------------------------------------------------------------
# Unicode / CJK payload round-trips intact
# ---------------------------------------------------------------------------

def test_cjk_text_round_trips(store):
    cjk = "一種電動車充電站之充電管理方法，依據第一參考值判斷特定事件。"
    store.upsert("tenant_cjk", [_chunk("z1", text=cjk, metadata={"族": "甲"})],
                 [_vec(4)])
    hits = store.search("tenant_cjk", _vec(4), top_k=5)
    assert hits[0][0].text == cjk
    assert hits[0][0].metadata.get("族") == "甲"


# ---------------------------------------------------------------------------
# Metadata filter with zero matches returns []
# ---------------------------------------------------------------------------

def test_metadata_filter_no_match_returns_empty(store):
    store.upsert("tenant_nf", [_chunk("a", jurisdiction="US")], [_vec(5)])
    hits = store.search("tenant_nf", _vec(5), top_k=5,
                        metadata_filter={"jurisdiction": "JP"})
    assert hits == []


# ---------------------------------------------------------------------------
# Q5 RBAC — strongest isolation: identical query vector still cannot cross.
# ---------------------------------------------------------------------------

def test_identical_vector_cannot_cross_tenants(store):
    """Even when tenant_b queries with the EXACT vector of tenant_a's chunk,
    tenant_a's chunk must remain invisible — isolation is namespace-based, not
    score-based, so a similarity-oracle attack cannot leak across tenants."""
    shared = _vec(42)
    store.upsert("tenant_iso_a", [_chunk("secret_a", patent_no="USA")], [shared])
    store.upsert("tenant_iso_b", [_chunk("b_only", patent_no="USB")], [_vec(7)])

    b_hits = store.search("tenant_iso_b", shared, top_k=5)
    b_ids = {h[0].chunk_id for h in b_hits}
    assert "secret_a" not in b_ids
    # tenant_b only ever sees its own chunk.
    assert b_ids <= {"b_only"}


def test_list_claim_chunks_is_tenant_scoped(store):
    store.upsert("tenant_lc_a", [_chunk("a1", patent_no="USX", claim_no=1)], [_vec(8)])
    store.upsert("tenant_lc_b", [_chunk("b1", patent_no="USX", claim_no=1)], [_vec(9)])
    # Same patent_no in both tenants, but list_claim_chunks must not leak.
    a_claims = store.list_claim_chunks("tenant_lc_a", "USX")
    assert {c.chunk_id for c in a_claims} == {"a1"}
    b_claims = store.list_claim_chunks("tenant_lc_b", "USX")
    assert {c.chunk_id for c in b_claims} == {"b1"}


# ---------------------------------------------------------------------------
# Dim-mismatch guard — memory store raises a clear contract error.
# (Qdrant enforces dim server-side / via _should_drop_for_dim; the memory store
#  is the one that previously leaked a raw numpy broadcast error, so this guard
#  is asserted on the memory backend specifically.)
# ---------------------------------------------------------------------------

def test_memory_upsert_dim_mismatch_raises():
    s = MemoryVectorStore()
    s.upsert("t", [_chunk("c1")], [_vec(1, dim=8)])
    with pytest.raises(VectorDimMismatch) as exc:
        s.upsert("t", [_chunk("c2")], [_vec(2, dim=16)])
    assert "dim mismatch" in str(exc.value)


def test_memory_search_dim_mismatch_raises():
    s = MemoryVectorStore()
    s.upsert("t", [_chunk("c1")], [_vec(1, dim=8)])
    with pytest.raises(VectorDimMismatch):
        s.search("t", _vec(2, dim=4), top_k=5)


def test_memory_dim_established_on_first_vector():
    s = MemoryVectorStore()
    assert s._dim is None
    s.upsert("t", [_chunk("c1")], [_vec(1, dim=12)])
    assert s._dim == 12
    # Same-dim follow-up upsert is fine.
    s.upsert("t", [_chunk("c2")], [_vec(2, dim=12)])
    assert len(s.search("t", _vec(1, dim=12), top_k=5)) == 2


def test_memory_mixed_dim_within_one_batch_is_atomic():
    """A batch where vectors disagree on dim must fail WITHOUT partially
    writing — the first vector establishes dim, the second trips the guard,
    and NOTHING from the batch is indexed (atomic validation)."""
    s = MemoryVectorStore()
    with pytest.raises(VectorDimMismatch):
        s.upsert("t", [_chunk("c1"), _chunk("c2")],
                 [_vec(1, dim=8), _vec(2, dim=10)])
    # Nothing was written — the tenant is still empty.
    assert s.search("t", _vec(1, dim=8), top_k=5) == []
    assert s.stats()["total_chunks"] == 0
