"""
vector_retriever.py — Semantic retrieval via embeddings.

BM25 matches WORDS. This matches MEANING. "how does Gyro die" should find the
passage about senescence and Ball Breaker even though it never says "die" — because
their embeddings (dense numeric vectors capturing meaning) sit close together.

It implements the SAME `.retrieve(query, k)` interface as BM25Retriever, so it
drops into the pipeline with zero downstream changes.

The `embedder` is injectable — a callable list[str] -> ndarray(N, D):
  - default: sentence-transformers 'all-MiniLM-L6-v2' (small, runs locally/offline
    AFTER a one-time model download — that's why you run this on your machine).
  - tests: a tiny fake embedder, so the retrieval MECHANICS are provable without
    any download (see test_vector_retriever below).
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .chunker import Chunk
from .retriever import RetrievedChunk

Embedder = Callable[[list[str]], np.ndarray]


def sentence_transformer_embedder(model_name: str = "all-MiniLM-L6-v2") -> Embedder:
    """Default embedder. Downloads a small model once, then runs offline."""
    from sentence_transformers import SentenceTransformer  # lazy: only if used
    model = SentenceTransformer(model_name)

    def embed(texts: list[str]) -> np.ndarray:
        return np.asarray(model.encode(list(texts)), dtype="float32")

    return embed


def _l2_normalize(m: np.ndarray) -> np.ndarray:
    """Normalize rows to unit length so a dot product == cosine similarity."""
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class VectorRetriever:
    """Dense semantic retrieval over a list of chunks."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        if not chunks:
            raise ValueError("VectorRetriever needs a non-empty list of chunks")
        self.chunks = chunks
        self._embed = embedder or sentence_transformer_embedder()
        self._matrix = _l2_normalize(self._embed([c.text for c in chunks]))

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        q = _l2_normalize(self._embed([query]))[0]
        sims = self._matrix @ q                    # cosine similarity to every chunk
        order = np.argsort(sims)[::-1][:k]         # top-k, highest first
        return [RetrievedChunk(chunk=self.chunks[i], score=float(sims[i])) for i in order]
