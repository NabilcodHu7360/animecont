"""
corpus.py — Loads a citation-tagged markdown corpus into Passage objects.

WHY THIS EXISTS
The whole product risk is that Claude invents plot points. The fix is to feed it
*retrieved, real* passages and force it to cite them. For that to work, every
passage has to carry a source we can point back to. We encode the source in the
markdown heading itself, e.g.:

    ## [series=jojo | page=Steel_Ball_Run | section=Conclusion] Johnny sails home

so the citation ("jojo Steel_Ball_Run") travels with the text through the whole
pipeline and ends up in the script.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# Matches:  ## [key=value | key=value | ...] Optional Title
_HEADING_RE = re.compile(r"^##\s*\[(?P<meta>[^\]]+)\]\s*(?P<title>.*)$")


@dataclass
class Passage:
    """One source unit from the corpus."""
    text: str
    title: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Human-readable citation string, e.g. 'jojo Steel_Ball_Run'."""
        series = self.meta.get("series", "?")
        ch = self.meta.get("ch")
        return f"{series} ch.{ch}" if ch else series

    @property
    def source_id(self) -> str:
        """Stable, UNIQUE id per passage for dedup / tracing / fusion keys.

        Includes page+section (not just series/arc/ch) so section-based corpora —
        which share one arc and carry no chapter tag — still get distinct ids.
        """
        parts = [self.meta.get(k, "") for k in ("series", "arc", "page", "ch", "section")]
        return "|".join(p for p in parts if p)


def _parse_meta(meta_str: str) -> dict[str, str]:
    """'series=jojo | page=Steel_Ball_Run'  ->  {'series': 'jojo', 'page': 'Steel_Ball_Run'}"""
    out: dict[str, str] = {}
    for part in meta_str.split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_corpus(path: str | Path) -> list[Passage]:
    """Parse a citation-tagged markdown file into a list of Passages.

    Lines starting with '<!--' comment blocks and blank lines are ignored.
    A new passage starts at each '## [...]' heading and runs until the next one.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()

    passages: list[Passage] = []
    cur_meta: dict[str, str] | None = None
    cur_title = ""
    cur_body: list[str] = []
    in_comment = False

    def flush():
        if cur_meta is not None:
            body = " ".join(l.strip() for l in cur_body if l.strip())
            if body:
                passages.append(Passage(text=body, title=cur_title, meta=cur_meta))

    for line in lines:
        stripped = line.strip()
        # Skip HTML comment blocks (used for corpus notes)
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        if in_comment:
            in_comment = "-->" not in stripped
            continue

        m = _HEADING_RE.match(line)
        if m:
            flush()  # close the previous passage
            cur_meta = _parse_meta(m.group("meta"))
            cur_title = m.group("title").strip()
            cur_body = []
        elif cur_meta is not None:
            cur_body.append(line)

    flush()  # close the last passage
    return passages


if __name__ == "__main__":
    # Quick manual check
    here = Path(__file__).resolve().parents[2]
    passages = load_corpus(here / "data" / "corpus" / "jojo.md")
    print(f"Loaded {len(passages)} passages")
    for p in passages[:3]:
        print(f"  [{p.citation}] {p.title}: {p.text[:70]}...")
