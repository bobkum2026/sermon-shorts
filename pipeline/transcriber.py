"""Stage 2: Audio transcription with word-level timestamps."""

from __future__ import annotations

import logging
import math
from pathlib import Path

from pipeline.models import JobConfig, TranscriptResult, VideoMetadata, WordSegment
from services.ffmpeg_wrapper import extract_audio, run_ffmpeg
from services.openai_client import transcribe_audio

logger = logging.getLogger(__name__)

# Whisper API max file size is 25MB. MP3 at 64kbps mono ~= 0.47MB/min, so ~50 min safe
MAX_CHUNK_DURATION = 600  # 10 minutes per chunk (very safe under 25MB as mp3)
OVERLAP_SECONDS = 5


def transcribe(metadata: VideoMetadata, config: JobConfig) -> TranscriptResult:
    """Transcribe video audio and return word-level timestamps."""
    # Use mp3 instead of wav to stay under Whisper's 25MB limit
    audio_path = config.job_temp_dir / "audio.mp3"
    _extract_audio_mp3(metadata.source_path, audio_path)

    duration = metadata.duration_seconds
    language = config.language

    if duration <= MAX_CHUNK_DURATION:
        result = _transcribe_single(audio_path, language)
    else:
        result = _transcribe_chunked(audio_path, duration, language, config.job_temp_dir)

    logger.info(
        "Transcribed: %d words, language=%s",
        len(result.segments),
        result.language,
    )
    return result


def _extract_audio_mp3(video_path: Path, audio_path: Path) -> Path:
    """Extract audio as compressed mp3 to stay under Whisper 25MB limit."""
    run_ffmpeg([
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "64k",
        str(audio_path),
    ])
    return audio_path


def _transcribe_single(audio_path: Path, language: str) -> TranscriptResult:
    """Transcribe a single audio file."""
    raw = transcribe_audio(audio_path, language=language)
    return _parse_whisper_response(raw)


def _transcribe_chunked(
    audio_path: Path,
    duration: float,
    language: str,
    temp_dir: Path,
) -> TranscriptResult:
    """Split long audio into chunks and transcribe each."""
    num_chunks = math.ceil(duration / MAX_CHUNK_DURATION)
    all_segments: list[WordSegment] = []
    detected_language = "unknown"

    for i in range(num_chunks):
        start = i * MAX_CHUNK_DURATION
        end = min(start + MAX_CHUNK_DURATION + OVERLAP_SECONDS, duration)
        chunk_path = temp_dir / f"audio_chunk_{i}.mp3"

        run_ffmpeg([
            "-i", str(audio_path),
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            str(chunk_path),
        ])

        raw = transcribe_audio(chunk_path, language=language)
        result = _parse_whisper_response(raw)

        if i == 0:
            detected_language = result.language

        # Offset timestamps by chunk start time
        for seg in result.segments:
            adjusted = WordSegment(
                word=seg.word,
                start=seg.start + start,
                end=seg.end + start,
            )
            # Skip overlap duplicates
            if all_segments and adjusted.start < all_segments[-1].end:
                continue
            all_segments.append(adjusted)

    full_text = " ".join(s.word for s in all_segments)
    return TranscriptResult(
        segments=all_segments,
        full_text=full_text,
        language=detected_language,
    )


def _parse_whisper_response(raw: dict) -> TranscriptResult:
    """Parse Whisper API verbose_json response into our model."""
    words = raw.get("words", [])
    language = raw.get("language", "unknown")

    segments = []
    for w in words:
        segments.append(WordSegment(
            word=w.get("word", "").strip(),
            start=float(w.get("start", 0)),
            end=float(w.get("end", 0)),
        ))

    # Filter empty words
    segments = [s for s in segments if s.word]

    full_text = raw.get("text", " ".join(s.word for s in segments))

    return TranscriptResult(
        segments=segments,
        full_text=full_text.strip(),
        language=language,
    )
