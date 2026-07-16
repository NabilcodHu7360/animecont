"""
grounding_eval.py — Does the generated script keep its grounding promise?

The generator PROMISES to cite only real sources and invent no plot facts. This
module VERIFIES that promise mechanically, so "trust me, it's accurate" becomes
"here is the automated proof." Four checks, cheap ones first:

  1. DANGLING TAGS   — every [S#] in the script points to a source that exists.
  2. COVERAGE        — what fraction of narrative sentences actually carry a cite.
  3. STRUCTURE       — cold open, [MUSIC CUE]/[VISUAL] markers, length in range.
  4. FAITHFULNESS    — does each cited source actually support its claim?
                       (pluggable judge: cheap offline heuristic, or real LLM.)

Checks 1-3 are deterministic and free — perfect for a CI gate. Check 4 is the
expensive, truthful one; you run it on a sample, not every sentence, in CI.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

CITE_RE = re.compile(r"\[S(\d+)\]")
MARKER_RE = re.compile(r"\[(?:MUSIC CUE|BEAT|HOST|VISUAL)[^\]]*\]", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9']+")

# Very common English words we ignore when checking claim/source overlap.
_STOP = set("the a an and or but of to in on at is are was were be been being it "
            "he she they them his her their this that these those with as for from "
            "by into out up down over then than so who what when where why how not "
            "his her its our your my we you i".split())


# ── helpers ──────────────────────────────────────────────────────────────────

def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def _split_sentences(text: str) -> list[str]:
    # Naive but fine for scripts: split on sentence enders, keep non-empty.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── result container ─────────────────────────────────────────────────────────

@dataclass
class EvalReport:
    n_sources: int = 0
    n_narrative_sentences: int = 0
    n_cited_sentences: int = 0
    coverage: float = 0.0
    dangling_tags: list[int] = field(default_factory=list)
    unused_sources: list[int] = field(default_factory=list)
    structure: dict[str, bool] = field(default_factory=dict)
    faithfulness: float | None = None
    unfaithful_examples: list[str] = field(default_factory=list)

    def passed(self, min_coverage=0.85, min_faithfulness=0.9) -> bool:
        if self.dangling_tags:
            return False
        if self.coverage < min_coverage:
            return False
        if not all(self.structure.values()):
            return False
        if self.faithfulness is not None and self.faithfulness < min_faithfulness:
            return False
        return True

    def summary(self) -> str:
        lines = [
            f"sources: {self.n_sources}",
            f"coverage: {self.coverage:.0%} "
            f"({self.n_cited_sentences}/{self.n_narrative_sentences} narrative sentences cited)",
            f"dangling tags: {self.dangling_tags or 'none'}",
            f"unused sources: {self.unused_sources or 'none'}",
            f"structure: {self.structure}",
        ]
        if self.faithfulness is not None:
            lines.append(f"faithfulness: {self.faithfulness:.0%}")
            for ex in self.unfaithful_examples:
                lines.append(f"   ✗ unsupported: {ex[:80]}")
        return "\n".join(lines)


# ── the judges for check #4 ──────────────────────────────────────────────────

def heuristic_judge(claim: str, source: str, threshold: float = 0.5) -> bool:
    """CHEAP proxy: is enough of the claim's content present in the source?

    This is NOT real understanding — it's word overlap. It catches blatant
    fabrication (claim shares almost nothing with its cited source) but will be
    fooled by paraphrase. Use it as a fast pre-filter; use llm_judge for truth.
    """
    claim_words = _content_words(claim)
    if not claim_words:
        return True
    src_words = _content_words(source)
    overlap = len(claim_words & src_words) / len(claim_words)
    return overlap >= threshold


def llm_judge(claim: str, source: str, model: str = "claude-opus-4-8") -> bool:
    """REAL check: ask a model whether the source supports the claim."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    prompt = (
        f"SOURCE:\n{source}\n\nCLAIM:\n{claim}\n\n"
        "Does the SOURCE support the CLAIM? A claim is supported only if the "
        "source states or directly implies it. Answer with exactly one word: "
        "SUPPORTED or UNSUPPORTED."
    )
    msg = client.messages.create(
        model=model, max_tokens=5,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return "SUPPORTED" in text.upper() and "UNSUPPORTED" not in text.upper()


# ── the evaluator ────────────────────────────────────────────────────────────

def evaluate(
    script: str,
    sources: list[str],
    target_words: tuple[int, int] = (400, 6000),
    judge=heuristic_judge,
    check_faithfulness: bool = True,
) -> EvalReport:
    """Run all checks. `sources` is the ordered list of source texts, so
    sources[0] is [S1], sources[1] is [S2], etc. `judge` is swappable."""
    rep = EvalReport(n_sources=len(sources))
    used: set[int] = set()

    # Checks 1 & 2: walk sentences, tally coverage, collect tags.
    for sent in _split_sentences(script):
        tags = [int(n) for n in CITE_RE.findall(sent)]
        used.update(tags)
        for t in tags:
            if t < 1 or t > len(sources):
                rep.dangling_tags.append(t)

        # Is this a *narrative* sentence (real prose), or just a marker line?
        prose = MARKER_RE.sub("", CITE_RE.sub("", sent)).strip()
        if len(_WORD_RE.findall(prose)) < 4:
            continue  # marker/stylistic line — not counted for coverage
        rep.n_narrative_sentences += 1
        if tags:
            rep.n_cited_sentences += 1

    rep.coverage = (rep.n_cited_sentences / rep.n_narrative_sentences
                    if rep.n_narrative_sentences else 0.0)
    rep.unused_sources = [i + 1 for i in range(len(sources)) if (i + 1) not in used]

    # Check 3: structure.
    words = len(_WORD_RE.findall(script))
    rep.structure = {
        "has_music_cue": bool(re.search(r"\[MUSIC CUE", script, re.IGNORECASE)),
        "has_visual": bool(re.search(r"\[VISUAL", script, re.IGNORECASE)),
        "length_in_range": target_words[0] <= words <= target_words[1],
    }

    # Check 4: faithfulness of cited claims.
    if check_faithfulness:
        checked = supported = 0
        for sent in _split_sentences(script):
            tags = [int(n) for n in CITE_RE.findall(sent)]
            valid = [t for t in tags if 1 <= t <= len(sources)]
            if not valid:
                continue
            claim = MARKER_RE.sub("", CITE_RE.sub("", sent)).strip()
            cited_src = " ".join(sources[t - 1] for t in valid)
            checked += 1
            if judge(claim, cited_src):
                supported += 1
            else:
                rep.unfaithful_examples.append(claim)
        rep.faithfulness = supported / checked if checked else None

    return rep


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m src.eval.grounding_eval <script.txt> <sources.txt>")
        print("For authored data/scripts/ files use: python -m src.eval.run_script_eval")
        sys.exit(0)
    script = open(sys.argv[1], encoding="utf-8").read()
    sources = [l.strip() for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
    report = evaluate(script, sources)
    print(report.summary())
    sys.exit(0 if report.passed() else 1)