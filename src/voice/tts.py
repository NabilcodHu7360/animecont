"""
tts.py — Turn a video-essay script into narration audio.

WHY THIS EXISTS (and why not elevenlabs_tts.py)
The original voice module called the ElevenLabs HTTP API (paid, needs a key).
Piper is local, free and fast, but it's a completely different mechanism: a
subprocess reading an ONNX voice model, not a REST call. So rather than bolt
Piper onto an HTTP client, this module mirrors the pattern we already proved in
generator/llm.py — ONE interface, swappable backends:

    synthesize(text, out_path, provider="piper")

elevenlabs_tts.py is left intact; add it as a provider here if you ever want it.

THE HARD PART IS NOT THE AUDIO — IT'S THE CLEANING
Our scripts are authored markdown full of things a narrator must never say:
    ## ACT ONE — THE FAKE SCHMELMAN      <- heading
    [MUSIC CUE: a lone piano...]         <- production marker
    [VISUAL: a floating sky-island...]   <- image prompt
    [HOST] The anime left you...         <- speaker tag
    ...ruin the real Schmelman's legacy. [ch.30-53]   <- CITATION
    *Grounded in data/corpus/...*        <- provenance header
Left in, Piper would read "ch dot thirty dash fifty three" every few sentences.
clean_script_for_tts() strips all of it and leaves only spoken prose.
"""
from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

DEFAULT_VOICE = Path("models/piper/en_US-lessac-medium.onnx")

# A ~10s clean single-speaker clip. THE biggest quality lever: Chatterbox's
# default speaker has a theatrical baseline that no parameter tuning removes,
# because it's the speaker's style, not a setting. Clip *quality* matters more
# than length. Turbo expects one; the original model treats it as optional.
REFERENCE_VOICE = Path("models/reference_voice.wav")

# ── Chatterbox tuning ────────────────────────────────────────────────────────
# `exaggeration` drives intensity AND speed together — push it up and delivery
# gets dramatic *and* rushed; `cfg_weight` counter-slows the pacing. 0.4/0.3 was
# tuned against the DEFAULT speaker, whose baseline is theatrical. With a calm
# reference clip the anchor is different, so higher exaggeration is usable —
# re-sweep per reference rather than trusting these blindly.
# ONLY the 0.5B model honours these. Turbo ignores them (see _load_chatterbox).
# Picked by A/B sweep against the authored reference clip. 0.8/0.25 sounded
# good on a single dramatic line, but exaggeration drives speed too and that
# rush compounds over ~25 chunks — 0.65 holds up across a whole script.
# Override per-run with --exaggeration / --cfg.
CHATTERBOX_EXAGGERATION = 0.65
CHATTERBOX_CFG_WEIGHT = 0.3
# Autoregressive model: quality degrades on long inputs, so chunk tighter
# than Piper. ~50s of CPU compute per chunk of this size.
CHATTERBOX_MAX_CHARS = 300

