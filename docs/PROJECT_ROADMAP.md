# AnimeCont — Complete Project Roadmap

*A step-by-step overview of the whole pipeline: where we are, what's left, and the order to do it in. AnimeCont turns "what happens in the manga after the anime ends" into finished, grounded, cited video essays.*

---

## The Big Picture

The product is a **finished video summary** of a manga's post-anime story. Four production stages, wrapped in the engineering that makes it trustworthy and repeatable:

```
  INGEST → RETRIEVE → GENERATE(script) → EVAL → VOICE → IMAGES → ASSEMBLE(video)
   [done]   [done]      [done, 12 scripts]  [next]  [adapt]  [adapt]   [adapt]
                                                └──── observability + CI wrap around all of it ────┘
```

The #1 product risk is **factual faithfulness** — an LLM inventing plot. That's why grounding, citations, and evaluation aren't add-ons; they're the spine.

---

## STATUS: What's Done

**Stage 0–3 are complete.**

- **Ingest** (`src/ingest/`): Fandom MediaWiki client, boundary filter (trims pre-anime content), corpus builder, and a quality gate. Three proven ingest strategies:
  1. Arc-page pulls (most series)
  2. Chapter-range mode for series with stub arc pages (Frieren, Demon Slayer)
  3. Hybrid / entity-page sourcing when chapters also fail (Vinland Saga, Solo Leveling)
- **Retrieve** (`src/grounding/`): corpus loader, chunker, BM25 + vector retrievers, hybrid retriever (Reciprocal Rank Fusion) behind a shared Retriever protocol.
- **Generate** (`src/generator/`): grounded generator with a strict `[S#]` citation contract, budget-aware source assembly, provider-agnostic LLM adapter (Gemini / Anthropic / Ollama).
- **12 scripts written** (`data/scripts/`): all cited to their source arcs/chapters/pages.

**Key finding already documented:** small local models (Ollama qwen2.5) produce weak, uncited output on multi-constraint creative prompts. Scripts were authored with a stronger model in the loop; this is a portfolio result about model capability vs. task complexity, not a blocker.

---

## STAGE 4 — Evaluation (DO THIS NEXT)

**Why first:** everything downstream (voice, images, video) is built from the script. If a script has weak citations or hallucinated beats, we want to catch it *before* spending time turning it into a video. Eval is the cheap gate that protects expensive stages.

**Code exists:** `src/eval/grounding_eval.py` — checks dangling tags, citation coverage, structural compliance, and faithfulness (heuristic word-overlap + optional LLM-judge).

**Steps:**
1. Run the eval harness over all 12 scripts in `data/scripts/`.
2. Read the report per script: citation coverage %, any dangling/broken tags, structural checks.
3. Expect variation — e.g. Gachiakuta and any thin-sourced series will score differently from richly-sourced ones (Demon Slayer, Vinland Saga). That variation is itself a finding.
4. Fix or flag anything that fails. This closes the "catch → supplement → regenerate" loop we used during ingest.
5. Save the eval output as a baseline — CI (Stage 8) will later gate on it.

**Deliverable:** an eval report table (series × metrics) you can show in the portfolio.

---

## STAGE 5 — Voice / Narration

**Code exists:** `src/voice/elevenlabs_tts.py`. It already has `clean_script_for_tts()` that strips `[HOST]`, `[VISUAL:]`, `[MUSIC CUE:]`, `[BEAT]` markers, chunks text to stay under API limits, and stitches audio.

**The catch:** it's built for the **ElevenLabs API (paid)**. Same friction as the LLM stage.

**Steps:**
1. Decide the voice backend:
   - **Free/local (recommended):** swap in a local TTS engine (e.g. Piper, Coqui TTS, or `pyttsx3` for a quick baseline). Local = no API cost, runs on your CPU.
   - **Free tier:** ElevenLabs free tier if the quota is workable for short runs.
2. Refactor `elevenlabs_tts.py` into a provider-agnostic `tts.py` — mirror exactly what we did with `llm.py` (one interface, swappable backends). This is a clean, reusable pattern the portfolio already demonstrates once.
3. Confirm `clean_script_for_tts()` correctly strips *our* marker set (verify against an actual script — the markers must match).
4. Generate narration for ONE script end-to-end first (suggest a shorter one).
5. Listen. Check pacing, mispronunciations, marker leakage.

