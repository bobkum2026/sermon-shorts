"""FFmpeg command builder and executor."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run an ffmpeg command with error handling."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    logger.debug("ffmpeg command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.error("ffmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"ffmpeg failed (code {result.returncode}): {result.stderr[:500]}")
    return result


def run_ffprobe(args: list[str], timeout: int = 30) -> str:
    """Run ffprobe and return stdout."""
    cmd = ["ffprobe", "-hide_banner"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:500]}")
    return result.stdout.strip()


def get_video_info(path: Path) -> dict:
    """Get video duration, width, height via ffprobe."""
    import json

    raw = run_ffprobe([
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ])
    data = json.loads(raw)

    video_stream = next(
        (s for s in data.get("streams", []) if s["codec_type"] == "video"),
        None,
    )
    duration = float(data.get("format", {}).get("duration", 0))
    width = int(video_stream["width"]) if video_stream else 0
    height = int(video_stream["height"]) if video_stream else 0

    return {"duration": duration, "width": width, "height": height}


def extract_audio(video_path: Path, audio_path: Path, sample_rate: int = 16000) -> Path:
    """Extract audio from video as WAV."""
    run_ffmpeg([
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(audio_path),
    ])
    return audio_path


def cut_segment(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    copy_codec: bool = True,
) -> Path:
    """Cut a segment from a video file."""
    if copy_codec:
        args = [
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-i", str(input_path),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]
    else:
        # Re-encode for frame-accurate cutting (subtitle sync)
        args = [
            "-i", str(input_path),
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
    run_ffmpeg(args)
    return output_path


def crop_and_scale(
    input_path: Path,
    output_path: Path,
    crop_x: str,
    crop_w: str,
    crop_h: str,
    scale_w: int = 1080,
    scale_h: int = 1920,
    fps: int = 30,
) -> Path:
    """Crop and scale a video to target dimensions."""
    vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={scale_w}:{scale_h}"
    run_ffmpeg([
        "-i", str(input_path),
        "-vf", vf,
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ])
    return output_path


def burn_subtitles(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
) -> Path:
    """Burn ASS subtitles into video."""
    # Escape path for ffmpeg filter (colons and backslashes)
    escaped_ass = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
    run_ffmpeg([
        "-i", str(input_path),
        "-vf", f"ass='{escaped_ass}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        str(output_path),
    ])
    return output_path


def add_hook_and_compose(
    input_path: Path,
    output_path: Path,
    hook_text: str = "",
    hook_duration: float = 2.5,
    hook_font_size: int = 72,
    music_path: Path | None = None,
    music_volume_db: int = -18,
    fade_in: float = 0.5,
    fade_out: float = 1.0,
    duration: float = 0.0,
) -> Path:
    """Final composition: hook overlay + music mix + fades."""
    filters_v = []
    filters_a = []
    inputs = ["-i", str(input_path)]
    audio_map = "[0:a]"

    # Fade in/out
    if duration > 0:
        filters_v.append(
            f"fade=t=in:st=0:d={fade_in},"
            f"fade=t=out:st={duration - fade_out:.2f}:d={fade_out}"
        )
        filters_a.append(
            f"[0:a]afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={duration - fade_out:.2f}:d={fade_out}[aout]"
        )
        audio_map = "[aout]"

    # Hook text overlay
    if hook_text:
        # Escape single quotes for ffmpeg drawtext
        safe_text = hook_text.replace("'", "'\\''").replace(":", "\\:")
        filters_v.append(
            f"drawtext=text='{safe_text}'"
            f":fontsize={hook_font_size}"
            f":fontcolor=white:borderw=4:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":enable='between(t,0,{hook_duration})'"
            f":alpha='if(lt(t,0.3),t/0.3,if(gt(t,{hook_duration - 0.5}),({hook_duration}-t)/0.5,1))'"
        )

    # Background music
    if music_path and music_path.exists():
        inputs += ["-i", str(music_path)]
        filters_a = [
            f"[0:a]afade=t=in:st=0:d={fade_in},afade=t=out:st={duration - fade_out:.2f}:d={fade_out}[speech];"
            f"[1:a]volume={music_volume_db}dB,afade=t=in:st=0:d=1,afade=t=out:st={duration - 1.5:.2f}:d=1.5[music];"
            f"[speech][music]amix=inputs=2:duration=first[aout]"
        ]
        audio_map = "[aout]"

    # Build filter_complex
    vf_chain = ",".join(filters_v) if filters_v else None
    af_chain = ";".join(filters_a) if filters_a else None

    args = inputs[:]

    if vf_chain and af_chain:
        # Combine into filter_complex
        full_filter = f"[0:v]{vf_chain}[vout];{af_chain}"
        args += ["-filter_complex", full_filter, "-map", "[vout]", "-map", audio_map]
    elif vf_chain:
        args += ["-vf", vf_chain, "-c:a", "copy"]
    elif af_chain:
        args += ["-filter_complex", af_chain, "-map", "0:v", "-map", audio_map, "-c:v", "copy"]
    else:
        args += ["-c", "copy"]

    args += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(output_path),
    ]

    run_ffmpeg(args, timeout=300)
    return output_path
