"""
elevenlabs_tts.py
Converts script text to MP3 narration via ElevenLabs API.
Handles chunking (free tier limit) and stitches audio automatically.
"""
import os
import requests
import time
from pathlib import Path


ELEVENLABS_API = "https://api.elevenlabs.io/v1"
CHUNK_SIZE = 2400  # chars — safe for free tier


def clean_script_for_tts(script: str) -> str:
    """Strips stage directions from script before sending to TTS."""
    lines = script.split("\n")
    clean = []
    for line in lines:
        # Remove lines that are purely stage directions
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        # Remove inline markers but keep the surrounding text
        for marker in ["[BEAT]", "[HOST]", "[MUSIC CUE:", "[VISUAL:", "[MUSIC SWELL]", "[MUSIC OUT]"]:
            line = line.replace(marker, "")
        clean.append(line)
    return "\n".join(clean).strip()


def chunk_text(text: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    """Splits text at sentence boundaries to stay under API limits."""
    chunks = []
    current = ""
    sentences = text.replace("\n", " ").split(". ")

    for sentence in sentences:
        if len(current) + len(sentence) < max_chars:
            current += sentence + ". "
        else:
            if current.strip():
                chunks.append(current.strip())
            current = sentence + ". "

    if current.strip():
        chunks.append(current.strip())
    return chunks


def generate_audio_chunk(text: str, voice_id: str, api_key: str, output_path: Path) -> bool:
    """Calls ElevenLabs API for one chunk. Returns True on success."""
    url = f"{ELEVENLABS_API}/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        },
    }

    r = requests.post(url, json=payload, headers=headers, timeout=60)
    if r.status_code == 200:
        output_path.write_bytes(r.content)
        return True
    else:
        print(f"  ElevenLabs error {r.status_code}: {r.text[:200]}")
        return False


def script_to_audio(script: str, output_dir: Path, voice_id: str = None) -> Path | None:
    """
    Main entry point. Converts full script to a single MP3.
    Returns path to final audio file, or None if failed.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("  No ELEVENLABS_API_KEY set. Skipping voice generation.")
        return None

    voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean + chunk
    clean = clean_script_for_tts(script)
    chunks = chunk_text(clean)
    print(f"  Generating voice in {len(chunks)} chunks...")

    chunk_paths = []
    for i, chunk in enumerate(chunks):
        chunk_path = output_dir / f"chunk_{i:03d}.mp3"
        print(f"  Chunk {i+1}/{len(chunks)}...", end=" ")
        success = generate_audio_chunk(chunk, voice_id, api_key, chunk_path)
        if success:
            chunk_paths.append(chunk_path)
            print("✓")
        else:
            print("✗ skipped")
        time.sleep(0.5)  # Rate limit buffer

    if not chunk_paths:
        return None

    # If only one chunk, just return it
    if len(chunk_paths) == 1:
        final = output_dir / "narration.mp3"
        chunk_paths[0].rename(final)
        return final

    # Stitch chunks with ffmpeg
    final = output_dir / "narration.mp3"
    list_file = output_dir / "chunks.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in chunk_paths))

    import subprocess
    result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(final)
    ], capture_output=True)

    list_file.unlink(missing_ok=True)
    for p in chunk_paths:
        p.unlink(missing_ok=True)

    if result.returncode == 0:
        print(f"  Narration saved: {final}")
        return final
    return None