**Deliverable:** `data/audio/<series>_narration.mp3` for one series, then batch.

---

## STAGE 6 — Background Images

**Code exists:** `src/images/image_generator.py`. Built for **Leonardo.ai (paid)**, but already has a no-API-key fallback and can read scene prompts.

**Key advantage:** our scripts have explicit `[VISUAL: ...]` cues — the image prompts are already written into every script. The generator should parse those, not use the generic `DEFAULT_SCENE_PROMPTS`.

**Steps:**
1. Add a parser that extracts `[VISUAL: ...]` lines from a script → an ordered list of image prompts with their positions.
2. Choose the image backend:
   - **Free/local:** local Stable Diffusion (AUTOMATIC1111 or ComfyUI) — but note your AMD GPU on Windows has no acceleration, so this would be slow on CPU. Test feasibility.
   - **Free tier / free stock:** a free image API, or the existing placeholder-download fallback for a first pass.
3. Refactor into a provider-agnostic `image_gen.py` (same pattern again).
4. Generate images for the `[VISUAL:]` cues of ONE script.
5. Sanity-check style consistency across images (anime aesthetic, coherent look).

**Content-safety note:** keep prompts to atmospheric/scene backgrounds, not copyrighted character likenesses — safer and more legally sound for a portfolio piece.

**Deliverable:** `data/images/<series>/scene_NN.png` aligned to the script's visual cues.

---

## STAGE 7 — Video Assembly

**Code exists:** `src/assembler/video_assembler.py` — uses **FFmpeg (free)**, already handles audio duration probing and music ducking (music at ~15% under narration). This stage has no paid dependency.

**Steps:**
1. Install/confirm FFmpeg on the machine.
2. Timing logic: map each `[VISUAL:]` image to the span of narration it belongs to, so images change roughly in sync with the script beats. (Simplest v1: divide narration duration evenly across images; better v2: align to marker positions.)
3. Optional: background music bed (needs a royalty-free source — the `music/` dir suggests this was planned).
4. Assemble ONE full video: narration + timed images (+ optional music) → MP4.
5. Watch it start to finish.

**Deliverable:** `outputs/<series>.mp4` — the first complete AnimeCont video.

---

## STAGE 8 — Observability, CI, Hardening (the "production-grade" layer)

This is what turns a working pipeline into a *portfolio-grade* one. Do it after one full video proves the pipeline end-to-end.

- **Observability:** log cost, latency, and token/character counts per stage per video. A simple per-run JSON/CSV report ("this video took N minutes, cost $X, used Y tokens") is a strong portfolio artifact.
- **CI regression gating:** wire the Stage-4 eval into `.github/` CI so any change that drops citation coverage below a threshold fails the build. You already have a `.github` dir — this is the natural home.
- **Hardening:** the graceful-skip patterns we added (missing pages, bad slugs, encoding) generalized across the pipeline; audit each stage for the same resilience.
- **Batch runner:** one command that takes a series from registry → finished MP4, so all 12 can be produced repeatably.

---

## Recommended Order (and why)

1. **Eval now** — cheap gate, protects everything downstream, produces a portfolio table.
2. **One full video next (Voice → Images → Assemble for a SINGLE series)** — proving the *entire* pipeline once end-to-end is worth more than 12 half-finished stages. Pick one series and take it all the way to MP4.
3. **Then batch** the remaining 11 through the proven pipeline.
4. **Then the observability/CI/hardening layer** on top.

The guiding principle throughout: **prove one complete vertical slice before scaling horizontally.**

---

## Open Decisions (flag these before starting the media stages)

- **TTS backend:** local (Piper/Coqui, free, CPU) vs. ElevenLabs free tier? → shapes Stage 5.
- **Image backend:** local SD (slow on your AMD/Windows CPU) vs. free API vs. stock fallback? → shapes Stage 6.
- **Music:** include a royalty-free music bed, or narration-only for v1?

None of these block Stage 4 (eval), which needs no new dependencies — so we can start there immediately while deciding the media backends.