# ── pronunciation ────────────────────────────────────────────────────────────
# TTS mangles invented proper nouns. These respellings are applied to the SPOKEN
# text only — the .md keeps the real spelling, so eval and captions are correct.
# Order matters: longer keys first so substrings don't clobber them.
PRONUNCIATIONS = {
    # demon slayer
    "Kokushibo": "Koh-koo-shee-boh", "Michikatsu": "Mee-chee-kaht-soo",
    "Tsugikuni": "Tsoo-gee-koo-nee", "Yoriichi": "Yoh-ree-ee-chee",
    "Kagaya Ubuyashiki": "Kah-gah-yah Oo-boo-yah-shee-kee",
    "Muzan Kibutsuji": "Moo-zahn Kee-boot-soo-jee",
    "Gyomei": "Gyoh-may", "Muichiro": "Moo-ee-chee-roh",
    "Kaigaux": "Kai-gah-koo", "Kaigaku": "Kai-gah-koo",
    "Tanjiro": "Tahn-jee-roh", "Nezuko": "Neh-zoo-koh",
    "Shinobu": "Shee-noh-boo", "Zenitsu": "Zeh-neet-soo",
    "Akaza": "Ah-kah-zah", "Hakuji": "Hah-koo-jee", "Koyuki": "Koh-yoo-kee",
    "Sanemi": "Sah-neh-mee", "Genya": "Gen-yah", "Obanai": "Oh-bah-nye",
    "Mitsuri": "Meet-soo-ree", "Tamayo": "Tah-mah-yoh",
    # jjk
    "Kenjaku": "Ken-jah-koo", "Sukuna": "Soo-koo-nah", "Megumi": "Meh-goo-mee",
    "Higuruma": "Hee-goo-roo-mah", "Mahoraga": "Mah-hoh-rah-gah",
    "Okkotsu": "Oh-koh-tsoo", "Yorozu": "Yoh-roh-zoo",
    "Tsumiki": "Tsoo-mee-kee", "Takaba": "Tah-kah-bah",
    # jigokuraku
    "Gabimaru": "Gah-bee-mah-roo", "Jigokuraku": "Jee-goh-koo-rah-koo",
    "Sagiri": "Sah-gee-ree", "Gantetsusai": "Gahn-tet-soo-sigh",
    "Chobei": "Choh-bay", "Yuzuriha": "Yoo-zoo-ree-hah",
    # others
    "Frieren": "Free-ren", "Himmel": "Him-mel", "Diagoldze": "Dee-ah-gold-zeh",
    "Thorfinn": "Thor-fin", "Askeladd": "Ass-keh-lad", "Jomsviking": "Yoms-viking",
    "Gudrid": "Goo-thrid", "Jinwoo": "Jin-woo", "Antares": "An-tah-reez",
    "Ashborn": "Ash-born", "Gountess": "Gown-tess",
}

# Production markers whose ENTIRE bracket is dropped, including inner text.
_MARKER_RE = re.compile(r"\[(?:MUSIC CUE|VISUAL|BEAT|SFX|INTENSITY)[^\]]*\]", re.IGNORECASE)
# [HOST] is a speaker tag: drop the tag, keep the line's prose.
_HOST_RE = re.compile(r"\[HOST\]\s*", re.IGNORECASE)
# Any remaining [...] is a citation ([ch.81], [ch.30-53], [Doll Festival Arc]).
_CITE_RE = re.compile(r"\[[^\]]*\]")
# Markdown noise.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s.*$", re.MULTILINE)
_HRULE_RE = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1", re.DOTALL)


def strip_header(script: str) -> str:
    """Drop the italic provenance block above the first '---' rule."""
    parts = script.split("\n---\n", 1)
    return parts[1] if len(parts) == 2 else script


_ALLCAPS_RE = re.compile(r"\b[A-Z]{2,}\b")


def _decap(text: str) -> str:
    """ALL-CAPS words get read out letter by letter ("TITLE" -> T-I-T-L-E).
    Every script's title line is caps, so this hits all of them. Title-case any
    purely alphabetic caps run; words containing digits (D4C, ACT2) are left
    alone because spelling those out IS correct."""
    out = _ALLCAPS_RE.sub(lambda m: m.group(0).title(), text)
    # str.title() capitalises after apostrophes: JOJO'S -> Jojo'S. Undo that.
    return re.sub(r"(\w)'(\w)", lambda m: f"{m.group(1)}'{m.group(2).lower()}", out)


