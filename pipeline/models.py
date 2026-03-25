"""Data models shared across all pipeline stages."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobConfig(BaseModel):
    """Configuration for a single video generation job."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    youtube_url: str
    output_dir: Path = Path("./output")
    temp_dir: Path = Path("./temp")
    cleanup_temp: bool = True

    # Clip selection
    num_clips: int = 5
    min_duration: int = 30
    max_duration: int = 90

    # Subtitle style
    subtitle_style: str = "capcut"  # "capcut", "karaoke", "minimal"

    # Composition effects
    add_music: bool = False
    add_hook: bool = True
    add_progress_bar: bool = True
    add_zoom_cuts: bool = True
    add_emoji: bool = True

    # Bottom title bar (3 lines)
    title_text: str = ""       # Line 1: sermon title
    scripture_text: str = ""   # Line 2: Bible verse
    speaker_text: str = ""     # Line 3: speaker name
    title_font_size: int = 90  # Font size for title
    sub_font_size: int = 44    # Font size for scripture/speaker
    bar_ratio: int = 40        # Black bar height as % of total (20-60)
    title_y_pct: int = 25      # Title Y position within black bar (0-100%)
    sub_y_pct: int = 65        # Sub info Y position within black bar (0-100%)

    # Transcription
    language: str = "auto"
    whisper_mode: str = "api"  # "api" or "local"

    # AI engine for highlight analysis
    ai_engine: str = "openai"  # "openai" or "gemini"

    # Quote mode: user provides specific sentences to find in the video
    # Each line = one clip. Skips AI selection entirely.
    quotes: list[str] = Field(default_factory=list)

    @property
    def job_temp_dir(self) -> Path:
        return self.temp_dir / self.job_id

    @property
    def job_output_dir(self) -> Path:
        return self.output_dir / self.job_id


class VideoMetadata(BaseModel):
    """Metadata from the downloaded source video."""

    title: str
    duration_seconds: float
    width: int
    height: int
    source_path: Path


class WordSegment(BaseModel):
    """A single word with its start/end timestamps."""

    word: str
    start: float
    end: float


class TranscriptResult(BaseModel):
    """Full transcription output with word-level timestamps."""

    segments: list[WordSegment]
    full_text: str
    language: str


class EmphasisMoment(BaseModel):
    """A moment within a clip that deserves visual emphasis (zoom cut, emoji)."""

    time: float           # Seconds relative to clip start
    duration: float = 1.5
    zoom: float = 1.3
    emoji: str = ""
    reason: str = ""


class SubtitleLine(BaseModel):
    """A refined subtitle line after AI post-processing."""

    text: str
    start: float  # Relative to clip start
    end: float
    is_emphasis: bool = False


class ClipSelection(BaseModel):
    """A selected clip range chosen by AI."""

    index: int
    start_time: float
    end_time: float
    hook_text: str = ""
    reason: str = ""
    transcript_excerpt: str = ""
    word_segments: list[WordSegment] = Field(default_factory=list)
    emphasis_moments: list[EmphasisMoment] = Field(default_factory=list)
    refined_subtitles: list[SubtitleLine] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class ClipArtifact(BaseModel):
    """Tracks file paths for a single clip through the pipeline."""

    index: int
    raw_path: Optional[Path] = None
    cropped_path: Optional[Path] = None
    subtitled_path: Optional[Path] = None
    final_path: Optional[Path] = None
    error: Optional[str] = None


class PipelineStatus(BaseModel):
    """Real-time status of a running pipeline job."""

    job_id: str
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    clips_done: int = 0
    clips_total: int = 0
    error: Optional[str] = None


class PipelineResult(BaseModel):
    """Final output of a completed pipeline run."""

    job_id: str
    source_metadata: VideoMetadata
    transcript: TranscriptResult
    selections: list[ClipSelection]
    clips: list[ClipArtifact]
    elapsed_seconds: float
