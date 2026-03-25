"""Master pipeline orchestrator that chains all stages."""

from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from pipeline.models import (
    ClipArtifact,
    ClipSelection,
    JobConfig,
    PipelineResult,
    PipelineStatus,
    VideoMetadata,
)

logger = logging.getLogger(__name__)

# Global status tracker for web UI
_status: dict[str, PipelineStatus] = {}


def get_status(job_id: str) -> PipelineStatus | None:
    return _status.get(job_id)


def _update(job_id: str, **kwargs) -> None:
    if job_id not in _status:
        _status[job_id] = PipelineStatus(job_id=job_id)
    for k, v in kwargs.items():
        setattr(_status[job_id], k, v)


def run(
    config: JobConfig,
    on_progress: Callable[[str, float, str], None] | None = None,
) -> PipelineResult:
    """Execute the full pipeline: download → transcribe → select → crop → subtitle → compose.

    Args:
        config: Job configuration
        on_progress: Optional callback(stage, progress_pct, message)
    """
    from pipeline import downloader, transcriber, selector, cropper, subtitler, composer

    start_time = time.time()
    _update(config.job_id, stage="starting", progress=0, message="Initializing...")

    # Ensure directories exist
    config.job_temp_dir.mkdir(parents=True, exist_ok=True)
    config.job_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # === Stage 1: Download ===
        _update(config.job_id, stage="downloading", progress=5, message="Downloading video...")
        if on_progress:
            on_progress("downloading", 5, "Downloading video...")
        metadata = downloader.download(config)

        # === Stage 2: Transcribe ===
        _update(config.job_id, stage="transcribing", progress=20, message="Transcribing audio...")
        if on_progress:
            on_progress("transcribing", 20, "Transcribing audio...")
        transcript = transcriber.transcribe(metadata, config)

        # === Stage 3: Select clips ===
        if config.quotes:
            # Quote mode: find user-provided sentences in transcript
            from pipeline import quote_matcher
            _update(config.job_id, stage="selecting", progress=35, message="Matching quotes...")
            if on_progress:
                on_progress("selecting", 35, "Matching quotes...")
            selections = quote_matcher.match_quotes(transcript, config)
        else:
            # AI mode: auto-select best moments
            _update(config.job_id, stage="selecting", progress=35, message="AI selecting best moments...")
            if on_progress:
                on_progress("selecting", 35, "AI selecting best moments...")
            selections = selector.select_clips(transcript, config, video_duration=metadata.duration_seconds)

        # === Stage 4-6: Process each clip in parallel ===
        _update(
            config.job_id,
            stage="processing",
            progress=45,
            message="Processing clips...",
            clips_total=len(selections),
            clips_done=0,
        )

        clips: list[ClipArtifact] = []
        completed = 0

        def process_single_clip(sel: ClipSelection) -> ClipArtifact:
            """Process a single clip through crop → subtitle → compose."""
            nonlocal completed
            try:
                # Stage 4: Crop
                cropped = cropper.crop_clip(sel, metadata, config)

                # Stage 5: Subtitles (with AI-refined lines if available)
                subtitled = subtitler.add_subtitles(
                    cropped, sel.word_segments, config,
                    refined_subtitles=sel.refined_subtitles or None,
                )

                # Stage 6: Compose
                final = composer.compose(subtitled, sel, config)

                completed += 1
                pct = 45 + (completed / len(selections)) * 50
                _update(
                    config.job_id,
                    progress=pct,
                    clips_done=completed,
                    message=f"Clip {completed}/{len(selections)} done",
                )
                if on_progress:
                    on_progress("processing", pct, f"Clip {completed}/{len(selections)} done")

                return ClipArtifact(
                    index=sel.index,
                    cropped_path=cropped,
                    subtitled_path=subtitled,
                    final_path=final,
                )

            except Exception as e:
                logger.error("Clip %d failed: %s", sel.index, e)
                completed += 1
                return ClipArtifact(index=sel.index, error=str(e))

        # Process clips in parallel (max 3 concurrent)
        max_workers = min(3, len(selections))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(process_single_clip, sel): sel for sel in selections}
            for future in as_completed(futures):
                clips.append(future.result())

        # Sort clips by index
        clips.sort(key=lambda c: c.index)

        # === Done ===
        elapsed = time.time() - start_time
        successful = [c for c in clips if c.error is None]

        _update(
            config.job_id,
            stage="done",
            progress=100,
            message=f"Done! {len(successful)}/{len(clips)} clips generated in {elapsed:.0f}s",
        )

        if on_progress:
            on_progress("done", 100, f"Done! {len(successful)} clips in {elapsed:.0f}s")

        logger.info(
            "Pipeline complete: %d/%d clips in %.1fs → %s",
            len(successful), len(clips), elapsed, config.job_output_dir,
        )

        result = PipelineResult(
            job_id=config.job_id,
            source_metadata=metadata,
            transcript=transcript,
            selections=selections,
            clips=clips,
            elapsed_seconds=elapsed,
        )

        # Cleanup temp
        if config.cleanup_temp:
            try:
                shutil.rmtree(config.job_temp_dir)
                logger.debug("Cleaned up temp: %s", config.job_temp_dir)
            except Exception as e:
                logger.warning("Failed to clean temp: %s", e)

        return result

    except Exception as e:
        _update(config.job_id, stage="error", error=str(e), message=f"Error: {e}")
        logger.error("Pipeline failed: %s", e, exc_info=True)
        raise
