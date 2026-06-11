"""Integration tests for the REAL RAG backends (Qdrant + bge-m3).

Three tiers, mirroring tests/unit/test_vector_store_contract.py's skip pattern:

  1. Live Qdrant end-to-end — SKIPPED unless a real Qdrant answers at
     settings.QDRANT_URL. Exercises upsert/retrieve round-trip, tenant
     isolation, and the dim-drift guard against an actual server.
  2. bge-m3 embeddings — SKIPPED unless sentence-transformers/torch import.
     Asserts dim==1024 and that distinct texts produce distinct vectors.
  3. Backend SELECTION wiring — ALWAYS RUNS. Monkeypatches the QdrantClient
     constructor to a stub (no server needed) and asserts that
     VECTOR_BACKEND=qdrant routes _make_store() to a QdrantVectorStore with
     correct per-tenant collection naming, and that EMBEDDING_BACKEND selection
     picks the right Embedder branch.

The live tiers need infra this CI box doesn't have, so they skip cleanly; the
wiring tier proves the selection logic without any server or model.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from backend.ai_engine.rag import (
    Chunk,
    Embedder,
    MemoryVectorStore,
    QdrantVectorStore,
    _should_drop_for_dim,
)
from backend.shared.config import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _qdrant_or_skip(dim: int) -> QdrantVectorStore:
    """Construct a QdrantVectorStore against the live URL, or skip the test."""
    try:
        store = QdrantVectorStore(url=settings.QDRANT_URL, dim=dim)
        store._client.get_collections()  # forces a real round-trip
    except Exception as exc:  # pragma: no cover - depends on env
        pytest.skip(f"Qdrant not reachable at {settings.QDRANT_URL}: {exc}")
    return store


def _sentence_transformers_available() -> bool:
    """Probe importability in a SUBPROCESS.

    On some platforms (notably Windows here) importing sentence-transformers
    drags in torch, whose DLL load can trigger a native access-violation that
    a normal try/except cannot catch — it would crash the whole pytest run.
    Doing the import in a throwaway subprocess isolates that fatal case: a
    non-zero exit (clean ImportError/OSError OR a native crash) => unavailable,
    and we skip cleanly without endangering this process.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import sentence_transformers"],
            capture_output=True,
            timeout=120,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _bge_m3_model_cached() -> bool:
    """True when the bge-m3 weights are fully present in the local HF cache.

    The Embedder loads offline-first (rag.py `_load_st` passes
    ``local_files_only=True`` when the snapshot is cached), so the only way
    this test can run deterministically — on CI boxes and behind corporate
    firewalls alike — is when the model has been prefetched
    (``python scripts/prefetch_bge_m3.py``). If it has not, skip instead of
    failing on a hub download that this environment may not be able to make.
    """
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(settings.EMBEDDING_MODEL, local_files_only=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tier 1 — live Qdrant end-to-end (skips with no server)
# ---------------------------------------------------------------------------

DIM = 8  # tiny vectors keep the live test fast + dim-agnostic


def _vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(DIM).astype(np.float32).tolist()


def test_qdrant_round_trip_and_tenant_isolation():
    store = _qdrant_or_skip(DIM)
    # Unique tenants per run so repeated runs against a persistent Qdrant don't
    # collide. (collection name = patentmind_<tenant_id>)
    import uuid

    suffix = uuid.uuid4().hex[:8]
    ta = f"rag_real_a_{suffix}"
    tb = f"rag_real_b_{suffix}"
    try:
        store.upsert(
            ta,
            [_chunk("a1", "US1", "claim_1", 1), _chunk("a2", "US1", "abstract", None)],
            [_vec(1), _vec(2)],
        )
        store.upsert(tb, [_chunk("b1", "US2", "claim_1", 1)], [_vec(3)])

        a_hits = store.search(ta, _vec(1), top_k=5)
        assert a_hits, "round-trip returned no hits"
        assert {h[0].chunk_id for h in a_hits} == {"a1", "a2"}
        # scores descending
        scores = [s for _, s in a_hits]
        assert scores == sorted(scores, reverse=True)

        # tenant isolation: tenant_a never sees tenant_b's chunk
        assert "b1" not in {h[0].chunk_id for h in a_hits}
        b_hits = store.search(tb, _vec(3), top_k=5)
        assert {h[0].chunk_id for h in b_hits} == {"b1"}

        # claim-chunk listing round-trips
        claims = store.list_claim_chunks(ta, "US1")
        assert [c.claim_no for c in claims] == [1]
    finally:
        # Clean up the per-run collections so the persistent volume stays tidy.
        for t in (ta, tb):
            try:
                store._client.delete_collection(collection_name=store._coll(t))
            except Exception:
                pass


def test_qdrant_dim_drift_guard_live():
    """A second store with a DIFFERENT dim against an existing collection must
    hit the dim-drift guard (refuse by default)."""
    store = _qdrant_or_skip(DIM)
    import uuid

    t = f"rag_real_drift_{uuid.uuid4().hex[:8]}"
    try:
        store.upsert(t, [_chunk("c1", "US1", "claim_1", 1)], [_vec(1)])
        # New store, different dim, no reindex opt-in -> RuntimeError from the
        # guard when it tries to ensure the (now dim-mismatched) collection.
        other = QdrantVectorStore(url=settings.QDRANT_URL, dim=DIM + 4)
        with pytest.raises(RuntimeError) as exc:
            other.upsert(
                t, [_chunk("c2", "US1", "claim_2", 2)], [list(np.zeros(DIM + 4, dtype=np.float32))]
            )
        assert "dim mismatch" in str(exc.value)
    finally:
        try:
            store._client.delete_collection(collection_name=store._coll(t))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tier 2 — bge-m3 embeddings (skips if sentence-transformers unimportable)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _sentence_transformers_available(),
    reason="sentence-transformers / torch not importable in this environment",
)
@pytest.mark.skipif(
    not _bge_m3_model_cached(),
    reason="bge-m3 weights not in local HF cache — run scripts/prefetch_bge_m3.py",
)
def test_bge_m3_embedder_dim_and_distinctness(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "bge-m3")
    emb = Embedder()  # eager-loads the model
    assert emb.dim == 1024, f"bge-m3 must report 1024 dims, got {emb.dim}"

    v1 = emb.embed_one("a microchannel cooling system for EV batteries")
    v2 = emb.embed_one("a wireless charging coil alignment controller")
    assert len(v1) == 1024 and len(v2) == 1024
    # Distinct inputs -> distinct vectors (not the degenerate all-equal case).
    assert v1 != v2
    # And they should not be near-identical: cosine well below 1.0.
    a, b = np.array(v1), np.array(v2)
    cos = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    assert cos < 0.999, f"distinct texts gave near-identical vectors (cos={cos})"


