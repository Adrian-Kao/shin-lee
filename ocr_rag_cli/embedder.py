from __future__ import annotations

from functools import lru_cache
from typing import Any

from .config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedder() -> tuple[str, Any]:
    if EMBEDDING_MODEL == "BAAI/bge-m3":
        try:
            from FlagEmbedding import BGEM3FlagModel

            return "bge-m3", BGEM3FlagModel(EMBEDDING_MODEL, use_fp16=False)
        except ImportError:
            pass

    from sentence_transformers import SentenceTransformer

    return "sentence-transformers", SentenceTransformer(EMBEDDING_MODEL)


def _to_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        return vector.tolist()
    return list(vector)


def embed_texts(texts: list[str]) -> list[list[float]]:
    kind, model = get_embedder()
    if kind == "bge-m3":
        result = model.encode(texts, batch_size=12, max_length=8192)
        return [_to_list(vector) for vector in result["dense_vecs"]]

    vectors = model.encode(texts, normalize_embeddings=True)
    return [_to_list(vector) for vector in vectors]
