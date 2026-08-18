# Engineering notes

Design decisions, dead ends, tuning, and deliberate scope cuts. See the
[README](../README.md) for the overview and [RESULTS.md](RESULTS.md) for metrics.

## Engineering decisions

**Images are atmospheric, never characters.** Every `[VISUAL:]` cue describes a
mood or setting — *"two men facing each other in torrential rain"* — with
`no characters` in both prompt and SD negative prompt. Reproducing copyrighted
characters would be legally wrong and technically unreliable: base diffusion models
can't hold a character on-model across dozens of shots. Original consistent
characters are the headline of Future work.

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
tail. Fixing it in code beats hand-tuning cue placement across ten scripts.

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

## Tuning notes — what we did, and what would sharpen it

Two stages have obvious, low-risk headroom.

**Voice.** Every narration was cloned from a *single ~13-second* reference clip
through Chatterbox, with a `--ref` flag to swap the reference per video. That's enough
to sound like a specific person, but it's the floor, not the ceiling:

- A **longer, cleaner reference** — 20–40s, one speaker, no music or room noise,
  loudness-normalized. A casual phone memo clones *decently*; a clean read clones
  *stably*.
- The biggest untapped win: a reference that **contains the vocabulary the script will
  use**. A clip that already pronounces the hard proper nouns ("Gabimaru," "Tensen,"
  "Nichirin," "Stand") gives cloned prosody for exactly the words it otherwise mangles —
  so a short **per-series reference take** beats one generic clip.
- The `[INTENSITY]` markers already drive per-section delivery; they just need a
  cleaner base to shine.

**Images.** Atmospheric, character-free stills are the reliable path and look good.
Pushing past them surfaced real, instructive walls:

- CLIP silently truncates any prompt over **77 tokens** — long "design + scene + style"
  prompts lose their tail, so scene and style words must come *first* and stay short.
- The IP-Adapter character experiment held **identity** well but bled the reference's
  *composition*: full-body **character-sheet** references on plain grey produced
  plain-grey, sometimes duplicated figures instead of characters in scenes.
- The fixes that would matter most, in order: **single-figure, head-and-torso reference
  crops on a real background** (not sheets); a **trained LoRA per character** for
  identity *without* composition transfer; **ControlNet** for directed poses; **SDXL**
  for detail; and beneath all of it a **GPU** — at ~5 minutes per image on CPU, iteration
  itself is the bottleneck.

## Scope — what I didn't build, and why

Three things a reviewer will look for and not find. Each was considered and cut for
a reason.

**Cross-encoder reranking.** The standard third stage of a production RAG stack: a
model that re-scores the top-k hits for precision after retrieval has done recall.
It earns its keep when retrieval returns a hundred plausible candidates from a large
corpus and the ordering genuinely decides the answer. Here the corpus is ten
series of wiki prose, and for whole-story script generation the generator often
receives *most* of the relevant chapters as grounding anyway — coverage matters more
than ranking. If the corpus grew to thousands of series, this is the first thing I'd add.

**LoRA / DPO fine-tuning.** Supervised fine-tuning wants thousands of clean
input–output pairs; DPO wants preference labels on top of that. I have eleven
scripts. I could run the training loop and produce a notebook proving I know the API
— but there'd be no honest before/after metric, because ten examples can't move a
model meaningfully. The interesting version would be a small model trained to turn
plot summaries into structured beat sheets — that needs a dataset that doesn't exist yet.

**Real-time streaming.** Latency budgets, time-to-first-token, graceful degradation
under a deadline. None of them apply to a pipeline whose image stage takes ~94 minutes
on CPU. What *does* transfer is the resilience half: missing wiki pages, 404s, stub
chapters and dead slugs all degrade with a warning rather than killing a multi-series
build, because early on a single bad page slug (`Liber`, in Solo Leveling) took down an
entire run.

The pattern in all three: the competency is real, but forcing it into a system that
doesn't need it produces a worse system and a less honest portfolio.
