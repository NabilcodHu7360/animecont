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

# One coherent look per series, so every frame shares one palette and mood.
STYLE_SUFFIXES = {
    # "empty landscape, no people" leads each suffix: positive-prompt emptiness
    # is a stronger signal than a negative, and front position survives CLIP's
    # 77-token cap. Style follows. Keep total short so scene text isn't crowded.
    # Locked to ONE look — photoreal cinematic. The earlier "anime key art,
    # painterly" wording hedged and SD 1.5 resolved it inconsistently (mostly
    # photoreal, occasional matte-painting outliers). Committing to photoreal +
    # anti-painting negatives (below) keeps all 37 frames on the same look.
    "jojo": ("empty landscape, no people, no characters, cinematic photograph, "
             "photorealistic, golden-hour desert, dramatic volumetric light, "
             "warm saturated color, ultra detailed, sharp focus"),
    # Photoreal per-series palettes, matching each story's setting. Same locked
    # photoreal look as jojo (anti-painting negatives applied below).
    "gachiakuta": ("empty landscape, no people, no characters, cinematic "
                   "photograph, photorealistic, gritty industrial wasteland, "
                   "mountains of refuse, overcast grey sky, rust and grime, "
                   "high contrast, dramatic light, ultra detailed"),
    "solo-leveling": ("empty scene, no people, no characters, cinematic "
                      "photograph, photorealistic, dark fantasy dungeon, "
                      "glowing blue and violet magic light, ominous shadows, "
                      "modern city at night, dramatic volumetric light, "
                      "ultra detailed"),
    "kimetsu-no-yaiba": ("empty landscape, no people, no characters, cinematic "
                         "photograph, photorealistic, moonlit Taisho-era Japan, "
                         "misty forest and traditional architecture, deep indigo "
                         "night, warm lantern glow, dramatic light, ultra detailed"),
    "jigokuraku": ("empty scene, no people, no characters, cinematic photograph, "
                   "photorealistic, mystical japanese island, ancient palaces and "
                   "giant glowing flowers, blood-red mist, bioluminescent petals, "
                   "ominous, dramatic light, ultra detailed"),
    "_default": ("empty landscape, no people, no characters, cinematic anime "
                 "key art, painterly, dramatic light"),
}


def _character_design(series: str, role: str) -> str | None:
    """The original design description for a role, from gen_characters.ROLES.
    Prepended to the prompt so the render matches the locked reference design."""
    try:
        from .gen_characters import ROLES
        return ROLES.get(series, {}).get(role)
    except Exception:
        return None


@dataclass
class Scene:
    index: int
    prompt: str          # the raw cue text (CHAR= stripped out)
    offset: float        # 0.0-1.0 position in the spoken narration
    char: str | None = None   # role from [VISUAL: CHAR=role | ...], else None

    def full_prompt(self, series: str) -> str:
        suffix = STYLE_SUFFIXES.get(series, STYLE_SUFFIXES["_default"])
        if self.char:
            # Identity comes from the IP-Adapter reference, so the text focuses on
            # SCENE + ACTION (kept first so CLIP's 77-token cap doesn't clip it),
            # plus a short photoreal tag. We deliberately do NOT reuse the
            # "empty scene, no people" style suffix here — we want the figure.
            return (f"{self.prompt}, in a detailed scene, cinematic photograph, "
                    "photorealistic, dramatic light")
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
        raw = m.group(1).strip()
        # Optional "CHAR=role | ..." prefix places a cast design in this shot.
        char = None
        cm = re.match(r"CHAR=([\w-]+)\s*\|\s*(.*)", raw, re.IGNORECASE)
        if cm:
            char = cm.group(1).lower()
            raw = cm.group(2).strip()
        scenes.append(Scene(index=i, prompt=raw, offset=offset, char=char))
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


IP_ADAPTER_SCALE = 0.5   # identity strength; lower lets the scene/background show


