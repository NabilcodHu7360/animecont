# AnimeCont

Turns "what happens in the manga after the anime ends?" into a finished, narrated,
cited video essay — wiki ingest → grounded script → evaluation → voice → images →
captions → MP4. Every model runs locally. No paid APIs anywhere in the pipeline.

**[▶ Watch the output — Plunderer, 6 min](https://youtu.be/NF5Li_yRDd0)** — generated
end to end by this pipeline: grounded script, cloned narration, 25 Stable Diffusion
backgrounds, burned-in captions. Every plot claim in it traces to a cited wiki chapter.

**The problem this is built around:** an LLM asked to recap a specific manga will
confidently invent reveals that never happened. For a video claiming to recount
canon, that isn't a rough edge — it's the whole ballgame. So retrieval, citation
and mechanical evaluation aren't résumé decorations bolted on at the end. They're
the reason the product can exist. Every plot claim in all 11 scripts traces to a
specific wiki chapter or arc, and a harness proves it.

## Pipeline

```
ingest → retrieve → generate → EVAL → voice → images → captions → assemble
                                 └── CI gate: coverage drops, build fails
```

| Stage | Module | What it does |
|---|---|---|
| Ingest | `src/ingest/` | Fandom MediaWiki API → citation-tagged corpus + quality gate |
| Retrieve | `src/grounding/` | BM25 + vector, fused by Reciprocal Rank Fusion |
| Generate | `src/generator/` | Provider-agnostic LLM (Gemini / Anthropic / Ollama), `[S#]` citation contract |
| **Eval** | `src/eval/` | Citation coverage + faithfulness. Gates everything downstream. |
| Voice | `src/voice/tts.py` | Piper (fast) or Chatterbox (expressive), reference-voice cloning |
| Images | `src/images/image_gen.py` | Local Stable Diffusion from the script's own `[VISUAL:]` cues |
| Captions | `src/captions/captions.py` | faster-whisper word timings → burned-in SRT |
| Assemble | `src/assembler/assemble.py` | FFmpeg: timeline, Ken Burns, caption burn-in |
| **Observability** | `src/obs/run_log.py` | Per-stage wall clock, p50/p95/max per unit of work |

## Results

**Grounding — 11 scripts, all passing.** Faithfulness is the column that matters:
it's the mechanical proof that nothing was invented.

| series | coverage | faithfulness | | series | coverage | faithfulness |
|---|---|---|---|---|---|---|
| blackclover | 62% | 100% | | jojo | 81% | 97% |
| chainsaw-man | 62% | 98% | | jujutsu-kaisen | 76% | 100% |
| frieren | 78% | 98% | | kimetsu-no-yaiba | 72% | 100% |
| gachiakuta | 91% | 100% | | plunderer | 60% | 91% |
| jigokuraku | 75% | 100% | | solo-leveling | 81% | 92% |
| vinlandsaga | 69% | 94% | | | | |

Coverage varies by *citation style*, not accuracy: `[ch.30-53]` covers a whole
passage, so sentence-level coverage reads lower than per-chapter `[ch.81]` tags.
Worth stating plainly because the metric is easy to misread as a quality ranking.

**Cost — one 6-minute video:**

| stage | wall clock | unit p50 | unit p95 | unit max | $ |
|---|---|---|---|---|---|
| voice (chatterbox 0.5B, 25 chunks) | 79.6 min | 111s | 141s | **2260s** | 0.00 |
| images (SD 1.5, 25 scenes) | 93.0 min | 230s | 234s | 234s | 0.00 |
| assemble (ffmpeg) | 1.0 min | — | — | — | 0.00 |
| **total** | **~174 min** | | | **$0.00** | |

That `unit max` of 2260s is a real p99 outlier: one Chatterbox chunk failed to hit
an end token and ground to the 1000-step cap — 20× the median, half the run, and
completely invisible until it was logged. Ryzen 9 / 32GB / CPU-only (AMD GPU has
no acceleration on Windows).

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

## Setup

```bash
pip install -r requirements.txt
python -m piper.download_voices --data-dir models/piper en_US-lessac-medium
```
FFmpeg must be on PATH.

**Two virtualenvs are required.** `chatterbox-tts` pins `diffusers==0.29.0`;
Stable Diffusion needs `diffusers>=0.31`. They cannot coexist, and the stages run
as separate commands, so isolate them:

```
.venv-voice   → chatterbox-tts (diffusers 0.29.0, safetensors 0.5.3)
.venv-image   → diffusers (modern) + stable diffusion
```
`faster-whisper` handles captions specifically because it runs on ctranslate2 and
pulls in neither package.

**Reference voice (optional, biggest quality win).** Drop a clean 10–15s mono
24kHz clip at `models/reference_voice.wav`. Gitignored — bring your own.

## Usage

```bash
python -m src.ingest.build_corpus && python -m src.ingest.corpus_quality
python -m src.eval.run_script_eval                       # gate before spending compute

python -m src.voice.tts --dry-run data/scripts/plunderer_script.md   # check spoken text
python -m src.voice.tts --chatterbox data/scripts/plunderer_script.md
python -m src.images.image_gen --sd data/scripts/plunderer_script.md
python -m src.captions.captions plunderer
python -m src.assembler.assemble plunderer

python -m src.obs.run_log report                         # where did the time go
```

## Engineering decisions

**Images are atmospheric, never characters.** Every `[VISUAL:]` cue describes a
mood or setting — *"two men facing each other in torrential rain"* — with
`no characters` in both prompt and SD negative prompt. Reproducing copyrighted
characters would be legally wrong and technically unreliable: diffusion models
can't hold a character on-model across 25 shots.

**Citations live in the script; the narrator never says them.** `tts.py` strips
`[ch.30-53]`, `[MUSIC CUE:]`, `[VISUAL:]` and markdown *in memory* at narration
time. The `.md` stays the single source of truth for eval and CI.

**Intensity is authored, not configured.** `[INTENSITY: high]` in the script sets
exaggeration per section — 0.8 for a climax, 0.45 for a quiet ending — so the
performance travels with the writing. cfg moves inversely, because exaggeration
speeds delivery up and cfg slows it back down.

**The assembler owns the timeline, not the script.** Cues collide (two at 9%),
cluster, and leave gaps. `build_timeline()` enforces a minimum shot length, forces
the first shot to 0 (or the video opens on 32 seconds of black), and stretches the
tail. Fixing it in code beats hand-tuning cue placement across eleven scripts.

## What didn't work (and what that taught)

**Small local LLMs can't do multi-constraint creative generation.** qwen2.5:14b on
Ollama produced uncited, book-report prose against a prompt demanding cinematic
structure *and* strict citation. Not a tuning problem — a capability ceiling.

**Piper is architecturally flat.** No amount of `length_scale` tuning makes it
expressive; it has no emotion model. Chatterbox 0.5B does — but its `exaggeration`
drives intensity *and speed* together, so a hot setting rushes.

**Chatterbox Turbo is 3× faster and useless here.** 30s/chunk vs 90s, and it logs
`"exaggeration not supported ... will be ignored"` — accepts the argument, drops it.
Speed without expression, so the 0.5B stays.

**The default speaker was the problem, not the parameters.** Hours went into
tuning exaggeration against a theatrical baseline. A 15-second reference clip
changed the delivery more than every parameter combined.

**Upstream bugs are load-bearing.** Chatterbox's reference-audio path mixes float64
and float32 across two consumers and crashes on *any* `audio_prompt_path` — a
pristine studio WAV fails identically. `_patch_chatterbox_dtypes()` coerces both.
Without it, voice cloning is impossible on either model.

## Status

Plunderer is complete end-to-end: wiki → corpus → cited script → eval → narration →
25 generated backgrounds → captions → a 6-minute MP4. All 11 scripts are written,
evaluated and CI-gated. The other ten are render-ready at roughly 3 CPU-hours each,
but rendering them would exercise identical code paths with different inputs — the
pipeline is the artifact, not the batch. See `docs/PROJECT_ROADMAP.md`.

## Licensing

Code is MIT. The data isn't, and that distinction matters: `data/corpus/` is built
from Fandom wikis, whose community content is **CC BY-SA 3.0** — so the corpus files
and the scripts derived from them carry share-alike terms, not MIT. Every passage
keeps its source in the heading (`## [series=frieren | page=Chapter_81 | section=Summary]`),
so attribution is mechanical rather than a promise. See `NOTICE` for the full picture,
including model licenses (SD 1.5 ships under CreativeML Open RAIL-M, which has
use-based restrictions worth reading before anyone reuses this).

## Scope: what I didn't build, and why

Three things a reviewer will look for and not find. Each was considered and cut for
a reason, and I'd rather say so than have the gaps read as oversights.

**Cross-encoder reranking.** The standard third stage of a production RAG stack: a
model that re-scores the top-k hits for precision after retrieval has done recall.
It earns its keep when retrieval returns a hundred plausible candidates from a large
corpus and the ordering genuinely decides the answer. Here the corpus is eleven
series of wiki prose, and for whole-story script generation the generator often
receives *most* of the relevant chapters as grounding anyway — coverage matters more
than ranking. Adding a reranker would buy a line on a checklist and roughly nothing
measurable. If the corpus grew to thousands of series, this is the first thing I'd add.

**LoRA / DPO fine-tuning.** Supervised fine-tuning wants thousands of clean
input–output pairs; DPO wants preference labels on top of that. I have eleven
scripts. I could run the training loop and produce a notebook proving I know the API
— but there'd be no honest before/after metric at the end, because eleven examples
can't move a model in a way that means anything. A fine-tune with nothing to show is
worse than no fine-tune. The interesting version of this project would be a small
model trained to turn plot summaries into structured beat sheets — that needs a
dataset that doesn't exist yet.

**Real-time streaming.** Latency budgets, time-to-first-token, graceful degradation
under a deadline. These matter enormously — and none of them apply to a pipeline
whose image stage takes 94 minutes on CPU. You cannot give a batch renderer a latency
budget without making it a different product. What *does* transfer is the resilience
half: missing wiki pages, 404s, stub chapters and dead slugs all degrade with a
warning rather than killing a multi-series build, because early on a single bad page
slug (`Liber`, in Solo Leveling) took down an entire run.

The pattern in all three: the competency is real, but forcing it into a system that
doesn't need it produces a worse system and a less honest portfolio.
