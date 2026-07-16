"""
build_corpus.py — Generate corpus files for every series in the registry.

Run on your machine (needs internet for the Fandom API):
    python -m src.ingest.build_corpus

For each registry entry it: fetches each listed page, parses it into Passages,
trims pre-anime content for "continuous" series, and writes one corpus markdown
file per series in the same citation-tagged format load_corpus() expects.

`fetch` is injectable so the whole pipeline can be tested offline (see the
__main__ demo, which runs with a fake fetch and no network).
"""
from __future__ import annotations

import time
from pathlib import Path

import yaml

from ..grounding.corpus import Passage
from .fandom import fetch_page_html, html_to_passages, ingest_chapter_range
from .boundary import filter_after_chapter


def serialize_corpus(subdomain: str, passages: list[Passage]) -> str:
    """Passages -> citation-tagged markdown that load_corpus() can read back."""
    out = [f"# {subdomain} — Post-Anime Corpus\n"]
    for p in passages:
        page = p.meta.get("page", "")
        section = p.meta.get("section", p.title)
        out.append(
            f"## [series={subdomain} | page={page} | section={section}] {p.title}\n\n"
            f"{p.text}\n"
        )
    return "\n".join(out)


def build_one(entry: dict, fetch=fetch_page_html) -> list[Passage]:
    """Ingest + trim one registry entry into a list of Passages."""
    subdomain = entry["subdomain"]
    passages: list[Passage] = []
    rng = entry.get("chapter_range")
    if rng:
        passages.extend(
            ingest_chapter_range(subdomain, subdomain, rng[0], rng[1], fetch=fetch)
        )
        # chapter passages are already post-anime scoped; no trimming needed

    page_passages: list[Passage] = []
    for page in entry.get("pages", []):
            try:
                html = fetch(subdomain, page)
            except Exception as e:
                print(f"    skip page {page!r}: {e}")
                continue
            page_passages.extend(html_to_passages(html, series=subdomain, page=page))
    # Only page passages need boundary trimming (chapters are already scoped)
    if entry.get("continuation_type") == "continuous":
        page_passages = filter_after_chapter(page_passages, entry.get("cutoff_chapter"))

    passages.extend(page_passages)
    return passages

def build_all(
    registry_path: str | Path = "data/series_registry.yaml",
    out_dir: str | Path = "data/corpus",
    fetch=fetch_page_html,
    polite_delay: float = 1.0,
) -> dict[str, int]:
    """Build every series. Returns {subdomain: n_passages}. Skips empty entries."""
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))    
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int] = {}
    for entry in registry.get("series", []):
        if not entry.get("pages") and not entry.get("chapter_range"):
            print(f"skip {entry['subdomain']}: no pages listed yet")
            continue
        passages = build_one(entry, fetch=fetch)
        (out_dir / f"{entry['subdomain']}.md").write_text(
            serialize_corpus(entry["subdomain"], passages), encoding="utf-8"
        )
        summary[entry["subdomain"]] = len(passages)
        print(f"built {entry['subdomain']}: {len(passages)} passages")
        if fetch is fetch_page_html:
            time.sleep(polite_delay)  # be kind to Fandom between series
    return summary


if __name__ == "__main__":
    build_all()
