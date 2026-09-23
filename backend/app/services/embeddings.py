from __future__ import annotations

import asyncio
import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


class FakeEmbedder:
    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            values = [0.0] * self.dimensions
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                values[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            results.append([value / norm for value in values])
        return results


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        prepared = texts
        if query:
            prepared = [f"Represent this sentence for searching relevant passages: {text}" for text in texts]
        model = await asyncio.to_thread(self._load)
        results: list[list[float]] = []
        for start in range(0, len(prepared), 32):
            vectors = await asyncio.to_thread(
                model.encode, prepared[start:start + 32],
                normalize_embeddings=True, show_progress_bar=False,
            )
            results.extend(vector.tolist() for vector in vectors)
        return results
