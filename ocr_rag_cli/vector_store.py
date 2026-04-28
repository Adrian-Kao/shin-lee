from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import QDRANT_COLLECTION, QDRANT_URL
from .embedder import embed_texts
from .models import Chunk


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    collections = client.get_collections().collections
    if any(item.name == QDRANT_COLLECTION for item in collections):
        return
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
    )


def upsert_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    vectors = embed_texts([chunk.text for chunk in chunks])
    client = get_client()
    ensure_collection(client, len(vectors[0]))
    points = [
        qm.PointStruct(
            id=chunk.id,
            vector=vector,
            payload={
                "file_name": chunk.file_name,
                "page": chunk.page,
                "text": chunk.text,
                "source_path": chunk.source_path,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    return len(points)


def search(question: str, top_k: int) -> list[dict]:
    vector = embed_texts([question])[0]
    client = get_client()
    hits = client.search(collection_name=QDRANT_COLLECTION, query_vector=vector, limit=top_k)
    return [
        {
            "score": hit.score,
            "file_name": hit.payload.get("file_name"),
            "page": hit.payload.get("page"),
            "text": hit.payload.get("text"),
            "source_path": hit.payload.get("source_path"),
        }
        for hit in hits
    ]
