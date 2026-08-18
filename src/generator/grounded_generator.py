"""
grounded_generator.py — grounded, cited script generation.

This supersedes the plot-generation half of the old script_generator.py. Instead
of asking Claude to recall a manga from memory (hallucination city), we:

  1. Assemble a citation-tagged SOURCES block from the corpus (budget-aware:
     use it all when it fits, retrieve to fit when it doesn't).
  2. Prompt Claude to narrate ONLY facts present in SOURCES and cite each one.
  3. Let Claude invent freely on *style* (drama, pacing, production markers).

`build_prompt()` is pure and API-free so you can unit-test the grounding logic and
inspect exactly what gets sent — without spending a single API credit.
`generate_script()` is the thin wrapper that actually calls the model.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ..grounding.chunker import Chunk
from ..grounding.retriever import Retriever


# ── Source assembly ──────────────────────────────────────────────────────────

def _chapter_start(chunk: Chunk) -> int:
    """Pull the starting chapter number out of a source_id for ordering.

    source_id looks like 'jojo|Steel_Ball_Run|54-70' -> 54.
    """
    parts = chunk.source_id.split("|")
    ch = parts[2] if len(parts) > 2 else ""
    m = re.match(r"(\d+)", ch)
    return int(m.group(1)) if m else 0


def _word_count(chunks: list[Chunk]) -> int:
    return sum(len(c.text.split()) for c in chunks)


def assemble_grounding(
    chunks: list[Chunk],
    retriever: Retriever | None = None,
    budget_words: int = 1500,
    focus_query: str | None = None,
) -> list[Chunk]:
    """Choose which chunks become the grounded SOURCES, then order by chapter.

    - If the whole corpus fits in `budget_words`: use all of it (coverage wins).
    - Otherwise: use the retriever to pick the most relevant chunks under budget.
      `focus_query` lets you bias what "relevant" means (e.g. "the ending");
      with no query we retrieve against a broad prompt so we still get spread.
    """
    if _word_count(chunks) <= budget_words or retriever is None:
        selected = list(chunks)
    else:
        query = focus_query or "major plot reveals, character arcs, and the ending"
        # Pull generously, then greedily keep top chunks until we hit budget.
        hits = retriever.retrieve(query, k=len(chunks))
        selected, running = [], 0
        for h in hits:
            w = len(h.chunk.text.split())
            if running + w > budget_words:
                continue
            selected.append(h.chunk)
            running += w

    # Chapter order so the narrative reads front-to-back, not by relevance score.
    selected.sort(key=lambda c: (_chapter_start(c), c.chunk_index))
    return selected


def build_context_block(chunks: list[Chunk]) -> str:
    """Render selected chunks as a numbered, citation-tagged SOURCES block."""
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[S{i}] ({c.citation} — {c.title})\n{c.text}")
    return "\n\n".join(lines)


# ── Prompt construction ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional anime video essayist and podcast host. \
Your style is cinematic, present-tense, emotionally invested — the kind of essay \
that gets millions of views because it makes people FEEL something.

You work under a strict grounding contract:
- FACTS (plot events, names, reveals, outcomes) may come ONLY from the numbered \
SOURCES you are given. Every plot statement MUST end with its source tag, e.g. \
"Tokikaze delivers the killing blow [S9]." Combine tags when a sentence draws on \
several sources, e.g. [S8][S9].
- If a detail is not in the SOURCES, you do NOT state it. Do not invent names, \
deaths, motivations, or outcomes. When unsure, stay silent rather than guess.
- STYLE is yours to invent: narration, transitions, tension, tone, and the \
production markers [MUSIC CUE: ...], [BEAT], [HOST], [VISUAL: ...]. These are not \
factual claims and do NOT need citations.

Structure: a gripping 30-second cold open, acts with rising emotion, [MUSIC CUE] \
and [BEAT] markers, [VISUAL: ...] markers describing shots for image generation, \
and a closing monologue that lands the theme."""


def build_prompt(
    anime: str,
    grounded_chunks: list[Chunk],
    target_length: str = "full",
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt). Pure — no API call, fully testable."""
    length_guide = {
        "short": "~1500 words, ~10 minutes of audio",
        "medium": "~3000 words, ~20 minutes of audio",
        "full": "~5000 words, ~30 minutes of audio",
    }.get(target_length, "~5000 words")

    sources = build_context_block(grounded_chunks)

    user_prompt = f"""Write a cinematic video-essay script covering what happens in \
the {anime} manga AFTER the anime ended.

TARGET LENGTH: {length_guide}

Narrate the story below in order, dramatically, following the grounding contract.
Cite every plot statement with its [S#] tag. Do not add plot facts beyond these.

SOURCES:
{sources}
"""
    return SYSTEM_PROMPT, user_prompt


# ── Generation ───────────────────────────────────────────────────────────────

def generate_script(
    anime: str,
    grounded_chunks: list[Chunk],
    target_length: str = "full",
    provider: str = "gemini",
    model: str | None = None,
    max_tokens: int = 8000,
) -> str:
    from .llm import complete
    system, user = build_prompt(anime, grounded_chunks, target_length)
    return complete(system, user, provider=provider, model=model, max_tokens=max_tokens)
    
    # Robust: concatenate all text blocks instead of assuming content[0].
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
