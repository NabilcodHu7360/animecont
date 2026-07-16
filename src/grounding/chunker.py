"""
chunker.py — Splits passages into overlapping chunks for retrieval.

WHY OVERLAP
If you cut a passage into hard, non-overlapping windows, a fact that straddles a
boundary gets split across two chunks and neither chunk retrieves well. A small
overlap (a few sentences / tokens repeated at the seam) keeps boundary-straddling
facts intact in at least one chunk. Classic default: ~500-800 token chunks with
~100 token overlap.

NOTE ON "TOKENS"
We approximate tokens by whitespace words here so this runs with zero downloads.
For production, swap `count_len` for tiktoken to count real model tokens:

    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    count_len = lambda s: len(enc.encode(s))

The interface below doesn't change — only the length function does.
"""
from __future__ import annotations

from dataclasses import dataclass

from .corpus import Passage


@dataclass
class Chunk:
    """A retrievable unit: a slice of a passage that still knows its source."""
    text: str
    title: str
    citation: str
    source_id: str
    chunk_index: int  # position of this chunk within its source passage


def _words(text: str) -> list[str]:
    return text.split()


def chunk_passage(
    passage: Passage,
    max_words: int = 120,
    overlap_words: int = 30,
) -> list[Chunk]:
    """Split one passage into overlapping word-windows.

    Defaults are small (120/30) because our corpus passages are short and
    self-contained. Scale up to ~600/100 for long scraped articles.
    """
    words = _words(passage.text)
    if not words:
        return []

    # Passage already fits in one chunk -> return it whole.
    if len(words) <= max_words:
        return [Chunk(passage.text, passage.title, passage.citation,
                      passage.source_id, 0)]

    step = max(1, max_words - overlap_words)
    chunks: list[Chunk] = []
    for i, start in enumerate(range(0, len(words), step)):
        window = words[start:start + max_words]
        if not window:
            break
        chunks.append(Chunk(
            text=" ".join(window),
            title=passage.title,
            citation=passage.citation,
            source_id=passage.source_id,
            chunk_index=i,
        ))
        if start + max_words >= len(words):
            break  # last window reached the end
    return chunks


def chunk_corpus(
    passages: list[Passage],
    max_words: int = 120,
    overlap_words: int = 30,
) -> list[Chunk]:
    """Chunk an entire corpus, preserving order."""
    out: list[Chunk] = []
    for p in passages:
        out.extend(chunk_passage(p, max_words, overlap_words))
    return out
