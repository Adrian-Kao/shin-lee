"""prefetch_bge_m3.py — download + cache the bge-m3 embedding model.

The bge-m3 weights are a multi-GB pull. Doing that lazily on the first real
retrieval request turns a demo into a multi-minute stall (and can fail if the
box has no outbound internet at request time). This script pulls + caches the
model AHEAD of time and prints the resolved embedding dimension (expected
1024) so an operator can confirm the model is wired before flipping
EMBEDDING_BACKEND=bge-m3.

Usage:
    python scripts/prefetch_bge_m3.py
    EMBEDDING_MODEL=BAAI/bge-m3 python scripts/prefetch_bge_m3.py

This is purely an ops convenience — nothing in the app imports it. It honours
EMBEDDING_MODEL (default BAAI/bge-m3) so an operator who points the app at a
different multilingual model prefetches the right one.
"""

from __future__ import annotations

import os
import sys

EXPECTED_DIM = 1024


def main() -> int:
    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # ImportError, OSError (torch/CUDA), etc.
        print(
            "ERROR: could not import sentence-transformers / torch.\n"
            f"  underlying error: {type(exc).__name__}: {exc}\n\n"
            "The real RAG stack needs these installed in THIS environment:\n"
            "    pip install 'sentence-transformers>=2.7' torch\n\n"
            "If you only want the mock/memory POC path you do NOT need this "
            "script — leave EMBEDDING_BACKEND=mock and run scripts/rag_smoke.py.",
            file=sys.stderr,
        )
        return 2

    print(f">> Prefetching embedding model: {model_name}")
    print("   (first run downloads weights to the HF cache; subsequent runs are fast)")
    try:
        model = SentenceTransformer(model_name)
    except Exception as exc:
        print(
            f"ERROR: failed to load model {model_name!r}: "
            f"{type(exc).__name__}: {exc}\n"
            "Check the model id, network access to huggingface.co, and disk space.",
            file=sys.stderr,
        )
        return 3

    dim = model.get_sentence_embedding_dimension()
    # Sanity-encode one string so the forward pass (and any lazy weight load)
    # is exercised here rather than on the first live request.
    vec = model.encode("patent claim limitation", normalize_embeddings=True)
    print(f"OK  model cached: {model_name}")
    print(f"OK  embedding dim: {dim}  (sample vector len={len(vec)})")

    if dim != EXPECTED_DIM:
        print(
            f"NOTE: dim={dim} != expected {EXPECTED_DIM} for bge-m3. If you are "
            f"using a different model this is fine — but set EMBEDDING_DIM={dim} "
            f"in your env so the mock fallback / Qdrant collection sizing match.",
        )
    else:
        print(
            f"OK  dim matches bge-m3 ({EXPECTED_DIM}). The Embedder reports this "
            "automatically; EMBEDDING_DIM only governs the mock backend."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