def apply_pronunciations(text: str) -> str:
    """Respell proper nouns phonetically for the narrator only."""
    for name in sorted(PRONUNCIATIONS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", PRONUNCIATIONS[name], text)
    return text


def clean_script_for_tts(script: str, phonetic: bool = True,
                         header: bool = True) -> str:
    """Markdown script -> plain spoken prose. Order matters.

    `header=False` when the caller already stripped it — strip_header cuts at the
    first '---' rule, so running it on a mid-script fragment silently eats
    everything before that fragment's first rule.
    """
    t = strip_header(script) if header else script
    t = _MARKER_RE.sub("", t)        # kill [MUSIC CUE:...] / [VISUAL:...] wholly
    t = _HOST_RE.sub("", t)          # drop [HOST] tag, keep its sentence
    t = _CITE_RE.sub("", t)          # kill leftover citations
    t = _HEADING_RE.sub("", t)       # kill '## ACT ONE ...'
    t = _HRULE_RE.sub("", t)         # kill '---'
    t = _EMPHASIS_RE.sub(r"\2", t)   # **bold** / *italic* -> bare words
    # Em-dash: Piper ignores it, producing a run-on. A comma gives a real pause,
    # but ", " right after a title reads oddly, so use a period there instead.
    t = re.sub(r"\s*—\s*(?=[A-Z][A-Z ]{4,})", ". ", t)  # TITLE — CAPS -> period
    t = re.sub(r"\s*—\s*", ", ", t)                      # elsewhere -> comma
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n\n", t)
    lines = [ln.strip() for ln in t.split("\n")]
    t = "\n".join(ln for ln in lines if ln).strip()
    t = _decap(t)          # before pronunciations, so respellings still match
    return apply_pronunciations(t) if phonetic else t


# ── per-section intensity ────────────────────────────────────────────────────
# A single exaggeration for a whole script is a compromise: 0.65 carries the
# narration, but climaxes want 0.8. [INTENSITY: high] in the script sets the
# level from that point until the next marker, so intensity is authored into
# the writing rather than passed as a global flag. cfg drops as exaggeration
# rises, because exaggeration speeds delivery up and cfg slows it back down.
INTENSITY_RE = re.compile(r"\[INTENSITY:\s*(\w+)\]", re.IGNORECASE)
INTENSITY_LEVELS = {
    "low":    (0.45, 0.35),   # quiet, reflective
    "normal": (0.65, 0.30),   # default narration
    "high":   (0.80, 0.25),   # climaxes, reveals
}


def segment_by_intensity(script: str, default: tuple[float, float] | None = None):
    """Script -> [(spoken_text, exaggeration, cfg_weight)] in order.

    Splits on [INTENSITY:] markers BEFORE cleaning, because cleaning strips them.
    """
    default = default or INTENSITY_LEVELS["normal"]
    body = strip_header(script)
    parts = INTENSITY_RE.split(body)
    # split() -> [text, level, text, level, text, ...]
    segments: list[tuple[str, float, float]] = []
    level = default
    for i, part in enumerate(parts):
        if i % 2 == 1:                        # a captured level name
            level = INTENSITY_LEVELS.get(part.lower(), default)
            continue
        spoken = clean_script_for_tts(part, header=False)
        if spoken.strip():
            segments.append((spoken, level[0], level[1]))
    return segments


def chunk_text(text: str, max_chars: int = 1500) -> list[str]:
    """Split on sentence boundaries. Piper has no API limit, but chunking keeps
    memory sane on long scripts and makes failures easier to localise."""
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > max_chars:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur.strip())
    return chunks


def _piper_once(text: str, out_path: Path, voice: Path) -> None:
    """One Piper subprocess -> one wav. Uses `python -m piper` so it works even
    when the `piper` console script isn't on PATH (common on Windows)."""
    import sys
    cmd = [sys.executable, "-m", "piper",
           "-m", str(voice), "--output_file", str(out_path)]
    proc = subprocess.run(cmd, input=text.encode("utf-8"),
                          capture_output=True)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"piper failed (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'ignore')[:400]}"
        )


def _concat_wavs(parts: list[Path], out_path: Path) -> None:
    """Stitch wavs with the stdlib — no ffmpeg needed at this stage."""
    if len(parts) == 1:
        parts[0].replace(out_path)
        return
    with wave.open(str(parts[0]), "rb") as w0:
        params = w0.getparams()
    with wave.open(str(out_path), "wb") as out:
        out.setparams(params)
        for p in parts:
            with wave.open(str(p), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))
    for p in parts:
        p.unlink(missing_ok=True)


def _patch_chatterbox_dtypes() -> None:
    """Chatterbox's reference-audio path mixes float64 and float32 and crashes:
        RuntimeError: expected scalar type Double but found Float
        ValueError: input must have the type torch.float32, got torch.float64
    Two separate consumers are affected — the s3 tokenizer's mel matmul and the
    voice encoder's LSTM — so both get coerced. This is a bug in the library,
    not in our audio: a pristine studio wav fails identically. Without this,
    audio_prompt_path is unusable on BOTH the 0.5B and turbo models.
    """
    from chatterbox.models.s3tokenizer.s3tokenizer import S3Tokenizer
    if not getattr(S3Tokenizer.log_mel_spectrogram, "_animecont_patched", False):
        _orig_mel = S3Tokenizer.log_mel_spectrogram

        def _mel_f32(self, audio, *a, **k):
            if getattr(self, "_mel_filters", None) is not None:
                self._mel_filters = self._mel_filters.float()
            if hasattr(audio, "float"):
                audio = audio.float()
            return _orig_mel(self, audio, *a, **k)

        _mel_f32._animecont_patched = True
        S3Tokenizer.log_mel_spectrogram = _mel_f32

    from chatterbox.models.voice_encoder.voice_encoder import VoiceEncoder
    if not getattr(VoiceEncoder.forward, "_animecont_patched", False):
        _orig_fwd = VoiceEncoder.forward

        def _fwd_f32(self, mels, *a, **k):
            if hasattr(mels, "float"):
                mels = mels.float()
            return _orig_fwd(self, mels, *a, **k)

        _fwd_f32._animecont_patched = True
        VoiceEncoder.forward = _fwd_f32


