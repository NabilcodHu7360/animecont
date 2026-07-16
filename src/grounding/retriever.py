"""
retriever.py — Retrieval interface + a BM25 (lexical) implementation.

THE PLAN (why the interface matters)
Retrieval has three common flavours:
  1. Lexical (BM25)     — matches exact words. Great for names: "Firenda", "Ende".
  2. Semantic (vectors) — matches meaning. Great for paraphrases: "who dies?".
  3. Hybrid (1 + 2)     — fuse both, then rerank. What production RAG actually uses.

We implement BM25 now (pure-python, zero downloads, runs in CI). By coding to the
`Retriever` protocol below, we can drop in a `VectorRetriever` and a
`HybridRetriever` later WITHOUT touching the script generator — it only ever sees
`.retrieve(query, k) -> list[RetrievedChunk]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rank_bm25 import BM25Okapi

from .chunker import Chunk


@dataclass
class RetrievedChunk:
    """A chunk plus the score that got it retrieved."""
    chunk: Chunk
    score: float


class Retriever(Protocol):
    """Every retriever (BM25, vector, hybrid) implements this one method."""
    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]: ...


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens. BM25 works on token lists, not raw strings."""
    return re.findall(r"[a-z0-9']+", text.lower())


class BM25Retriever:
    """Lexical retrieval over a list of chunks using Okapi BM25."""

    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("BM25Retriever needs a non-empty list of chunks")
        self.chunks = chunks
        self._tokenized = [_tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._tokenized)

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        scores = self._bm25.get_scores(_tokenize(query))
        # Rank all chunks by score, keep the top k with score > 0.
        ranked = sorted(
            zip(self.chunks, scores), key=lambda cs: cs[1], reverse=True
        )
        return [
            RetrievedChunk(chunk=c, score=float(s))
            for c, s in ranked[:k]
            if s > 0
        ]


def format_context(results: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a citation-tagged context block for the LLM.

    This is what we paste into the script-generation prompt. Because each line is
    prefixed with its citation, we can later instruct Claude: "only state facts
    present below, and cite the source in [brackets]."
    """
    lines = []
    for r in results:
        lines.append(f"[{r.chunk.citation}] ({r.chunk.title}) {r.chunk.text}")
    return "\n\n".join(lines)
