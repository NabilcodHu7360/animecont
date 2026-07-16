"""
run_script_eval.py — Batch-evaluate the authored video-essay scripts.

WHY A SEPARATE RUNNER
grounding_eval.py was written for the generator's [S#] citation contract, where
a script cites [S1], [S2], ... and you pass a parallel sources.txt. The authored
scripts in data/scripts/ use a *human-readable* citation style instead:
    [ch.81]        single chapter
    [ch.30-53]     chapter range
    [Doll Festival Arc]   arc/section name
so the raw [S#] evaluator would see zero tags and wrongly report 0% coverage.

This runner adapts the SAME underlying checks (coverage, structure, faithfulness)
to that citation style, loads each script's matching corpus as the source text,
and prints one row per script plus a summary table. grounding_eval.py is left
untouched so the [S#] path still works for generator output.

Usage:
    python -m src.eval.run_script_eval                  # all scripts in data/scripts/
    python -m src.eval.run_script_eval data/scripts/frieren_script.md   # one script
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .grounding_eval import (
    _split_sentences, _content_words, _WORD_RE, MARKER_RE, heuristic_judge,
)

SCRIPTS_DIR = Path("data/scripts")
CORPUS_DIR = Path("data/corpus")

# Our citation styles: [ch.81], [ch.30-53], or [Some Arc Name].
# We deliberately exclude the production markers so they aren't counted as cites.
_MARKER_WORDS = ("MUSIC CUE", "BEAT", "HOST", "VISUAL", "INTENSITY")
CITE_ANY_RE = re.compile(r"\[([^\]]+)\]")


def is_citation(tag: str) -> bool:
    """True if a [...] tag is a citation, not a production marker or filler."""
    t = tag.strip()
    if any(t.upper().startswith(m) for m in _MARKER_WORDS):
        return False
    if t.lower() in ("brackets", "beat"):  # stray literal words in headers
        return False
    return True


def script_to_corpus_path(script_path: Path) -> Path:
    """frieren_script.md -> data/corpus/frieren.md"""
    stem = script_path.name.replace("_script.md", "")
    return CORPUS_DIR / f"{stem}.md"


def strip_header(script: str) -> str:
    """Drop the italic provenance header block so it isn't scored as prose."""
    # Everything after the first '---' divider is the actual script body.
    parts = script.split("\n---\n", 1)
    return parts[1] if len(parts) == 2 else script


def evaluate_authored(script: str, corpus: str,
                      target_words=(400, 6000),
                      judge=heuristic_judge) -> dict:
    """Coverage + structure + faithfulness for an arc/chapter-cited script."""
    body = strip_header(script)
    sentences = _split_sentences(body)

    n_narrative = n_cited = 0
    checked = supported = 0
    unsupported_examples: list[str] = []
    all_tags: set[str] = set()

    for sent in sentences:
        raw_tags = CITE_ANY_RE.findall(sent)
        cite_tags = [t for t in raw_tags if is_citation(t)]
        all_tags.update(cite_tags)

        # narrative sentence = real prose once markers+cites are stripped
        prose = CITE_ANY_RE.sub("", sent)
        prose = MARKER_RE.sub("", prose).strip()
        if len(_WORD_RE.findall(prose)) < 4:
            continue
        n_narrative += 1
        if cite_tags:
            n_cited += 1

        # faithfulness: does the corpus support this claim's content words?
        # (corpus-level heuristic: the cited chapter/arc text lives in `corpus`.)
        if cite_tags:
            checked += 1
            if judge(prose, corpus):
                supported += 1
            else:
                unsupported_examples.append(prose)

    coverage = n_cited / n_narrative if n_narrative else 0.0
    faithfulness = supported / checked if checked else None
    words = len(_WORD_RE.findall(body))

    return {
        "coverage": coverage,
        "n_narrative": n_narrative,
        "n_cited": n_cited,
        "n_unique_tags": len(all_tags),
        "faithfulness": faithfulness,
        "unsupported": unsupported_examples,
        "words": words,
        "has_music_cue": bool(re.search(r"\[MUSIC CUE", script, re.IGNORECASE)),
        "has_visual": bool(re.search(r"\[VISUAL", script, re.IGNORECASE)),
        "length_ok": target_words[0] <= words <= target_words[1],
    }


def passed(r: dict, min_cov=0.60, min_faith=0.80) -> bool:
    """Thresholds are gentler than the [S#] path: arc-level citations cover
    multiple sentences, and heuristic faithfulness is a coarse word-overlap
    proxy against the *whole* corpus, so we don't demand 0.85/0.9 here."""
    if r["coverage"] < min_cov:
        return False
    if not (r["has_music_cue"] and r["has_visual"] and r["length_ok"]):
        return False
    if r["faithfulness"] is not None and r["faithfulness"] < min_faith:
        return False
    return True


def run_one(script_path: Path) -> dict | None:
    corpus_path = script_to_corpus_path(script_path)
    if not corpus_path.exists():
        print(f"  ! {script_path.name}: corpus {corpus_path} not found — skipped")
        return None
    script = script_path.read_text(encoding="utf-8")
    corpus = corpus_path.read_text(encoding="utf-8")
    return evaluate_authored(script, corpus)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        targets = [Path(argv[1])]
    else:
        targets = sorted(SCRIPTS_DIR.glob("*_script.md"))

    print(f"{'series':<22} {'cov':>5} {'faith':>6} {'cites':>6} {'words':>6}  pass")
    print("-" * 60)
    any_fail = False
    for sp in targets:
        r = run_one(sp)
        if r is None:
            continue
        name = sp.name.replace("_script.md", "")
        ok = passed(r)
        any_fail = any_fail or not ok
        faith = f"{r['faithfulness']:.0%}" if r["faithfulness"] is not None else "  -"
        print(f"{name:<22} {r['coverage']:>4.0%} {faith:>6} "
              f"{r['n_unique_tags']:>6} {r['words']:>6}  {'OK' if ok else 'FAIL'}")
        if not ok and r["unsupported"]:
            for ex in r["unsupported"][:2]:
                print(f"    ✗ low-overlap: {ex[:70]}")
    print("-" * 60)
    print("all passed" if not any_fail else "some scripts need attention")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
