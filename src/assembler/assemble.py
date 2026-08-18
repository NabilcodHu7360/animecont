"""
assemble.py — narration + timed images -> finished MP4.

WHY NOT video_assembler.py
That module is reusable in parts (ffprobe duration, music ducking) but assumed
someone else had already decided WHEN each image appears, and its create_podcast
shells out to `cp` — Unix-only, broken on Windows. The hard part of assembly is
the timeline, and that's what lives here.

THE TIMELINE PROBLEM
image_gen.py records each [VISUAL:] cue's offset in the narration (9%, 16%,
23%...). Naively cutting exactly on those offsets breaks in two ways we hit on
the real scripts:
  1. COLLISIONS — two cues can land at the same offset (9% and 9%), flashing an
     image for a fraction of a second.
  2. LONG TAIL — the last cue is at 79%, so the final image would hold for ~75s
     of narration while the story keeps moving.
So build_timeline() enforces a minimum shot length and stretches the tail,
rather than us hand-tuning cue placement in all 11 scripts.

MOTION
A still image held 30s reads as a broken video. Each shot gets a slow Ken Burns
push (ffmpeg zoompan) so the frame is always alive.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FPS = 25
W, H = 1280, 720
MIN_SHOT_SECONDS = 6.0     # no image flashes shorter than this
MAX_SHOT_SECONDS = 30.0    # beyond this, a still feels dead even with motion


@dataclass
class Shot:
    file: Path
    start: float
    duration: float
    prompt: str


def get_audio_duration(audio_path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(audio_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("ffprobe failed — is ffmpeg installed and on PATH?")
    return float(json.loads(r.stdout)["format"]["duration"])


def build_timeline(scenes: list[dict], images_dir: Path,
                   audio_seconds: float) -> list[Shot]:
    """Offsets -> real start/duration pairs, with collisions and the tail fixed.

    Strategy: each shot starts at its cue's offset, and runs until the NEXT
    cue's start (last one runs to the end of the audio). Then we walk forward
    enforcing MIN_SHOT_SECONDS — pushing later starts back if needed — and
    finally split any shot longer than MAX_SHOT_SECONDS is left alone (the Ken
    Burns move carries it) but warned about.
    """
    starts = [s["offset"] * audio_seconds for s in scenes]

    # The first cue rarely sits at 0% (an opener can land at 9% = 32s),
    # which would open the video on 32 seconds of black. The first image always
    # covers the cold open.
    starts[0] = 0.0

    # Enforce a minimum gap by pushing each start at least MIN after the last.
    for i in range(1, len(starts)):
        if starts[i] - starts[i - 1] < MIN_SHOT_SECONDS:
            starts[i] = starts[i - 1] + MIN_SHOT_SECONDS

    # If pushing overflowed the audio, compress everything back proportionally.
    if starts[-1] >= audio_seconds - MIN_SHOT_SECONDS:
        span = audio_seconds - MIN_SHOT_SECONDS
        starts = [span * i / max(len(starts) - 1, 1) for i in range(len(starts))]

    shots: list[Shot] = []
    for i, s in enumerate(scenes):
        end = starts[i + 1] if i + 1 < len(starts) else audio_seconds
        dur = max(end - starts[i], MIN_SHOT_SECONDS)
        f = images_dir / s["file"]
        if not f.exists():
            raise FileNotFoundError(f"missing image: {f}")
        shots.append(Shot(file=f, start=starts[i], duration=dur,
                          prompt=s.get("prompt", "")))
    return shots


def _ken_burns(index: int, frames: int) -> str:
    """Pick a camera move for this shot.

    A binary zoom-in/zoom-out alternation is a pattern the eye catches within
    three shots. Six moves — zooms, lateral pans, diagonal drifts — mixed by a
    seeded shuffle so it looks hand-cut but rebuilds identically every run.

    zoompan notes: `on` is the current output frame, `d` the shot's frame count,
    so on/d is 0->1 progress. Expressions must avoid division by zero at on=0.
    """
    import random

    z_in = "min(zoom+0.0009,1.18)"
    z_out = "if(lte(zoom,1.0),1.18,max(1.001,zoom-0.0009))"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    # pan expressions: travel the un-zoomed slack across the shot
    px_lr = f"(iw-iw/zoom)*on/{frames}"
    px_rl = f"(iw-iw/zoom)*(1-on/{frames})"
    py_tb = f"(ih-ih/zoom)*on/{frames}"
    py_bt = f"(ih-ih/zoom)*(1-on/{frames})"

    moves = [
        (z_in,  cx,    cy),      # push in, centred
        (z_out, cx,    cy),      # pull out, centred
        ("1.12", px_lr, cy),     # pan left -> right
        ("1.12", px_rl, cy),     # pan right -> left
        (z_in,  px_lr, py_tb),   # push in, drifting down-right
        (z_out, px_rl, py_bt),   # pull out, drifting up-left
    ]
    rng = random.Random(index * 7919)      # deterministic per shot
    z, x, y = moves[rng.randrange(len(moves))]
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}"


def _render_shot(shot: Shot, out_path: Path, index: int) -> Path:
    """One still -> one clip with a Ken Burns move."""
    frames = max(int(shot.duration * FPS), 1)
    vf = (
        # upscale first so zoompan doesn't jitter on the source pixels
        f"scale={W*2}:{H*2},"
        f"{_ken_burns(index, frames)},"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(shot.file),
        "-vf", vf, "-t", f"{shot.duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-r", str(FPS), str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"ffmpeg failed on shot {index}:\n"
            f"{r.stderr.decode('utf-8', 'ignore')[-600:]}"
        )
    return out_path


def _subtitles_filter(srt: Path) -> str:
    """ffmpeg's subtitles filter parses its argument, so Windows paths break it:
    the drive colon reads as an option separator and backslashes as escapes.
    Feed it a relative posix-style path and escape any remaining colon."""
    try:
        rel = srt.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        rel = srt.as_posix().replace(":", r"\:")
    style = (
        "FontName=DejaVu Sans,FontSize=17,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H99000000,BorderStyle=3,Outline=1,Shadow=0,"
        "MarginV=38,Alignment=2"
    )
    return f"subtitles={rel}:force_style='{style}'"


def assemble(series: str,
             audio_path: Path | None = None,
             images_dir: Path | None = None,
             music_path: Path | None = None,
             out_path: Path | None = None,
             srt_path: Path | None = None) -> Path:
    audio_path = Path(audio_path or f"data/audio/{series}.wav")
    images_dir = Path(images_dir or f"data/images/{series}")
    out_path = Path(out_path or f"outputs/{series}.mp4")
    manifest = images_dir / "scenes.json"
    srt = Path(srt_path) if srt_path else Path(f"data/subs/{series}.srt")

    for p in (audio_path, manifest):
        if not p.exists():
            raise FileNotFoundError(f"missing: {p}")

    from ..obs.run_log import stage
    scenes = json.loads(manifest.read_text(encoding="utf-8"))
    audio_seconds = get_audio_duration(audio_path)
    shots = build_timeline(scenes, images_dir, audio_seconds)
    _obs = stage("assemble", series=series, provider="ffmpeg")
    st = _obs.__enter__()
    st.count(shots=len(shots))
    st.note(video_seconds=round(audio_seconds, 1), captions=srt.exists())

    print(f"{series}: {audio_seconds/60:.1f} min audio, {len(shots)} shots")
    for i, s in enumerate(shots):
        flag = "  <- long" if s.duration > MAX_SHOT_SECONDS else ""
        print(f"  {i:2d}  {s.start:6.1f}s  +{s.duration:5.1f}s  "
              f"{s.prompt[:44]}{flag}")

    tmp = out_path.parent / f".{series}_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. still -> moving clip, one per shot
    clips = []
    for i, s in enumerate(shots):
        c = tmp / f"clip_{i:03d}.mp4"
        print(f"  rendering shot {i+1}/{len(shots)}...")
        _render_shot(s, c, i)
        clips.append(c)

    # 2. concat the clips (stream copy — fast, no requality loss)
    listing = tmp / "concat.txt"
    listing.write_text(
        "".join(f"file '{c.resolve().as_posix()}'\n" for c in clips),
        encoding="utf-8",
    )
    silent = tmp / "video_silent.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(silent)],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-600:])

    # 3. mux audio (+ optional ducked music bed), burning in captions if present.
    #    Burn-in forces a video re-encode: the `-c:v copy` fast path can't apply
    #    a filter. Costs ~1 min for a 5 min video; worth it for baked captions
    #    that need no sidecar file on any player.
    burn = srt.exists()
    vcodec = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-vf", _subtitles_filter(srt)] if burn else ["-c:v", "copy"])
    if burn:
        print(f"  burning captions from {srt}")
    else:
        print(f"  no captions at {srt} — skipping burn-in")

    if music_path and Path(music_path).exists():
        cmd = [
            "ffmpeg", "-y", "-i", str(silent), "-i", str(audio_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex",
            f"[2:a]volume=0.15,atrim=duration={audio_seconds}[m];"
            f"[1:a][m]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]",
            *vcodec, "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(silent), "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            *vcodec, "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_path),
        ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-600:])

    for f in tmp.iterdir():
        f.unlink(missing_ok=True)
    tmp.rmdir()

    mb = out_path.stat().st_size / 1e6
    st.note(mb=round(mb, 1))
    _obs.__exit__(None, None, None)
    print(f"\nwrote {out_path}  ({mb:.1f} MB, {audio_seconds/60:.1f} min)")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.assembler.assemble jojo")
        print("       python -m src.assembler.assemble jojo --music path.mp3")
        print("       python -m src.assembler.assemble jojo --dry-run")
        sys.exit(2)
    series = sys.argv[1]
    music = None
    if "--music" in sys.argv:
        music = Path(sys.argv[sys.argv.index("--music") + 1])
    if "--dry-run" in sys.argv:
        # Show the timeline without rendering — cheap way to sanity-check pacing.
        a = Path(f"data/audio/{series}.wav")
        d = Path(f"data/images/{series}")
        secs = get_audio_duration(a)
        sc = json.loads((d / "scenes.json").read_text(encoding="utf-8"))
        for i, s in enumerate(build_timeline(sc, d, secs)):
            print(f"{i:2d}  {s.start:6.1f}s  +{s.duration:5.1f}s  {s.prompt[:50]}")
        sys.exit(0)
    assemble(series, music_path=music)
