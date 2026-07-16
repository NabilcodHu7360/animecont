"""
corpus_quality.py — Verify corpus quality BEFORE generating anything.

A bad corpus silently poisons everything downstream: the script, voice, and video
all faithfully repeat a corpus error. So we gate on quality. Run this right after
build_corpus:

    python -m src.ingest.corpus_quality

It scans every data/corpus/*.md and checks the four things that actually threaten
grounding, printing a per-series report and exiting non-zero if anything FAILs.

  1. VOLUME        — did the ingest actually get content? (catches 404s / cruft)
  2. CITATIONS     — can every passage be traced to a locator, not just a series?
  3. JUNK          — leftover wiki chrome (nav, "Community content is…", galleries)
  4. PRE-ANIME BLEED — for continuous series, content from before the cutoff
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from ..grounding.corpus import load_corpus, Passage

# Thresholds (tune to taste — these are deliberately lenient first-pass gates).
MIN_PASSAGES = 3
MIN_WORDS = 200
MIN_CITATION_RATE = 0.5   # fraction of passages with a specific locator

# Wiki chrome that sometimes survives ingestion.
_JUNK = re.compile(
    r"community content is available|all items \(\d+\)|sign in to|"
    r"fandom apps|categories:|view source|explore properties|"
    r"terms of use|privacy policy",
    re.IGNORECASE,
)


def _words(passages: list[Passage]) -> int:
    return sum(len(p.text.split()) for p in passages)


def _ch_range(p: Passage) -> tuple[int, int] | None:
    ch = p.meta.get("ch", "")
    m = re.match(r"(\d+)\s*-\s*(\d+)", ch) or re.match(r"(\d+)", ch)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else a
    return (a, b)


def check_corpus(path: Path, cutoff: int | None, continuous: bool) -> tuple[str, list[str]]:
    """Return (status, issues) for one corpus file. status in PASS/WARN/FAIL."""
    passages = load_corpus(path)
    issues: list[str] = []
    status = "PASS"

    # 1. Volume
    nwords = _words(passages)
    if len(passages) < MIN_PASSAGES or nwords < MIN_WORDS:
        issues.append(f"THIN: {len(passages)} passages / {nwords} words "
                      f"(min {MIN_PASSAGES}/{MIN_WORDS}) — likely a 404 or bad parse")
        status = "FAIL"

    # 2. Citation specificity (has ch OR section OR page, not just series)
    specific = sum(bool(p.meta.get("ch") or p.meta.get("section") or p.meta.get("page"))
                   for p in passages)
    rate = specific / len(passages) if passages else 0
    if rate < MIN_CITATION_RATE:
        issues.append(f"WEAK CITATIONS: only {rate:.0%} of passages have a locator")
        status = "FAIL" if status != "FAIL" else status

    # 3. Junk
    junk = [p.title for p in passages if _JUNK.search(p.text)]
    if junk:
        issues.append(f"JUNK: {len(junk)} passage(s) look like wiki chrome: {junk[:3]}")
        status = "WARN" if status == "PASS" else status

    # 4. Pre-anime bleed (continuous series only)
    if continuous and cutoff:
        full, partial = 0, 0
        for p in passages:
            rng = _ch_range(p)
            if not rng:
                continue
            a, b = rng
            if b < cutoff:
                full += 1
            elif a < cutoff <= b:
                partial += 1
        if full:
            issues.append(f"PRE-ANIME BLEED: {full} passage(s) fully before ch.{cutoff}")
            status = "FAIL" if status != "FAIL" else status
        if partial:
            issues.append(f"straddle: {partial} passage(s) span ch.{cutoff} "
                          f"(partly pre-anime — usually fine)")
            status = "WARN" if status == "PASS" else status

    return status, issues


def main(registry_path="data/series_registry.yaml", corpus_dir="data/corpus") -> int:
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))    # map series-slug -> (cutoff, continuous)
    meta = {e["subdomain"]: (e.get("cutoff_chapter"),
                             e.get("continuation_type") == "continuous")
            for e in registry.get("series", [])}

    files = sorted(Path(corpus_dir).glob("*.md"))
    if not files:
        print("No corpus files found — run `python -m src.ingest.build_corpus` first.")
        return 1

    print(f"Corpus quality report — {len(files)} file(s)\n" + "=" * 52)
    worst_ok = True
    for f in files:
        passages = load_corpus(f)
        series = passages[0].meta.get("series", f.stem) if passages else f.stem
        cutoff, continuous = meta.get(series, meta.get(f.stem, (None, False)))
        status, issues = check_corpus(f, cutoff, continuous)
        mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[status]
        print(f"\n{mark} [{status}] {f.name}  ({len(passages)} passages)")
        for i in issues:
            print(f"      - {i}")
        if status == "FAIL":
            worst_ok = False

    print("\n" + "=" * 52)
    print("All corpora passed." if worst_ok else "Some corpora FAILED — fix before generating.")
    return 0 if worst_ok else 1


if __name__ == "__main__":
    sys.exit(main())
