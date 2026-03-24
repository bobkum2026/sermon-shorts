"""Stage 1: YouTube video download via yt-dlp."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pipeline.models import JobConfig, VideoMetadata
from services.ffmpeg_wrapper import get_video_info

logger = logging.getLogger(__name__)

YOUTUBE_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]+"
)


def validate_url(url: str) -> bool:
    """Check if the URL looks like a valid YouTube URL."""
    return bool(YOUTUBE_URL_PATTERN.match(url))


def download(config: JobConfig) -> VideoMetadata:
    """Download a YouTube video and return metadata."""
    import yt_dlp

    if not validate_url(config.youtube_url):
        raise ValueError(f"Invalid YouTube URL: {config.youtube_url}")

    config.job_temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = config.job_temp_dir / "source.mp4"

    ydl_opts = {
        "format": f"bestvideo[height<={1080}][ext=mp4]+bestaudio[ext=m4a]/best[height<={1080}][ext=mp4]/best",
        "outtmpl": str(output_path),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
    }

    logger.info("Downloading: %s", config.youtube_url)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(config.youtube_url, download=True)

    title = info.get("title", "untitled")

    # yt-dlp may append codec info to filename, find the actual file
    if not output_path.exists():
        candidates = list(config.job_temp_dir.glob("source*"))
        if candidates:
            output_path = candidates[0]
        else:
            raise FileNotFoundError("Download completed but output file not found")

    video_info = get_video_info(output_path)

    metadata = VideoMetadata(
        title=title,
        duration_seconds=video_info["duration"],
        width=video_info["width"],
        height=video_info["height"],
        source_path=output_path,
    )

    logger.info(
        "Downloaded: '%s' (%ds, %dx%d)",
        title,
        int(metadata.duration_seconds),
        metadata.width,
        metadata.height,
    )
    return metadata
