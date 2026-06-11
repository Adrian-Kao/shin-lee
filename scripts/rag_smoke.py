"""rag_smoke.py — prove the RAG is real, not SHA-256 noise.

Indexes the demo patents (backend/patent_db/seed.py) into WHATEVER backend the
environment selects, then runs the retrieval-eval harness and prints the REAL
recall@5 / MRR plus rag.stats() (backend, embedding_backend, embedding_dim).

  - Defaults (VECTOR_BACKEND=memory, EMBEDDING_BACKEND=mock): reproduces the
    ~0.50 mock baseline. The numbers are NOT a quality signal (mock embeddings
    are deterministic SHA-256 noise) — this run only proves the wiring.
  - VECTOR_BACKEND=qdrant EMBEDDING_BACKEND=bge-m3: produces REAL numbers
    against a live Qdrant + bge-m3 model.

Usage:
    python scripts/rag_smoke.py
    VECTOR_BACKEND=qdrant EMBEDDING_BACKEND=bge-m3 python scripts/rag_smoke.py

Fails with a clear, actionable message (not a stack trace) when Qdrant is
configured but unreachable, or when bge-m3 is configured but its deps are
missing. Exit code 0 on success, non-zero on a configuration/infra failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python scripts/rag_smoke.py` from anywhere by putting the repo root on
# sys.path (mirrors scripts/anthropic_smoke.py).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# config.py refuses to boot with the published placeholder JWT_SECRET (even in
# mock mode). This smoke script issues NO JWTs (it calls the RAG layer
# directly), so any non-placeholder value unblocks the import. setdefault keeps
# an operator's real JWT_SECRET if they already exported one. We deliberately
# do NOT touch VECTOR_BACKEND / EMBEDDING_BACKEND — reading whatever the env
# selects is the entire point of this script.
os.environ.setdefault("JWT_SECRET", "rag-smoke-no-jwt-issued-here-32bytes-placeholder")

from backend.shared.config import settings  # noqa: E402


def _preflight() -> None:
    """Fail fast with actionable guidance if the selected real backends can't
    be stood up in THIS environment. Returns normally for mock/memory."""
    # --- Qdrant reachability -------------------------------------------------
    if settings.VECTOR_BACKEND == "qdrant":
        try:
            from qdrant_client import QdrantClient
        except Exception as exc:
            print(
                "ERROR: VECTOR_BACKEND=qdrant but qdrant-client is not "
                f"importable ({type(exc).__name__}: {exc}).\n"
                "  pip install qdrant-client",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
        try:
            client = QdrantClient(url=settings.QDRANT_URL, timeout=5.0)
            client.get_collections()  # forces a real round-trip
        except Exception as exc:
            print(
                f"ERROR: VECTOR_BACKEND=qdrant but Qdrant is unreachable at "
                f"{settings.QDRANT_URL}\n"
                f"  underlying error: {type(exc).__name__}: {exc}\n\n"
                "Bring the stack up first:\n"
                "    bash scripts/start_rag_stack.sh\n"
                "or point QDRANT_URL at your running instance.",
                file=sys.stderr,
            )
            raise SystemExit(3) from exc

    # --- bge-m3 importability ------------------------------------------------
    if settings.EMBEDDING_BACKEND == "bge-m3":
        try:
            import sentence_transformers  # noqa: F401
        except Exception as exc:
            print(
                "ERROR: EMBEDDING_BACKEND=bge-m3 but sentence-transformers / "
                f"torch is not importable ({type(exc).__name__}: {exc}).\n"
                "  pip install 'sentence-transformers>=2.7' torch\n"
                "Then prefetch the model:\n"
                "    python scripts/prefetch_bge_m3.py",
                file=sys.stderr,
            )
            raise SystemExit(4) from exc


def main() -> int:
    print("=" * 72)
    print("RAG smoke / real-backend eval")
    print("=" * 72)
    print(f"VECTOR_BACKEND    : {settings.VECTOR_BACKEND}")
    print(f"EMBEDDING_BACKEND : {settings.EMBEDDING_BACKEND}")
    print(f"QDRANT_URL        : {settings.QDRANT_URL}")
    print("-" * 72)

    _preflight()

    # Import AFTER preflight so the eager Embedder()/_make_store() construction
    # in rag.py (which would raise on a missing model / unreachable Qdrant)
    # happens with our friendly guards already passed.
    from backend.ai_engine import rag, retrieval_eval

    # Index the demo corpus into the eval tenant via the public RAG API, then
    # score. evaluate() does the indexing itself, so just call it.
    report = retrieval_eval.evaluate(k=5)
    stats = rag.stats()

    print(f"indexed backend   : {stats.get('backend')}")
    print(f"embedding backend : {stats.get('embedding_backend')}")
    print(f"embedding dim     : {stats.get('embedding_dim')}")
    print(f"total chunks      : {stats.get('total_chunks')}")
    print("-" * 72)
    print(f"eval cases        : {report['n_cases']}")
    print(f"aggregate recall@5: {report['recall@k']:.3f}")
    print(f"aggregate MRR     : {report['mrr']:.3f}")
    print("-" * 72)
    for pc in report["per_case"]:
        mark = " " if pc["hit"] else "x"
        tops = ",".join(pc["top_patent_nos"][:3])
        print(f"{mark} {pc['id']:<30} recall@5={pc['recall@k']:.3f} mrr={pc['mrr']:.3f}  {tops}")
    print("-" * 72)

    if report["embedding_backend"] == "mock":
        print("NOTE: mock embeddings are deterministic SHA-256 noise. These")
        print("      numbers prove the index->retrieve->score WIRING only, NOT")
        print("      RAG quality. Flip to EMBEDDING_BACKEND=bge-m3 (with a live")
        print("      Qdrant) for real numbers — target recall@5 >= 0.70 (Q6).")
    else:
        target = retrieval_eval.PROD_TARGET_RECALL_AT_5
        verdict = "MET" if report["recall@k"] >= target else "BELOW TARGET"
        print(
            f"REAL backend: recall@5 {report['recall@k']:.3f} vs Q6 target "
            f"{target:.2f} -> {verdict}"
        )
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
