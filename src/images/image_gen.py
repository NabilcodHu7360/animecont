"""
image_gen.py — Turn a script's [VISUAL:] cues into background images.

WHY NOT image_generator.py
The original module called Leonardo.ai (paid) and, with no key, downloaded
RANDOM stock photos from picsum — unrelated to the story, useless for judging a
cut, and needing network. It also fell back to generic DEFAULT_SCENE_PROMPTS
rather than reading the script.

This module instead:
  1. Parses the script's own [VISUAL: ...] cues — the image prompts are already
     authored there, positioned at the beats they illustrate.
  2. Records each cue's OFFSET in the spoken text, so the assembler can time
     images to the narration instead of splitting duration evenly.
  3. Swaps backends behind one interface (same pattern as llm.py / tts.py):
        placeholder — local PIL cards, instant, offline. Proves the pipeline.
        sd          — local Stable Diffusion. The quality pass.

STYLE
Prompts get a per-series style suffix so every frame shares one look. Cues are
deliberately atmospheric and character-free: consistent to generate, and clear
of the copyright problem that comes with reproducing licensed characters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VISUAL_RE = re.compile(r"\[VISUAL:\s*([^\]]+)\]", re.IGNORECASE)

# One coherent look per series. Chosen for Plunderer: cold blues for the Abyss,
# warm amber for the fragile peace — the story's emotional axis.
STYLE_SUFFIXES = {
    "plunderer": ("painterly anime background art, muted desaturated palette, "
                  "cold blue shadows with warm amber highlights, soft "
                  "atmospheric lighting, cinematic wide shot, melancholic, "
                  "no characters, no text"),
    "_default": ("painterly anime background art, cinematic wide shot, "
                 "atmospheric lighting, no characters, no text"),
}


@dataclass
class Scene:
    index: int
    prompt: str          # the raw cue text from the script
    offset: float        # 0.0-1.0 position in the spoken narration

    def full_prompt(self, series: str) -> str:
        suffix = STYLE_SUFFIXES.get(series, STYLE_SUFFIXES["_default"])
        return f"{self.prompt}, {suffix}"


def parse_scenes(script_text: str) -> list[Scene]:
    """Extract [VISUAL:] cues and where they fall in the SPOKEN text.

    Offset matters: images should change when the narration reaches the beat
    they illustrate. We measure position in spoken words (not raw markdown),
    because that's what maps to audio time.
    """
    from ..voice.tts import clean_script_for_tts, strip_header

    body = strip_header(script_text)
    scenes: list[Scene] = []
    total_spoken = len(clean_script_for_tts(script_text).split())
    if total_spoken == 0:
        return scenes

    for i, m in enumerate(VISUAL_RE.finditer(body)):
        # Spoken words BEFORE this cue = its position in the narration.
        before = clean_script_for_tts(body[:m.start()])
        offset = min(len(before.split()) / total_spoken, 1.0)
        scenes.append(Scene(index=i, prompt=m.group(1).strip(), offset=offset))
    return scenes


# ── backends ─────────────────────────────────────────────────────────────────

def _render_placeholder(scene: Scene, out_path: Path, series: str) -> Path:
    """Local card: gradient + the cue text. No network, instant. Lets you SEE
    which scene is which when checking the cut's timing."""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    W, H = 1280, 720
    # Cold-blue -> warm-amber vertical gradient, matching the intended style.
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, bot = (18, 28, 46), (74, 52, 30)
    for y in range(H):
        f = y / H
        d.line([(0, y), (W, y)],
               fill=tuple(int(top[c] + (bot[c] - top[c]) * f) for c in range(3)))

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
        small = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = small = ImageFont.load_default()

    d.text((40, 36), f"{series} — scene {scene.index + 1}", font=small,
           fill=(150, 170, 200))
    d.text((40, 62), f"@ {scene.offset:.0%} of narration", font=small,
           fill=(150, 170, 200))
    y = 180
    for line in textwrap.wrap(scene.prompt, width=46):
        d.text((40, y), line, font=font, fill=(235, 230, 220))
        y += 40

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=90)
    return out_path


def _render_sd(scene: Scene, out_path: Path, series: str,
               pipe=None) -> Path:
    """Local Stable Diffusion. SLOW on CPU (no AMD accel on Windows) — treat as
    an overnight batch, not interactive. `pipe` is passed in so the model loads
    once for the whole run."""
    if pipe is None:
        raise ValueError("_render_sd needs a preloaded pipe")
    img = pipe(scene.full_prompt(series),
               negative_prompt="text, watermark, signature, people, faces, "
                               "characters, letters",
               num_inference_steps=25, guidance_scale=7.5,
               width=768, height=432).images[0]
    img = img.resize((1280, 720))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=90)
    return out_path


def _load_sd():
    from diffusers import StableDiffusionPipeline
    import torch
    print("  loading stable diffusion (first run downloads ~4GB)...")
    pipe = StableDiffusionPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5", torch_dtype=torch.float32,
        safety_checker=None,
    )
    pipe = pipe.to("cpu")
    return pipe


# ── entry point ──────────────────────────────────────────────────────────────

def generate_for_script(script_path: Path, provider: str = "placeholder",
                        out_root: Path = Path("data/images")) -> list[Scene]:
    import json
    import time

    script_path = Path(script_path)
    series = script_path.name.replace("_script.md", "")
    text = script_path.read_text(encoding="utf-8")
    scenes = parse_scenes(text)
    if not scenes:
        raise ValueError(f"no [VISUAL:] cues found in {script_path}")

    out_dir = Path(out_root) / series
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{series}: {len(scenes)} scenes [{provider}]")

    from ..obs.run_log import stage
    pipe = _load_sd() if provider == "sd" else None
    t0 = time.time()
    with stage("images", series=series, provider=provider) as st:
      st.count(scenes=len(scenes))
      for s in scenes:
        p = out_dir / f"scene_{s.index:03d}.jpg"
        if provider == "placeholder":
            _render_placeholder(s, p, series)
        elif provider == "sd":
            t = time.time()
            _render_sd(s, p, series, pipe=pipe)
            st.sample(time.time() - t)       # per-image, for p50/p95/max
            done = s.index + 1
            eta = ((time.time() - t0) / done) * (len(scenes) - done)
            print(f"  scene {done}/{len(scenes)} {time.time()-t:.0f}s "
                  f"— eta {eta/60:.1f} min")
        else:
            raise ValueError(f"unknown image provider: {provider!r}")
    if provider == "placeholder":
        print(f"  wrote {len(scenes)} cards")

    # The assembler needs the offsets to time the cuts.
    manifest = out_dir / "scenes.json"
    manifest.write_text(json.dumps(
        [{"index": s.index, "offset": s.offset, "prompt": s.prompt,
          "file": f"scene_{s.index:03d}.jpg"} for s in scenes],
        indent=2), encoding="utf-8")
    print(f"  wrote {manifest}")
    return scenes


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.images.image_gen <script>            # placeholder cards")
        print("       python -m src.images.image_gen --sd <script>       # stable diffusion")
        print("       python -m src.images.image_gen --list <script>     # show cues only")
        sys.exit(2)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sp = Path(args[0])
    if "--list" in sys.argv:
        series = sp.name.replace("_script.md", "")
        for s in parse_scenes(sp.read_text(encoding="utf-8")):
            print(f"[{s.offset:5.0%}] {s.prompt}")
            print(f"        -> {s.full_prompt(series)[:100]}...")
        sys.exit(0)
    generate_for_script(sp, provider="sd" if "--sd" in sys.argv else "placeholder")
