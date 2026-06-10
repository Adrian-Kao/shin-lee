"""Per-run tenant namespacing for live-Qdrant unit tests.

Why this exists
---------------
The contract/robustness suites use short hardcoded tenant ids ("tenant_a",
"tenant_dup", ...). Against the in-memory backend that is fine — every test
gets a fresh store. Against a LIVE Qdrant (shared dev container, persistent
volume) it is not:

  * ``patentmind_tenant_a`` / ``patentmind_tenant_b`` are REAL demo
    collections (the demo seed tenants are literally ``tenant_a``/``tenant_b``,
    indexed at bge-m3's 1024 dims). The tests use 8-dim toy vectors, so a raw
    upsert trips the Q7 dim-drift data-loss guard — correctly: dropping the
    demo index to make a unit test pass would destroy real data.
  * Even between two test runs, leftover collections would leak state.

Fix: wrap the store so every tenant id is prefixed with a unique per-fixture
token, and delete exactly the collections this run created on teardown. The
wrapper satisfies the same 4-method VectorStore contract the tests exercise,
so assertions are unchanged and the production code path is fully exercised.
"""
from __future__ import annotations

import uuid


class TenantNamespacedStore:
    """Proxy a VectorStore, prefixing tenant ids with a unique run token."""

    def __init__(self, inner):
        self._inner = inner
        self._prefix = f"pytest_{uuid.uuid4().hex[:10]}_"
        self._tenants: set[str] = set()

    def _ns(self, tenant_id: str) -> str:
        namespaced = self._prefix + tenant_id
        self._tenants.add(namespaced)
        return namespaced

    # -- VectorStore contract -------------------------------------------------
    def upsert(self, tenant_id, chunks, vectors):
        return self._inner.upsert(self._ns(tenant_id), chunks, vectors)

    def search(self, tenant_id, query_vec, top_k=5, metadata_filter=None):
        return self._inner.search(
            self._ns(tenant_id), query_vec, top_k=top_k, metadata_filter=metadata_filter
        )

    def stats(self):
        return self._inner.stats()

    def list_claim_chunks(self, tenant_id, patent_no):
        return self._inner.list_claim_chunks(self._ns(tenant_id), patent_no)

    # -- teardown --------------------------------------------------------------
    def cleanup(self):
        """Delete only the collections this run created. Never touches demo data."""
        for tenant in self._tenants:
            try:
                self._inner._client.delete_collection(
                    collection_name=self._inner._coll(tenant)
                )
            except Exception:
                pass
