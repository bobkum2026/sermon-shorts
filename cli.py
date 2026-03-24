#!/usr/bin/env python3
"""CLI entry point for Sermon Short-form Generator."""

from __future__ import annotations

import argparse
import logging
import sys

from pipeline.models import JobConfig
from pipeline.orchestrator import run


def main():
    parser = argparse.ArgumentParser(
        description="Sermon Shorts Generator - YouTube to Short-form Videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py "https://youtube.com/watch?v=abc123"
  python cli.py "https://youtu.be/abc123" -n 3 -s karaoke
  python cli.py "https://youtube.com/watch?v=abc123" --ai openai --no-hook
  python cli.py "https://youtube.com/watch?v=abc123" --no-zoom --no-emoji --language ko
        """,
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("-n", "--num-clips", type=int, default=5, help="Number of clips (default: 5)")
    parser.add_argument("--min-duration", type=int, default=30, help="Min clip duration in seconds (default: 30)")
    parser.add_argument("--max-duration", type=int, default=90, help="Max clip duration in seconds (default: 90)")
    parser.add_argument(
        "-s", "--subtitle-style",
        choices=["capcut", "karaoke", "minimal"],
        default="capcut",
        help="Subtitle style (default: capcut)",
    )
    parser.add_argument(
        "--ai", choices=["gemini", "openai"], default="gemini",
        help="AI engine for highlight analysis (default: gemini)",
    )
    parser.add_argument("--no-music", action="store_true", help="Disable background music")
    parser.add_argument("--no-hook", action="store_true", help="Disable hook text overlay")
    parser.add_argument("--no-zoom", action="store_true", help="Disable zoom cuts on emphasis moments")
    parser.add_argument("--no-emoji", action="store_true", help="Disable emoji overlays")
    parser.add_argument("--no-progress-bar", action="store_true", help="Disable bottom progress bar")
    parser.add_argument("-t", "--title", default="", help="Title text for bottom bar")
    parser.add_argument("--scripture", default="", help="Bible verse for bottom bar")
    parser.add_argument("--speaker", default="", help="Speaker name for bottom bar")
    parser.add_argument("--language", default="auto", help="Transcript language (default: auto)")
    parser.add_argument("-o", "--output-dir", default="./output", help="Output directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = JobConfig(
        youtube_url=args.url,
        num_clips=args.num_clips,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        subtitle_style=args.subtitle_style,
        ai_engine=args.ai,
        add_music=not args.no_music,
        add_hook=not args.no_hook,
        add_zoom_cuts=not args.no_zoom,
        add_emoji=not args.no_emoji,
        add_progress_bar=not args.no_progress_bar,
        title_text=args.title,
        scripture_text=args.scripture,
        speaker_text=args.speaker,
        language=args.language,
        output_dir=args.output_dir,
    )

    def on_progress(stage: str, pct: float, message: str):
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "=" * filled + ">" + " " * max(0, bar_len - filled - 1)
        print(f"\r  [{bar}] {pct:5.1f}% | {message}", end="", flush=True)
        if stage == "done":
            print()

    print()
    print(f"  Sermon Shorts Generator")
    print(f"  URL: {config.youtube_url}")
    print(f"  Clips: {config.num_clips} ({config.min_duration}-{config.max_duration}s)")
    print(f"  Style: {config.subtitle_style} | AI: {config.ai_engine}")
    print(f"  Effects: hook={config.add_hook} zoom={config.add_zoom_cuts} emoji={config.add_emoji} bar={config.add_progress_bar}")
    if config.title_text:
        print(f"  Title: {config.title_text}")
    print()

    try:
        result = run(config, on_progress=on_progress)
    except Exception as e:
        print(f"\n  Error: {e}")
        sys.exit(1)

    print()
    successful = [c for c in result.clips if c.error is None]
    failed = [c for c in result.clips if c.error is not None]

    print(f"  Done! ({result.elapsed_seconds:.0f}s)")
    print(f"  Source: {result.source_metadata.title}")
    print(f"  Output: {config.job_output_dir}/")
    print()

    for clip in successful:
        print(f"    {clip.final_path}")
    for clip in failed:
        print(f"    [FAIL] Clip {clip.index}: {clip.error}")

    print()
    print(f"  {len(successful)} short-form videos generated!")
    print()


if __name__ == "__main__":
    main()
