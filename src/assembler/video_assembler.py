"""
video_assembler.py
Assembles narration audio + background images into a final MP4 video.
Uses FFmpeg for all media operations.
"""
import subprocess
import json
import os
from pathlib import Path


def get_audio_duration(audio_path: Path) -> float:
    """Returns audio duration in seconds using ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(audio_path)
    ], capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def create_podcast(narration: Path, music_path: Path | None, output: Path) -> Path:
    """
    Mixes narration + background music into a podcast MP3.
    Music is ducked to 15% volume under the narration.
    """
    if not music_path or not music_path.exists():
        # No music — just copy narration
        subprocess.run(["cp", str(narration), str(output)])
        return output

    duration = get_audio_duration(narration)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(narration),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume=0.15,atrim=duration={duration}[music];[0:a][music]amix=inputs=2:duration=first",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(output)
    ], capture_output=True)

    return output


def create_video(
    narration: Path,
    images: list[Path],
    music_path: Path | None,
    output: Path,
    anime_name: str = "Anime Continuation"
) -> Path:
    """
    Assembles the full video:
    - Background images cycle with slow Ken Burns zoom effect
    - Narration audio plays over
    - Background music mixed in at low volume
    - Chapter title card at the start
    """
    if not narration.exists():
        raise FileNotFoundError(f"Narration not found: {narration}")

    duration = get_audio_duration(narration)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not images:
        # No images — create a simple black video with audio
        print("  No images found — creating audio-only video with black bg")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=1280x720:d={duration}",
            "-i", str(narration),
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(output)
        ], capture_output=True)
        return output

    # Build image slideshow: each image gets equal time
    time_per_image = duration / len(images)

    # Create concat filter for images with Ken Burns zoom effect
    filter_parts = []
    for i, img in enumerate(images):
        # Slow zoom: scale up 10% over the duration of the image
        filter_parts.append(
            f"[{i}:v]scale=1920:1080,zoompan=z='min(zoom+0.0005,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(time_per_image*25)}:fps=25,scale=1280:720[v{i}]"
        )

    # Concatenate all image clips
    video_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    filter_parts.append(f"{video_inputs}concat=n={len(images)}:v=1:a=0[video_out]")

    filter_complex = ";".join(filter_parts)

    # Build ffmpeg command
    cmd = ["ffmpeg", "-y"]
    for img in images:
        cmd += ["-loop", "1", "-t", str(time_per_image), "-i", str(img)]
    cmd += ["-i", str(narration)]

    audio_idx = len(images)

    if music_path and music_path.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
        music_idx = len(images) + 1
        filter_complex += f";[{music_idx}:a]volume=0.12,atrim=duration={duration}[music];[{audio_idx}:a][music]amix=inputs=2:duration=first[audio_out]"
        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", "[video_out]", "-map", "[audio_out]"]
    else:
        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", "[video_out]", f"-map", f"{audio_idx}:a"]

    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output)
    ]

    print(f"  Running FFmpeg assembly ({len(images)} images, {duration:.0f}s)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FFmpeg error: {result.stderr[-500:]}")
        return None

    print(f"  Video saved: {output} ({output.stat().st_size // 1024 // 1024}MB)")
    return output
