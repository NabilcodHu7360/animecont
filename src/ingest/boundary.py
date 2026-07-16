"""
boundary.py — Keep only post-anime content for CONTINUOUS series.

Two kinds of continuation:
  - "parts"      (e.g. JoJo): the manga continues as whole new parts. Every part
                 page is 100% post-anime, so NO trimming is needed — you just list
                 the post-anime part pages in the registry.
  - "continuous" (e.g. Jujutsu Kaisen): one ongoing story. The anime stopped at a
                 chapter mid-story, so a page can mix pre- and post-anime events.

The PRIMARY boundary control is still page selection — you list the arc pages that
begin AFTER the cutoff. This function is a coarse SAFETY NET on top of that: if a
passage explicitly references only chapters below the cutoff, drop it. Anything
ambiguous (no chapter mentioned) is KEPT, because wrongly cutting real content is
worse than keeping a little extra.
"""
from __future__ import annotations

import re

from ..grounding.corpus import Passage

_CH_RE = re.compile(r"(?:chapter|ch\.?)\s*(\d+)", re.IGNORECASE)


def referenced_chapters(text: str) -> list[int]:
    return [int(n) for n in _CH_RE.findall(text)]


def filter_after_chapter(passages: list[Passage], cutoff: int | None) -> list[Passage]:
    """Drop passages whose only chapter references are below `cutoff`."""
    if not cutoff:
        return passages
    kept: list[Passage] = []
    for p in passages:
        chs = referenced_chapters(f"{p.title} {p.text}")
        if not chs or max(chs) >= cutoff:  # ambiguous or reaches past cutoff -> keep
            kept.append(p)
    return kept