def _load_chatterbox(turbo: bool = False):
    """Load Chatterbox once. The PerTh watermarker dependency doesn't resolve on
    all setups, so we swap in a pass-through BEFORE importing chatterbox.tts —
    it must be an object with .apply_watermark(), not None."""
    import perth

    class _NoWatermark:
        def apply_watermark(self, wav, sample_rate=None):
            return wav

    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        perth.PerthImplicitWatermarker = _NoWatermark

    _patch_chatterbox_dtypes()

    if turbo:
        # Turbo: 350M params, decoder distilled from 10 steps to 1 — ~3x faster
        # on CPU (~30s vs ~90s per chunk). BUT it logs
        #   "CFG, min_p and exaggeration are not supported by Turbo"
        # and silently ignores them. It accepts the kwargs and drops them, so
        # there is NO emotion control. Use it only when speed beats expression.
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        print("  loading chatterbox-turbo (no emotion control)...")
        return ChatterboxTurboTTS.from_pretrained(device="cpu")
    from chatterbox.tts import ChatterboxTTS
    print("  loading chatterbox 0.5B (emotion control)...")
    return ChatterboxTTS.from_pretrained(device="cpu")


def _synth_chatterbox(text: str, out_path: Path,
                      exaggeration: float = CHATTERBOX_EXAGGERATION,
                      cfg_weight: float = CHATTERBOX_CFG_WEIGHT,
                      audio_prompt_path: str | None = None,
                      turbo: bool = False) -> Path:
    """Expressive local narration. Model is non-deterministic: identical input
    can vary between runs, so tone may drift slightly across a long script."""
    import time
    import torchaudio as ta

    ref = audio_prompt_path
    if ref is None and REFERENCE_VOICE.exists():
        ref = str(REFERENCE_VOICE)
    if ref:
        print(f"  reference voice: {ref}")
    elif turbo:
        print("  WARNING: turbo expects a reference clip; using default speaker")
    else:
        print(f"  no {REFERENCE_VOICE} — using the default speaker "
              "(theatrical; a reference clip is the biggest quality win)")

    model = _load_chatterbox(turbo=turbo)      # load ONCE, reuse per chunk
    chunks = chunk_text(text, max_chars=CHATTERBOX_MAX_CHARS)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    t_start = time.time()

    for i, ch in enumerate(chunks):
        p = out_path.parent / f".{out_path.stem}_part{i:03d}.wav"
        t0 = time.time()
        kw: dict = {}
        if ref:
            kw["audio_prompt_path"] = ref
        if not turbo:
            # Turbo accepts these then logs "not supported ... will be ignored",
            # so passing them there is a silent no-op. Only send to the 0.5B.
            kw["exaggeration"] = exaggeration
            kw["cfg_weight"] = cfg_weight
        wav = model.generate(ch, **kw)
        # torchaudio defaults to 32-bit float WAV, which stdlib `wave` can't
        # read. Force int16 PCM so _concat_wavs works.
        ta.save(str(p), wav, model.sr, encoding="PCM_S", bits_per_sample=16)
        parts.append(p)
        done, total = i + 1, len(chunks)
        elapsed = time.time() - t_start
        eta = (elapsed / done) * (total - done)
        print(f"  chunk {done}/{total} ({len(ch)} chars) "
              f"{time.time()-t0:.0f}s — eta {eta/60:.1f} min")

    _concat_wavs(parts, out_path)
    print(f"  total {(time.time()-t_start)/60:.1f} min")
    return out_path


