"""Stage 4: Smart vertical crop with face tracking."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.models import ClipSelection, JobConfig, VideoMetadata
from services.face_detector import detect_face_positions
from services.ffmpeg_wrapper import cut_segment, get_video_info, run_ffmpeg

logger = logging.getLogger(__name__)


def crop_clip(
    selection: ClipSelection,
    metadata: VideoMetadata,
    config: JobConfig,
) -> Path:
    """Extract a clip segment and crop to 9:16 with face tracking."""
    temp_dir = config.job_temp_dir
    raw_path = temp_dir / f"clip_{selection.index}_raw.mp4"
    cropped_path = temp_dir / f"clip_{selection.index}_cropped.mp4"

    # Step 1: Extract the raw segment
    logger.info(
        "Clip %d: extracting %.1f-%.1f",
        selection.index, selection.start_time, selection.end_time,
    )
    cut_segment(
        metadata.source_path,
        raw_path,
        selection.start_time,
        selection.end_time,
        copy_codec=True,
    )

    # Get actual segment dimensions
    info = get_video_info(raw_path)
    src_w = info["width"]
    src_h = info["height"]

    # Calculate 9:16 crop dimensions from source
    target_ratio = 9 / 16
    src_ratio = src_w / src_h if src_h > 0 else 1

    if src_ratio > target_ratio:
        # Source is wider -> crop width
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        # Source is taller or equal -> crop height
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    # Step 2: Detect face positions for smart panning
    face_positions = detect_face_positions(raw_path, sample_interval=0.5, smoothing_factor=0.3)

    if face_positions:
        # Use dynamic panning based on face positions
        logger.info("Clip %d: face detected, using smart pan", selection.index)
        _crop_with_dynamic_pan(
            raw_path, cropped_path,
            src_w, src_h, crop_w, crop_h,
            face_positions,
        )
    else:
        # Center crop
        logger.info("Clip %d: no face detected, using center crop", selection.index)
        x_offset = (src_w - crop_w) // 2
        run_ffmpeg([
            "-i", str(raw_path),
            "-vf", f"crop={crop_w}:{crop_h}:{x_offset}:0,scale=1080:1920",
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(cropped_path),
        ])

    return cropped_path


def _crop_with_dynamic_pan(
    input_path: Path,
    output_path: Path,
    src_w: int,
    src_h: int,
    crop_w: int,
    crop_h: int,
    face_positions: list[float],
) -> None:
    """Crop with dynamic horizontal panning following face positions.

    Uses ffmpeg's sendcmd or expression-based crop for smooth panning.
    For simplicity and reliability, we use the median face position
    (most clips have the speaker roughly stationary).
    For clips with significant movement, we use keyframe-based panning.
    """
    import statistics

    max_x = src_w - crop_w
    if max_x <= 0:
        max_x = 0

    # Check if face position varies significantly
    if len(face_positions) > 1:
        pos_std = statistics.stdev(face_positions)
    else:
        pos_std = 0

    if pos_std < 0.05:
        # Static: use median position for single fixed crop
        median_x = statistics.median(face_positions)
        x_offset = int(median_x * src_w - crop_w / 2)
        x_offset = max(0, min(x_offset, max_x))

        run_ffmpeg([
            "-i", str(input_path),
            "-vf", f"crop={crop_w}:{crop_h}:{x_offset}:0,scale=1080:1920",
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ])
    else:
        # Dynamic: use ffmpeg expression for smooth panning
        # Sample a few keyframe positions and interpolate with ffmpeg expressions
        # We use the average of nearby positions for stability
        fps = 30
        total_frames = len(face_positions)

        # Build an expression that interpolates x position over time
        # Using between() with linear interpolation segments
        segments = []
        step = max(1, total_frames // 20)  # ~20 keyframes max
        keyframes = list(range(0, total_frames, step)) + [total_frames - 1]

        for i, kf_idx in enumerate(keyframes):
            x_pos = face_positions[min(kf_idx, len(face_positions) - 1)]
            x_offset = x_pos * src_w - crop_w / 2
            x_offset = max(0, min(x_offset, max_x))
            t = kf_idx / fps if fps > 0 else 0
            segments.append((t, int(x_offset)))

        # Build a piecewise linear expression
        expr_parts = []
        for i in range(len(segments) - 1):
            t0, x0 = segments[i]
            t1, x1 = segments[i + 1]
            # Linear interpolation: x0 + (x1-x0) * (t-t0) / (t1-t0)
            if t1 > t0:
                slope = (x1 - x0) / (t1 - t0)
                interp = f"{x0}+{slope:.2f}*(t-{t0:.3f})"
            else:
                interp = str(x0)
            expr_parts.append(f"between(t,{t0:.3f},{t1:.3f})*({interp})")

        x_expr = "+".join(expr_parts)
        # Clamp
        x_expr = f"clip({x_expr},0,{max_x})"

        vf = f"crop={crop_w}:{crop_h}:'{x_expr}':0,scale=1080:1920"

        run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ])