def _render_sd(scene: Scene, out_path: Path, series: str,
               pipe=None, ip_image=None, ip_scale: float = 0.0) -> Path:
    """Local Stable Diffusion. SLOW on CPU (no AMD accel on Windows) — treat as
    an overnight batch, not interactive. `pipe` is passed in so the model loads
    once for the whole run. When ip_image is given (a character reference) the
    pipe must already have an IP-Adapter loaded; ip_scale sets its influence."""
    if pipe is None:
        raise ValueError("_render_sd needs a preloaded pipe")
    # Establishing shots suppress people; CHARACTER shots must NOT (we want the
    # figure), so they only drop quality/style junk, never "person/face".
    if scene.char:
        negative = "text, watermark, signature, extra limbs, deformed, blurry, lowres"
    else:
        negative = ("people, person, human, man, woman, characters, figure, "
                    "crowd, cyclist, rider, jockey, face, "
                    "text, watermark, blurry, lowres")
    if series in ("jojo", "gachiakuta", "solo-leveling", "kimetsu-no-yaiba",
                  "jigokuraku"):
        negative += (", painting, digital painting, illustration, drawing, "
                     "sketch, cartoon, anime, matte painting, canvas texture, "
                     "brush strokes, oversaturated cg render")
    kwargs = dict(negative_prompt=negative, num_inference_steps=38,
                  guidance_scale=7.5, width=768, height=432)
    if ip_image is not None:
        pipe.set_ip_adapter_scale(ip_scale)   # 0.0 on establishing shots = no effect
        kwargs["ip_adapter_image"] = ip_image
    img = pipe(scene.full_prompt(series), **kwargs).images[0]
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
                        out_root: Path = Path("data/images"),
                        force: bool = False,
                        characters: bool = False) -> list[Scene]:
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
    n_char = sum(1 for s in scenes if s.char)
    print(f"{series}: {len(scenes)} scenes [{provider}]"
          + (f", {n_char} with cast (IP-Adapter)" if characters else ""))

    from ..obs.run_log import stage
    pipe = _load_sd() if provider == "sd" else None

    # Character mode: load the IP-Adapter once and each role's locked reference.
    ip_refs, ip_blank = {}, None
    if provider == "sd" and characters:
        from diffusers.utils import load_image
        from PIL import Image as _Image
        print("  loading IP-Adapter (first run downloads the adapter weights)...")
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder="models",
                             weight_name="ip-adapter_sd15.bin")
        char_dir = Path("data/characters") / series
        for role in sorted({s.char for s in scenes if s.char}):
            ref = char_dir / f"{role}.png"
            if not ref.exists():
                raise FileNotFoundError(f"missing character reference: {ref}")
            ip_refs[role] = load_image(str(ref))
        ip_blank = _Image.new("RGB", (224, 224), (128, 128, 128))  # scale-0 filler
        print(f"  loaded {len(ip_refs)} character references")

    t0 = time.time()
    with stage("images", series=series, provider=provider) as st:
      st.count(scenes=len(scenes))
      for s in scenes:
        p = out_dir / f"scene_{s.index:03d}.jpg"
        # Resume: skip images that already exist (unless --force). Lets a run
        # continue after a Ctrl+C / crash without re-rendering finished scenes.
        # To regenerate after a style change, pass force=True or delete the dir.
        if provider == "sd" and not force and p.exists():
            print(f"  scene {s.index + 1}/{len(scenes)} exists — skip")
            continue
        if provider == "placeholder":
            _render_placeholder(s, p, series)
        elif provider == "sd":
            t = time.time()
            if characters and s.char:
                _render_sd(s, p, series, pipe=pipe, ip_image=ip_refs[s.char],
                           ip_scale=IP_ADAPTER_SCALE)
            elif characters:
                # establishing shot: keep IP-Adapter loaded but neutral (scale 0)
                _render_sd(s, p, series, pipe=pipe, ip_image=ip_blank, ip_scale=0.0)
            else:
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
        print("       python -m src.images.image_gen --sd --force <script> # re-render all (ignore existing)")
        print("       python -m src.images.image_gen --sd --characters <script> # place cast designs via IP-Adapter")
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
    generate_for_script(sp, provider="sd" if "--sd" in sys.argv else "placeholder",
                        force="--force" in sys.argv,
                        characters="--characters" in sys.argv)
