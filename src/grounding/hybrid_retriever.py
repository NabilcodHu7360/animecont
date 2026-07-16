"""
hybrid_retriever.py — Fuse lexical (BM25) + semantic (vector) retrieval.

Neither alone is enough: BM25 nails exact names ("Firenda", "Ende") but misses
paraphrases; vectors catch meaning but can drift on rare proper nouns. Production
RAG runs BOTH and fuses them.

We fuse with RECIPROCAL RANK FUSION (RRF): each retriever contributes
1/(k + rank) for every chunk it ranks. It uses RANK, not raw score, so we don't
have to reconcile BM25's unbounded scores with cosine's 0..1 range — a clean,
robust default. Same `.retrieve()` interface as the others.
"""
from __future__ import annotations

from .retriever import Retriever, RetrievedChunk


class HybridRetriever:
    def __init__(self, bm25: Retriever, vector: Retriever,
                 pool: int = 20, k_rrf: int = 60):
        self.bm25 = bm25
        self.vector = vector
        self.pool = pool        # how deep to pull from each before fusing
        self.k_rrf = k_rrf      # RRF damping constant (60 is the standard default)

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        fused: dict[tuple, float] = {}
        lookup: dict[tuple, object] = {}

        for retriever in (self.bm25, self.vector):
            for rank, rc in enumerate(retriever.retrieve(query, k=self.pool)):
                key = (rc.chunk.source_id, rc.chunk.chunk_index)
                fused[key] = fused.get(key, 0.0) + 1.0 / (self.k_rrf + rank)
                lookup[key] = rc.chunk

        top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [RetrievedChunk(chunk=lookup[key], score=score) for key, score in top]
