from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    page_start: int
    page_end: int
    text: str


def chunk_pages(pages: list[str], size: int = 400, overlap: int = 80) -> list[TextChunk]:
    if size <= overlap or overlap < 0:
        raise ValueError("chunk size must exceed non-negative overlap")
    words: list[tuple[str, int]] = []
    for page_number, raw in enumerate(pages, start=1):
        cleaned = re.sub(r"\s+", " ", raw or "").strip()
        words.extend((word, page_number) for word in cleaned.split(" ") if word)
    if not words:
        return []
    chunks: list[TextChunk] = []
    step = size - overlap
    for start in range(0, len(words), step):
        window = words[start:start + size]
        if not window:
            break
        chunks.append(TextChunk(
            ordinal=len(chunks),
            page_start=window[0][1],
            page_end=window[-1][1],
            text=" ".join(word for word, _ in window),
        ))
        if start + size >= len(words):
            break
    return chunks
