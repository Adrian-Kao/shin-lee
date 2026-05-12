from __future__ import annotations

import re
import uuid

from .models import Chunk, PageText


def _normalize(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_id(page: PageText, chunk_no: int, text: str) -> str:
    key = f"{page.source_path}:{page.page}:{chunk_no}:{text[:120]}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def chunk_pages(pages: list[PageText], chunk_size: int = 900, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        text = _normalize(page.text)
        if not text:
            continue
        start = 0
        chunk_no = 1
        while start < len(text):
            end = min(start + chunk_size, len(text))
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    Chunk(
                        id=_chunk_id(page, chunk_no, piece),
                        file_name=page.file_name,
                        page=page.page,
                        text=piece,
                        source_path=page.source_path,
                    )
                )
            if end == len(text):
                break
            start = max(end - overlap, start + 1)
            chunk_no += 1
    return chunks
