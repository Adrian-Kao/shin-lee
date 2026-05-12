from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    file_name: str
    page: int
    text: str
    source_path: str


@dataclass(frozen=True)
class Chunk:
    id: str
    file_name: str
    page: int
    text: str
    source_path: str
