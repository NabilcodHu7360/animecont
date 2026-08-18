"""
transcribe.py — quick transcription of audio notes (e.g. WhatsApp voice memos)
using the faster-whisper model already installed for captions.

Usage (in .venv):
    python -m src.voice.transcribe "Video Project 20.m4a"
    python -m src.voice.transcribe "WhatsApp Audio ....ogg" "WhatsApp Audio ....ogg"

Handles mixed languages (e.g. Urdu-English) automatically. Prints the transcript
so you can paste it back. Uses the 'small' model for a good speed/accuracy balance
on mixed-language speech; pass --model medium for higher accuracy if needed.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print('Usage: python -m src.voice.transcribe "file1" ["file2" ...] [--model small|medium]')
        sys.exit(2)
    size = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "small"

    from faster_whisper import WhisperModel
    model = WhisperModel(size, device="cpu", compute_type="int8")

    for f in args:
        p = Path(f)
        if not p.exists():
            print(f"\n### {f} — NOT FOUND")
            continue
        segments, info = model.transcribe(str(p), task="transcribe")
        print(f"\n### {p.name}  (detected language: {info.language})\n")
        print(" ".join(s.text.strip() for s in segments))


if __name__ == "__main__":
    main()
