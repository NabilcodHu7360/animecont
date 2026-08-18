"""
captions.py — narration wav -> timed SRT.

WHY TRANSCRIBE AUDIO WE ALREADY HAVE THE TEXT FOR
We know exactly what was spoken (the script). What we don't know is WHEN each
word lands. tts.py chunks at ~250 chars, but a readable caption line is ~40, so
chunk timings would force us to interpolate — captions would drift inside every
chunk. Whisper gives real word-level timestamps, so lines break where the
narrator actually pauses.

Transcription isn't perfect on invented proper nouns (Schmelman, Tokikaze,
Gespenst, Althing), so we feed them as an initial_prompt to bias the decoder.
That's also exactly why captions are worth having: the TTS mispronounces those
names, and the caption carries the meaning the voice loses.

faster-whisper is used over openai-whisper deliberately: it runs on ctranslate2
and does NOT pull in transformers/diffusers, so it can't reignite the version
conflict between chatterbox-tts and diffusers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Names Whisper won't know. Biasing the decoder beats fixing 40 captions by hand.
SERIES_VOCAB: dict[str, str] = {
    # Per-series proper nouns to bias the decoder, e.g.:
    #   "jojo": "Gyro Zeppeli, Funny Valentine, Steel Ball Run, Tusk, D4C, ...",
}

MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CAPTION_SECONDS = 5.0


@dataclass
class Caption:
    index: int
    start: float
    end: float
    text: str


def _ts(seconds: float) -> str:
    """SRT timestamp: HH:MM:SS,mmm"""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def group_words(words: list[dict]) -> list[Caption]:
    """Word timings -> caption lines.

    Break on: sentence-ending punctuation, a long pause (natural beat), the
    character budget, or MAX_CAPTION_SECONDS. Breaking on pauses is what makes
    captions feel cut to the read rather than chopped by character count.
    """
    caps: list[Caption] = []
    cur: list[dict] = []

    def flush():
        if not cur:
            return
        text = " ".join(w["word"].strip() for w in cur).strip()
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        caps.append(Caption(len(caps) + 1, cur[0]["start"], cur[-1]["end"], text))

    for i, w in enumerate(words):
        cur.append(w)
        text_len = sum(len(x["word"]) for x in cur)
        dur = cur[-1]["end"] - cur[0]["start"]
        ends_sentence = w["word"].strip().endswith((".", "!", "?"))
        gap_next = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 0.0

        if (ends_sentence
                or gap_next > 0.45
                or text_len >= MAX_CHARS_PER_LINE * MAX_LINES
                or dur >= MAX_CAPTION_SECONDS):
            flush()
            cur = []
    flush()
    return caps


def wrap(text: str) -> str:
    """Wrap to at most MAX_LINES lines for on-screen readability."""
    import textwrap
    lines = textwrap.wrap(text, width=MAX_CHARS_PER_LINE)
    if len(lines) > MAX_LINES:
        # rebalance rather than spill a third line
        lines = textwrap.wrap(text, width=max(len(text) // MAX_LINES + 1,
                                              MAX_CHARS_PER_LINE))[:MAX_LINES]
    return "\n".join(lines)


def to_srt(caps: list[Caption]) -> str:
    out = []
    for c in caps:
        out.append(f"{c.index}\n{_ts(c.start)} --> {_ts(c.end)}\n{wrap(c.text)}\n")
    return "\n".join(out)


def generate(series: str, audio_path: Path | None = None,
             out_path: Path | None = None, model_size: str = "base") -> Path:
    from faster_whisper import WhisperModel

    audio_path = Path(audio_path or f"data/audio/{series}.wav")
    out_path = Path(out_path or f"data/subs/{series}.srt")
    if not audio_path.exists():
        raise FileNotFoundError(f"missing audio: {audio_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"{series}: transcribing {audio_path.name} [whisper-{model_size}, cpu]")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        initial_prompt=SERIES_VOCAB.get(series),
        vad_filter=True,
    )

    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
    if not words:
        raise RuntimeError("whisper returned no word timings")

    caps = group_words(words)
    out_path.write_text(to_srt(caps), encoding="utf-8")
    print(f"  {len(words)} words -> {len(caps)} captions")
    print(f"  wrote {out_path}")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.captions.captions jojo")
        print("       python -m src.captions.captions jojo --model small")
        sys.exit(2)
    series = sys.argv[1]
    size = "base"
    if "--model" in sys.argv:
        size = sys.argv[sys.argv.index("--model") + 1]
    generate(series, model_size=size)