def synthesize(text: str, out_path: Path, provider: str = "piper",
               voice: Path = DEFAULT_VOICE, **kwargs) -> Path:
    """Clean prose -> narration wav. `provider` is the swap point.

    piper      — seconds, flat delivery. Good for iterating on the script.
    chatterbox — 0.5B. THE expressive one: honours exaggeration/cfg_weight.
                 ~90s per chunk on CPU (~35 min per script).
    turbo      — 350M, ~30s per chunk (3x faster) but NO emotion control.
                 Speed only; it silently ignores exaggeration.
    Both accept audio_prompt_path. A reference clip matters more than any knob.
    """
    if provider in ("chatterbox", "turbo"):
        return _synth_chatterbox(text, Path(out_path),
                                 turbo=(provider == "turbo"), **kwargs)
    if provider != "piper":
        raise ValueError(f"unknown tts provider: {provider!r}")
    if not Path(voice).exists():
        raise FileNotFoundError(
            f"voice model not found: {voice}\n"
            "Run: python -m piper.download_voices --data-dir models\\piper "
            "en_US-lessac-medium"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = chunk_text(text)
    tmp_dir = out_path.parent
    parts = []
    for i, ch in enumerate(chunks):
        p = tmp_dir / f".{out_path.stem}_part{i:03d}.wav"
        print(f"  narrating chunk {i+1}/{len(chunks)} ({len(ch)} chars)...")
        _piper_once(ch, p, Path(voice))
        parts.append(p)
    _concat_wavs(parts, out_path)
    return out_path


def _synth_chatterbox_segments(segments, out_path: Path,
                               audio_prompt_path: str | None = None,
                               turbo: bool = False) -> Path:
    """Narrate [(text, exaggeration, cfg)] segments, varying intensity per
    section. Everything else matches _synth_chatterbox."""
    import time
    import torchaudio as ta

    ref = audio_prompt_path
    if ref is None and REFERENCE_VOICE.exists():
        ref = str(REFERENCE_VOICE)
    if ref:
        print(f"  reference voice: {ref}")
    else:
        print(f"  no {REFERENCE_VOICE} — default speaker (theatrical; a "
              "reference clip is the biggest quality win)")

    model = _load_chatterbox(turbo=turbo)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # flatten to chunks, each carrying its section's intensity
    jobs: list[tuple[str, float, float]] = []
    for text, ex, cfg in segments:
        for ch in chunk_text(text, max_chars=CHATTERBOX_MAX_CHARS):
            jobs.append((ch, ex, cfg))

    levels = sorted({j[1] for j in jobs})
    print(f"  {len(jobs)} chunks, exaggeration levels used: {levels}")

    from ..obs.run_log import stage
    parts: list[Path] = []
    t_start = time.time()
    series = out_path.stem
    with stage("voice", series=series,
               provider="turbo" if turbo else "chatterbox") as st:
      st.count(chunks=len(jobs), sections=len(segments))
      st.note(reference=bool(ref))
      for i, (ch, ex, cfg) in enumerate(jobs):
        p = out_path.parent / f".{out_path.stem}_part{i:03d}.wav"
        t0 = time.time()
        kw: dict = {}
        if ref:
            kw["audio_prompt_path"] = ref
        if not turbo:
            kw["exaggeration"] = ex
            kw["cfg_weight"] = cfg
        wav = model.generate(ch, **kw)
        ta.save(str(p), wav, model.sr, encoding="PCM_S", bits_per_sample=16)
        parts.append(p)
        st.sample(time.time() - t0)      # per-chunk, for p50/p95/max
        done = i + 1
        eta = ((time.time() - t_start) / done) * (len(jobs) - done)
        print(f"  chunk {done}/{len(jobs)} ({len(ch)} chars, ex={ex}) "
              f"{time.time()-t0:.0f}s — eta {eta/60:.1f} min")

    _concat_wavs(parts, out_path)
    print(f"  total {(time.time()-t_start)/60:.1f} min")
    return out_path


def narrate_script(script_path: Path, out_dir: Path = Path("data/audio"),
                   provider: str = "piper", voice: Path = DEFAULT_VOICE,
                   out_path: Path | None = None,
                   **kwargs) -> Path:
    """End-to-end: data/scripts/jojo_script.md -> data/audio/jojo.wav

    out_path overrides the default data/audio/<series>.wav — handy for writing
    several voice takes of the same script side by side without renaming.
    """
    script_path = Path(script_path)
    raw = script_path.read_text(encoding="utf-8")
    series = script_path.name.replace("_script.md", "")
    out = Path(out_path) if out_path else Path(out_dir) / f"{series}.wav"

    if provider in ("chatterbox", "turbo"):
        # honour [INTENSITY:] markers unless the caller forced a value
        forced = "exaggeration" in kwargs or "cfg_weight" in kwargs
        if not forced and INTENSITY_RE.search(raw):
            segs = segment_by_intensity(raw)
            words = sum(len(s[0].split()) for s in segs)
            print(f"{series}: {words} spoken words (~{words/150:.1f} min) "
                  f"[{provider}, {len(segs)} intensity sections]")
            return _synth_chatterbox_segments(
                segs, out, turbo=(provider == "turbo"),
                audio_prompt_path=kwargs.get("audio_prompt_path"))
        spoken = clean_script_for_tts(raw)
        words = len(spoken.split())
        print(f"{series}: {words} spoken words (~{words/150:.1f} min) [{provider}]")
        return synthesize(spoken, out, provider=provider, **kwargs)

    spoken = clean_script_for_tts(raw)
    words = len(spoken.split())
    print(f"{series}: {words} spoken words (~{words/150:.1f} min) [{provider}]")
    return synthesize(spoken, out, provider=provider, voice=voice)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.voice.tts <script>              # piper (fast, flat)")
        print("       python -m src.voice.tts --chatterbox <script> # expressive (recommended)")
        print("       python -m src.voice.tts --turbo <script>      # 3x faster, NO emotion control")
        print("       ... --chatterbox --exaggeration 0.8 --cfg 0.25 <script>")
        print("       ... --chatterbox --ref path\\to\\voice.wav <script> # clone a different voice this run")
        print("       ... --out data\\audio\\name.wav <script>        # write to a specific file (no renaming)")
        print("       python -m src.voice.tts --dry-run   <script>  # print spoken text")
        print("       python -m src.voice.tts --save-clean <script> # write data/pipper_scripts/")
        sys.exit(2)
    dry = "--dry-run" in sys.argv
    save_clean = "--save-clean" in sys.argv
    # The script is the .md argument — picking it by extension avoids mistaking
    # a flag value (a --ref path, an --exaggeration number) for the script.
    md = [a for a in sys.argv[1:] if a.endswith(".md")]
    if not md:
        print("error: no <script>.md provided")
        sys.exit(2)
    sp = Path(md[0])
    spoken = clean_script_for_tts(sp.read_text(encoding="utf-8"))

    if save_clean:
        # DERIVED artifact — regenerate it, never hand-edit it. The .md in
        # data/scripts/ stays the single source of truth.
        out_dir = Path("data/pipper_scripts")
        out_dir.mkdir(parents=True, exist_ok=True)
        series = sp.name.replace("_script.md", "")
        cp = out_dir / f"{series}_spoken.txt"
        cp.write_text(
            "# AUTO-GENERATED from data/scripts/%s — do not edit.\n"
            "# Regenerate: python -m src.voice.tts --save-clean data/scripts/%s\n\n%s"
            % (sp.name, sp.name, spoken),
            encoding="utf-8",
        )
        print(f"wrote {cp}")
        sys.exit(0)

    if dry:
        # Show exactly what WOULD be spoken — check this before burning CPU.
        print(spoken)
        sys.exit(0)
    provider = "piper"
    if "--chatterbox" in sys.argv:
        provider = "chatterbox"
    elif "--turbo" in sys.argv:
        provider = "turbo"
    kw = {}
    if provider == "chatterbox":
        if "--exaggeration" in sys.argv:
            kw["exaggeration"] = float(sys.argv[sys.argv.index("--exaggeration") + 1])
        if "--cfg" in sys.argv:
            kw["cfg_weight"] = float(sys.argv[sys.argv.index("--cfg") + 1])
    # --ref lets you clone a different reference voice per run without touching
    # the default models/reference_voice.wav (chatterbox/turbo only).
    if "--ref" in sys.argv:
        kw["audio_prompt_path"] = sys.argv[sys.argv.index("--ref") + 1]
    out_path = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    out = narrate_script(sp, provider=provider, out_path=out_path, **kw)
    print(f"\nwrote {out}")