# ---------------------------------------------------------------------------
# Tier 3 — backend SELECTION wiring (ALWAYS runs; no server / model needed)
# ---------------------------------------------------------------------------


class _StubQdrantClient:
    """Minimal stand-in for qdrant_client.QdrantClient — records the URL and
    answers the few calls _make_store()/__init__ make, so we can assert the
    selection wiring without a live server."""

    last_url = None

    def __init__(self, url=None, **kwargs):
        type(self).last_url = url

    def get_collections(self):  # pragma: no cover - not exercised here
        class _R:
            collections = []

        return _R()


def test_make_store_selects_qdrant_when_configured(monkeypatch):
    # Stub the constructor the lazy import inside QdrantVectorStore.__init__
    # resolves: `from qdrant_client import QdrantClient`.
    import qdrant_client

    import backend.ai_engine.rag as rag

    monkeypatch.setattr(qdrant_client, "QdrantClient", _StubQdrantClient)
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "qdrant")

    store = rag._make_store()
    assert isinstance(store, QdrantVectorStore)
    # Per-tenant collection naming holds.
    assert store._coll("tenant_a") == "patentmind_tenant_a"
    assert store._coll("tenant_b") == "patentmind_tenant_b"
    # The configured QDRANT_URL was passed through to the client.
    assert _StubQdrantClient.last_url == settings.QDRANT_URL
    # dim comes from the active embedder (mock default = EMBEDDING_DIM).
    assert store._dim == rag._embedder.dim


def test_make_store_selects_memory_by_default(monkeypatch):
    import backend.ai_engine.rag as rag

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "memory")
    store = rag._make_store()
    assert isinstance(store, MemoryVectorStore)


def test_embedder_backend_selection_mock_vs_bge(monkeypatch):
    # mock branch: no model load, dim from settings.EMBEDDING_DIM.
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "mock")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 384)
    emb = Embedder()
    assert emb.backend == "mock"
    assert emb.dim == 384
    assert emb._st_model is None  # mock must NOT load sentence-transformers

    # bge-m3 branch: constructing eager-loads the model. We don't have the
    # model here, so stub _load_st to prove the BRANCH is taken without a real
    # download, and stub the dim source.
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "bge-m3")

    class _FakeModel:
        def get_sentence_embedding_dimension(self):
            return 1024

    def _fake_load(self):
        self._st_model = _FakeModel()

    monkeypatch.setattr(Embedder, "_load_st", _fake_load)
    emb2 = Embedder()
    assert emb2.backend == "bge-m3"
    assert emb2._st_model is not None  # bge-m3 eager-loaded
    assert emb2.dim == 1024  # dim comes from the model, not EMBEDDING_DIM


def test_should_drop_for_dim_guard_behaviour():
    # Re-assert the pure guard here so the real-backend suite documents it too.
    assert _should_drop_for_dim(384, 384, allow_reindex=False) is False
    assert _should_drop_for_dim(1024, 1024, allow_reindex=True) is False
    with pytest.raises(RuntimeError):
        _should_drop_for_dim(384, 1024, allow_reindex=False)
    assert _should_drop_for_dim(384, 1024, allow_reindex=True) is True
