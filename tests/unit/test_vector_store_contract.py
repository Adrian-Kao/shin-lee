"""Q7 — formal VectorStore contract + dim-drift data-loss guard.

The Q7 decision is "Milvus/Qdrant self-host, swappable interface". These tests
make swappability *provable*: the same assertions run against any VectorStore
implementation, so a backend cannot silently drift from the shared contract.

- `MemoryVectorStore` is ALWAYS exercised.
- `QdrantVectorStore` is exercised only when a real Qdrant is reachable at
  `settings.QDRANT_URL`; otherwise the parametrization is skipped (so CI with
  no Qdrant container stays green).
- The dim-drift guard is tested via the pure helper `_should_drop_for_dim`,
  needing no Qdrant at all.
"""
from __future__ import annotations

import abc

import numpy as np
import pytest

from backend.ai_engine.rag import (
    Chunk,
    MemoryVectorStore,
    QdrantVectorStore,
    VectorStore,
    _should_drop_for_dim,
)
from backend.shared.config import settings
from tests.unit.qdrant_isolation import TenantNamespacedStore


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

DIM = 8  # tiny vectors keep the test fast and dim-agnostic


def _vec(seed: int) -> list[float]:
    """Deterministic unit-ish vector keyed by `seed`."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(DIM).astype(np.float32).tolist()


def _chunk(chunk_id, patent_no, section, claim_no, text="t", jurisdiction="US", metadata=None):
    return Chunk(
        chunk_id=chunk_id,
        patent_no=patent_no,
        section=section,
        claim_no=claim_no,
        text=text,
        jurisdiction=jurisdiction,
        metadata=metadata or {},
    )


def _make_qdrant_or_skip() -> VectorStore:
    """Construct a QdrantVectorStore against the configured URL, or skip.

    The returned store namespaces tenant ids per-run (TenantNamespacedStore):
    the shared dev Qdrant holds REAL demo collections for tenant_a/tenant_b
    (bge-m3, 1024-dim) which the 8-dim test vectors must never touch — the
    dim-drift guard would (rightly) refuse. We also verify reachability by
    issuing a cheap call and skipping on any connection error.
    """
    try:
        store = QdrantVectorStore(url=settings.QDRANT_URL, dim=DIM)
        # Force a real round-trip so an unreachable server skips rather than
        # failing later mid-assertion.
        store._client.get_collections()
    except Exception as exc:  # pragma: no cover - depends on env
        pytest.skip(f"Qdrant not reachable at {settings.QDRANT_URL}: {exc}")
    return TenantNamespacedStore(store)


# Each entry is a zero-arg factory returning a fresh store instance.
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
# Shared contract suite — runs identically against every backend
# ---------------------------------------------------------------------------

def test_upsert_search_round_trip(store):
    chunks = [_chunk("c1", "US1", "claim_1", 1), _chunk("c2", "US1", "abstract", None)]
    store.upsert("tenant_a", chunks, [_vec(1), _vec(2)])

    hits = store.search("tenant_a", _vec(1), top_k=5)
    assert isinstance(hits, list)
    assert hits, "round-trip search returned no hits"
    # Contract: list[tuple[Chunk, float]], sorted by descending score.
    for ch, score in hits:
        assert isinstance(ch, Chunk)
        assert isinstance(score, float)
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    assert {h[0].chunk_id for h in hits} == {"c1", "c2"}


def test_tenant_isolation(store):
    store.upsert("tenant_a", [_chunk("a1", "US1", "claim_1", 1)], [_vec(10)])
    store.upsert("tenant_b", [_chunk("b1", "US2", "claim_1", 1)], [_vec(11)])

    a_hits = store.search("tenant_a", _vec(10), top_k=5)
    b_hits = store.search("tenant_b", _vec(11), top_k=5)

    assert {h[0].chunk_id for h in a_hits} == {"a1"}
    assert {h[0].chunk_id for h in b_hits} == {"b1"}
    # tenant_a's chunk is invisible to tenant_b and vice versa.
    assert "b1" not in {h[0].chunk_id for h in a_hits}
    assert "a1" not in {h[0].chunk_id for h in b_hits}


def test_empty_tenant_search_returns_empty(store):
    assert store.search("nobody_here", _vec(99), top_k=5) == []


def test_metadata_filter_honoured(store):
    store.upsert(
        "tenant_f",
        [
            _chunk("us", "P1", "claim_1", 1, jurisdiction="US"),
            _chunk("tw", "P2", "claim_1", 1, jurisdiction="TW"),
        ],
        [_vec(20), _vec(21)],
    )
    hits = store.search("tenant_f", _vec(20), top_k=5, metadata_filter={"jurisdiction": "US"})
    assert {h[0].chunk_id for h in hits} == {"us"}, "filter must drop non-US chunks"


def test_metadata_filter_matches_nested_metadata(store):
    store.upsert(
        "tenant_g",
        [
            _chunk("x", "P1", "claim_1", 1, metadata={"family": "alpha"}),
            _chunk("y", "P1", "claim_2", 2, metadata={"family": "beta"}),
        ],
        [_vec(30), _vec(31)],
    )
    hits = store.search("tenant_g", _vec(30), top_k=5, metadata_filter={"family": "alpha"})
    assert {h[0].chunk_id for h in hits} == {"x"}


def test_list_claim_chunks_only_claims_sorted(store):
    chunks = [
        _chunk("c3", "US9", "claim_3", 3),
        _chunk("abs", "US9", "abstract", None),
        _chunk("c1", "US9", "claim_1", 1),
        _chunk("spec", "US9", "spec_para_1", None),
        _chunk("c2", "US9", "claim_2", 2),
        _chunk("other", "US_OTHER", "claim_1", 1),  # different patent
    ]
    store.upsert("tenant_c", chunks, [_vec(i) for i in range(len(chunks))])

    claims = store.list_claim_chunks("tenant_c", "US9")
    # Only claim chunks (claim_no is not None) for US9, ascending by claim_no.
    assert [c.claim_no for c in claims] == [1, 2, 3]
    assert all(c.claim_no is not None for c in claims)
    assert all(c.patent_no == "US9" for c in claims)


def test_list_claim_chunks_unindexed_patent_returns_empty(store):
    store.upsert("tenant_d", [_chunk("c1", "US1", "claim_1", 1)], [_vec(40)])
    assert store.list_claim_chunks("tenant_d", "NOT_INDEXED") == []
    assert store.list_claim_chunks("no_tenant", "US1") == []


# ---------------------------------------------------------------------------
# ABC registration / instantiability
# ---------------------------------------------------------------------------

def test_concrete_classes_are_vectorstore_subclasses():
    assert issubclass(MemoryVectorStore, VectorStore)
    assert issubclass(QdrantVectorStore, VectorStore)
    assert issubclass(VectorStore, abc.ABC)


def test_abc_abstractmethods_fully_implemented():
    # If any abstractmethod were unimplemented, the class would carry it in
    # __abstractmethods__ and instantiation would raise TypeError.
    expected = {"upsert", "search", "stats", "list_claim_chunks"}
    assert expected <= set(VectorStore.__abstractmethods__)
    assert MemoryVectorStore.__abstractmethods__ == frozenset()
    assert QdrantVectorStore.__abstractmethods__ == frozenset()
    # Memory store instantiates with no external deps; Qdrant is dep-heavy so
    # we only assert it carries no leftover abstractmethods (checked above).
    MemoryVectorStore()


def test_partial_impl_cannot_instantiate():
    class Incomplete(VectorStore):
        def upsert(self, tenant_id, chunks, vectors):  # noqa: D401
            ...
        # search / stats / list_claim_chunks intentionally missing

    with pytest.raises(TypeError):
        Incomplete()


# ---------------------------------------------------------------------------
# Dim-drift data-loss guard (Qdrant-free, via the pure helper)
# ---------------------------------------------------------------------------

def test_dim_guard_no_drop_when_dims_match():
    assert _should_drop_for_dim(384, 384, allow_reindex=False) is False
    assert _should_drop_for_dim(384, 384, allow_reindex=True) is False


def test_dim_guard_refuses_by_default_on_mismatch():
    with pytest.raises(RuntimeError) as exc:
        _should_drop_for_dim(384, 1024, allow_reindex=False)
    msg = str(exc.value)
    assert "dim mismatch" in msg
    assert "384" in msg and "1024" in msg
    assert "QDRANT_ALLOW_REINDEX" in msg


def test_dim_guard_allows_drop_when_opted_in():
    assert _should_drop_for_dim(384, 1024, allow_reindex=True) is True
    assert _should_drop_for_dim(1024, 384, allow_reindex=True) is True
