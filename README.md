# AnimeCont

Turns "what happens in the manga after the anime ends?" into a finished, narrated,
cited video essay — wiki ingest → grounded script → evaluation → voice → images →
captions → MP4. Every model runs locally. No paid APIs anywhere in the pipeline.

**▶ Watch the output:**

- [JoJo's Bizarre Adventure](https://youtu.be/xU2NTKuiiOA)
- [Solo Leveling](https://youtu.be/xEX57cl4e1Y)
- [Demon Slayer](https://youtu.be/fec4XSQFMZw)
- [Hell's Paradise](https://youtu.be/P8asWqpduZI)

Each is generated end to end by this pipeline: grounded script, cloned narration,
dozens of Stable Diffusion backgrounds, burned-in captions. Every plot claim traces
to a cited wiki chapter.

**The problem this is built around:** an LLM asked to recap a specific manga will
confidently invent reveals that never happened. For a video claiming to recount
canon, that isn't a rough edge — it's the whole ballgame. So retrieval, citation and
mechanical evaluation aren't résumé decorations bolted on at the end; they're the
reason the product can exist. Every plot claim in all 10 scripts traces to a specific
wiki chapter or arc, and a harness proves it. This is an actively evolving project —
**Future work** below lays out where it's headed.

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

**Status:** three series fully realized end to end (JoJo, Solo Leveling, Demon Slayer;
Hell's Paradise too). All 10 scripts are written, evaluated and CI-gated; the rest are
render-ready at ~3–4 CPU-hours each. Grounding, evaluation and observability — the hard
part — work today. Numbers in [docs/RESULTS.md](docs/RESULTS.md).

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

**Reference voice (optional, biggest quality win).** Drop a clean 20–40s mono 24kHz
clip at `models/reference_voice.wav`, ideally one that speaks the series' proper nouns
(see Limitations). Gitignored — bring your own.

## Usage

```bash
python -m src.ingest.build_corpus && python -m src.ingest.corpus_quality
python -m src.eval.run_script_eval                       # gate before spending compute

python -m src.voice.tts --dry-run data/scripts/jojo_script.md   # check spoken text
python -m src.voice.tts --chatterbox data/scripts/jojo_script.md
python -m src.images.image_gen --sd data/scripts/jojo_script.md
python -m src.captions.captions jojo
python -m src.assembler.assemble jojo

python -m src.obs.run_log report                         # where did the time go
```

## Limitations

*Shared across all four videos: narration is cloned from a single ~13s reference clip,
so proper nouns aren't always crisp; every image is a character-free still rendered on
CPU (~5 min each). Per-video specifics:*

**JoJo's Bizarre Adventure**
- SD ignores specific props — cues like "a starting gate with banners" render as generic desert rock.
- Early shots drifted painterly before the style was locked to photoreal.
- The script began sparse at 16 cues; densified to 37 for pacing.

**Solo Leveling**
- One shot rendered a stray human figure, breaking the otherwise character-free look.
- The dark violet palette occasionally goes muddy / low-contrast.
- A few warm-toned ending beats clash with the series' dark style suffix.

**Demon Slayer**
- Several shots lean painterly / woodblock — SD ties "Taisho-era Japan" to ukiyo-e despite the photoreal negative.
- A "paper-screen room" cue first rendered the scene *on a TV screen*; fixed by rewording + re-render.
- Densest script (43 cues) — the longest render and the most style variance.

**Hell's Paradise**
- The character (IP-Adapter) cut looked like character sheets on plain backgrounds, so it shipped atmospheric instead.
- Some cues that describe figures render as empty scenes (the no-people negative wins), reading abstract.
- Built last, so it hits the same limits as the others without new fixes.

The planned corrections for these live in **Future work** and
[docs/ENGINEERING.md](docs/ENGINEERING.md) (tuning notes): better per-series voice
references, single-figure reference crops, a per-character LoRA, ControlNet, SDXL, and
a GPU to make iteration fast.

## Future work

Concrete, achievable goals, ordered by value-to-effort:

1. **GPU rendering.** The single highest-leverage change. CPU-only makes every
   experiment a multi-hour wait; a GPU turns the image stage from overnight to minutes.
2. **Better voice references.** Record a clean ~30s per-series reference that includes
   the series' proper nouns, and A/B it against the current clip. Low effort, clear win.
3. **Consistent original cast via LoRA.** Train a small LoRA per *original* character
   design so a cast holds across a whole video without the character-sheet bleed that
   IP-Adapter showed.
4. **Motion over stills.** AnimateDiff or Stable Video Diffusion on key beats, so shots
   move instead of relying on Ken Burns pans.
5. **SDXL image upgrade.** Higher resolution and prompt adherence than SD 1.5, once a
   GPU makes it affordable.
6. **One-command full run.** Batch all ten series end to end behind the eval gate,
   failing loudly on any quality regression.
7. **Beat-sheet fine-tune.** A small model that turns a plot summary into the structured
   `[MUSIC CUE]/[VISUAL]` beat sheet — the one honest fine-tuning story here.

**Honest caveat on the character work.** Any version that puts recognizable characters
on screen lives on a legal line, not just a technical one: original designs that stand
in for roles are fine, but recreating a studio's specific character designs — even
"changed a little" — is reproduction. This stays a portfolio / fan-commentary project,
and the character-design boundary is one to treat deliberately.

## Licensing

Code is MIT. The data isn't: `data/corpus/` is built from Fandom wikis, whose community
content is **CC BY-SA 3.0** — so the corpus files and scripts derived from them carry
share-alike terms, not MIT. Every passage keeps its source in the heading, so
attribution is mechanical. See `NOTICE` for the full picture, including model licenses
(SD 1.5 ships under CreativeML Open RAIL-M).

## Deeper detail

- **[docs/RESULTS.md](docs/RESULTS.md)** — grounding eval (all 10 scripts), per-video
  cost/latency, observability, and the three wiki-ingest strategies.
- **[docs/ENGINEERING.md](docs/ENGINEERING.md)** — design decisions, what didn't work,
  voice/image tuning notes, and deliberate scope cuts.
- **[docs/PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)** — longer-range roadmap.
