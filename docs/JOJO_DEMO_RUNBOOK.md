# JoJo Image-Rich Demo — Runbook

Goal: rebuild the JoJo video essay with **37 background images** (up from 16) for a
much livelier, cinematic demo. Average shot is ~7–8s instead of ~20s+.

The script (`data/scripts/jojo_script.md`) is already updated: 37 atmospheric,
character-free `[VISUAL:]` cues, mojibake fixed, narration unchanged. Everything
below runs **on your machine** (SD + Piper need local compute) from the project
root, inside the `.venv`.

---

## 0. Activate the venv (image env has diffusers 0.39)

```powershell
.\.venv\Scripts\Activate.ps1
```

## 1. Clear the stale 16-image render

Cue order changed, so old scene files must go (otherwise indices mismatch):

```powershell
Remove-Item data\images\jojo\* -Force
```

## 2. Cheap sanity check BEFORE the long batch

Render, then stop after the first two images and eyeball the style:

```powershell
python -m src.images.image_gen --sd data\scripts\jojo_script.md
# when scene_001.jpg appears in data\images\jojo\, press Ctrl+C
Start-Process data\images\jojo\scene_000.jpg
Start-Process data\images\jojo\scene_001.jpg
```

Check: warm golden desert light, saturated, real depth, **no people/figures**,
painterly — not muddy or flat. If off, tune the style suffix / negative prompt in
`src/images/image_gen.py` before spending hours. Upload the two JPGs and I'll judge.

## 3. Full image render (the long one)

```powershell
python -m src.images.image_gen --sd data\scripts\jojo_script.md
```

Expect **~37 images x ~5 min ≈ 3–3.5 hours** on CPU at 38 steps. It prints a
running ETA. Treat it as a background/overnight batch. Writes `scene_000..036.jpg`
and `scenes.json` (the timing manifest the assembler needs).

## 4. Narration (Piper — fast, works now)

```powershell
python -m src.voice.tts data\scripts\jojo_script.md
```

Writes `data/audio/jojo.wav` in seconds. (Chatterbox is the expressive option but
is stuck in the dependency split with SD — use Piper for this demo, or run
Chatterbox from the voice venv separately if you want the richer read later.)

Optional — confirm no cue text leaks into the read first:

```powershell
python -m src.voice.tts --dry-run data\scripts\jojo_script.md | Select-String "turquoise|reliquary|junkyard"
# should print nothing
```

## 5. Captions

```powershell
python -m src.captions.captions jojo
```

Writes `data/subs/jojo.srt` (faster-whisper over the narration).

## 6. Assemble the video

Preview the timeline (no rendering) to sanity-check pacing:

```powershell
python -m src.assembler.assemble jojo --dry-run
```

Then build the mp4 (Ken Burns motion + burned-in captions):

```powershell
python -m src.assembler.assemble jojo
# optional background music:
python -m src.assembler.assemble jojo --music path\to\music.mp3
```

Writes `outputs/jojo.mp4`.

---

## Order that saves time

1. Do step 2 (two-image check) FIRST — cheapest way to catch a style problem.
2. While the 3-hour image batch runs (step 3), it's blocking the GPU/CPU; do
   narration + captions (steps 4–5) before or after, not during, to keep the
   render fast.
3. Assemble last (step 6) once images + audio + srt all exist.

## Notes

- 37 cues over ~4.5–5 min of narration = every shot lands 6–13s. No collisions,
  no dead-air tail (verified against the assembler's timeline logic).
- All cues are deliberately character-free — consistent to generate and clear of
  the copyright issue that comes with reproducing licensed characters.
- Single source of truth is `data/scripts/jojo_script.md`. Don't hand-edit
  `scenes.json` or `data/pipper_scripts/` — they're regenerated.
