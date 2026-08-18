# Results & metrics

Detailed numbers behind AnimeCont. See the [README](../README.md) for the overview.

## Grounding — 10 scripts, all passing

Faithfulness is the column that matters: it's the mechanical proof that nothing was
invented.

| series | coverage | faithfulness | | series | coverage | faithfulness |
|---|---|---|---|---|---|---|
| blackclover | 62% | 100% | | jojo | 81% | 97% |
| chainsaw-man | 62% | 98% | | jujutsu-kaisen | 76% | 100% |
| frieren | 78% | 98% | | kimetsu-no-yaiba | 72% | 100% |
| gachiakuta | 91% | 100% | | solo-leveling | 81% | 92% |
| jigokuraku | 75% | 100% | | vinlandsaga | 69% | 94% |

Coverage varies by *citation style*, not accuracy: `[ch.30-53]` covers a whole
passage, so sentence-level coverage reads lower than per-chapter `[ch.81]` tags.
Worth stating plainly because the metric is easy to misread as a quality ranking.

## Cost — per video (every model local, $0.00 throughout)

| video | length | scenes | images (SD 1.5) | assemble |
|---|---|---|---|---|
| JoJo | 4.7 min | 37 | 197.3 min | 1.2 min |
| Solo Leveling | 5.1 min | 40 | 224.2 min | 1.1 min |
| Demon Slayer | 9.2 min | 43 | ~236 min | 1.9 min |

Images dominate at ~5.3 min/scene on CPU (Ryzen 9 / 32 GB, no GPU acceleration).
Narration (Chatterbox 0.5B) adds ~35 min for a ~700-word script and scales with length
— it runs in the separate voice venv and isn't logged in the same run file. Every stage
is $0.00; nothing calls a paid API.

**Per-stage breakdown, JoJo (the one fully instrumented run):**

| stage | wall clock | unit p50 | unit p95 | unit max |
|---|---|---|---|---|
| voice (chatterbox 0.5B, 18 chunks) | 35.1 min | 128s | 168s | 168s |
| images (SD 1.5, 37 scenes) | 197.3 min | 320s | 320s | 324s |
| assemble (ffmpeg) | 1.2 min | — | — | — |
| **total** | **~234 min** | | | |

Observability earns its keep *across* runs. This JoJo render stayed clean — a 168s
voice-chunk max, tight p50/p95. An earlier run did not: one Chatterbox
chunk failed to hit an end token and ground to the 1000-step cap at **2260s** — 20×
the median and half that run, completely invisible until it was logged. You only
know which runs are healthy because every one is measured. Ryzen 9 / 32GB / CPU-only
(AMD GPU has no acceleration on Windows).

## Three ingest strategies

Wikis are inconsistent, and picking the right mode per series is most of the work:

1. **Arc pages** — the default, when arc pages carry real plot prose.
2. **Chapter range** — when arc pages are stubs. Demon Slayer's arc pages held
   **351 words total**; chapter mode pulled **51,000** across 69 chapters.
3. **Hybrid / entity pages** — when chapters fail too. Vinland Saga kept only
   3/84 chapters, so Timeline + character pages carried it. Solo Leveling has no
   usable arc *or* chapter pages; its corpus is built from entity pages alone.

`corpus_quality.py` catches thin corpora at ingest rather than three stages later
in a bad script. That "catch → supplement → regenerate" loop is the actual workflow.
