"""Stage 5: Commercial-grade animated subtitles via ASS format.

Supports three styles:
- capcut: Word-by-word highlight with pop-in, semi-transparent background box
- karaoke: Fill-sweep highlighting
- minimal: Clean white text

All styles feature:
- 1~2 line display for readability
- Semi-transparent rounded background box
- Emphasis lines get larger/bolder treatment
- Korean-optimized character limits
"""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.models import JobConfig, SubtitleLine, WordSegment
from services.ffmpeg_wrapper import burn_subtitles

logger = logging.getLogger(__name__)

# ASS colors: &HAABBGGRR (AA=alpha, 00=opaque, FF=transparent)
STYLES = {
    "capcut": {
        "highlight_color": "&H0000D7FF&",   # Gold
        "text_color": "&H00FFFFFF&",          # White
        "outline_color": "&H00000000&",       # Black
        "box_color": "&H80000000&",           # Semi-transparent black background
        "font_size": 62,
        "emphasis_font_size": 72,
        "outline_width": 3,
        "shadow": 3,
        "bold": True,
        "word_highlight": True,
        "pop_in": True,
    },
    "karaoke": {
        "highlight_color": "&H0000FFFF&",
        "text_color": "&H00FFFFFF&",
        "outline_color": "&H00000000&",
        "box_color": "&H80000000&",
        "font_size": 58,
        "emphasis_font_size": 66,
        "outline_width": 2,
        "shadow": 2,
        "bold": True,
        "word_highlight": False,
        "pop_in": False,
    },
    "minimal": {
        "highlight_color": "&H00FFFFFF&",
        "text_color": "&H40FFFFFF&",
        "outline_color": "&H00000000&",
        "box_color": "&HA0000000&",
        "font_size": 52,
        "emphasis_font_size": 58,
        "outline_width": 2,
        "shadow": 0,
        "bold": False,
        "word_highlight": False,
        "pop_in": False,
    },
}


def add_subtitles(
    video_path: Path,
    word_segments: list[WordSegment],
    config: JobConfig,
    refined_subtitles: list[SubtitleLine] | None = None,
) -> Path:
    """Generate styled ASS subtitles and burn them into the video."""
    if not word_segments and not refined_subtitles:
        logger.warning("No subtitle data, skipping")
        return video_path

    style_name = config.subtitle_style
    style = STYLES.get(style_name, STYLES["capcut"])
    ass_path = config.job_temp_dir / f"subs_{video_path.stem}.ass"
    output_path = video_path.parent / f"{video_path.stem}_sub.mp4"

    # Always use Whisper word_segments for accurate timing
    # (AI refined_subtitles have unreliable timestamps)
    lines = _words_to_subtitle_lines(word_segments)

    ass_content = _generate_ass(lines, word_segments, style, style_name)
    ass_path.write_text(ass_content, encoding="utf-8-sig")

    logger.info("Burning subtitles (%d lines, style=%s)", len(lines), style_name)
    burn_subtitles(video_path, ass_path, output_path)

    return output_path


def _words_to_subtitle_lines(
    segments: list[WordSegment],
    max_chars: int = 45,
    max_words: int = 12,
    max_duration: float = 4.0,
) -> list[SubtitleLine]:
    """Convert word segments into display lines.

    Groups words by character count, word count, and time gap.
    Ensures subtitles stay in sync with speech.
    """
    lines = []
    current_words: list[WordSegment] = []
    current_len = 0

    for seg in segments:
        word_len = len(seg.word)

        # Start a new line if:
        # 1) Too many characters
        # 2) Too many words
        # 3) Time gap > 0.8s from previous word (natural pause)
        # 4) Line duration would exceed max_duration
        should_break = False
        if current_words:
            if current_len + word_len + 1 > max_chars:
                should_break = True
            elif len(current_words) >= max_words:
                should_break = True
            elif seg.start - current_words[-1].end > 0.8:
                should_break = True
            elif seg.end - current_words[0].start > max_duration:
                should_break = True

        if should_break and current_words:
            lines.append(SubtitleLine(
                text=_wrap_text(" ".join(w.word for w in current_words)),
                start=current_words[0].start,
                end=current_words[-1].end,
            ))
            current_words = []
            current_len = 0

        current_words.append(seg)
        current_len += word_len + 1

    if current_words:
        lines.append(SubtitleLine(
            text=_wrap_text(" ".join(w.word for w in current_words)),
            start=current_words[0].start,
            end=current_words[-1].end,
        ))

    return lines


def _wrap_text(text: str, chars_per_line: int = 15) -> str:
    """Insert ASS line breaks (\\N) every ~chars_per_line characters at word boundaries."""
    words = text.split()
    result_lines = []
    current_line = ""

    for word in words:
        candidate = (current_line + " " + word).strip()
        if len(candidate) > chars_per_line and current_line:
            result_lines.append(current_line)
            current_line = word
        else:
            current_line = candidate

    if current_line:
        result_lines.append(current_line)

    return "\\N".join(result_lines[:3])  # Max 3 lines


def _ts(seconds: float) -> str:
    """Format seconds to ASS timestamp: H:MM:SS.CC"""
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _generate_ass(
    lines: list[SubtitleLine],
    word_segments: list[WordSegment],
    style: dict,
    style_name: str,
) -> str:
    """Generate a complete ASS subtitle file with commercial-grade styling."""
    fs = style["font_size"]
    efs = style["emphasis_font_size"]
    ow = style["outline_width"]
    sh = style["shadow"]
    bold = -1 if style["bold"] else 0

    header = f"""[Script Info]
Title: Sermon Short-form Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans KR,{fs},{style['text_color']},&H000000FF&,{style['outline_color']},{style['box_color']},{bold},0,0,0,100,100,1,0,3,{ow},{sh},8,60,60,80,1
Style: Emphasis,Noto Sans KR,{efs},{style['highlight_color']},&H000000FF&,{style['outline_color']},{style['box_color']},-1,0,0,0,100,100,1,0,3,{ow + 1},{sh + 1},8,60,60,80,1
Style: WordHL,Noto Sans KR,{fs},{style['highlight_color']},&H000000FF&,{style['outline_color']},{style['box_color']},-1,0,0,0,105,105,1,0,3,{ow},{sh},8,60,60,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    if style_name == "karaoke":
        events = _gen_karaoke(lines, word_segments, style)
    elif style.get("word_highlight") and word_segments:
        events = _gen_word_highlight(lines, word_segments, style)
    else:
        events = _gen_line_display(lines, style)

    return header + "\n".join(events) + "\n"


def _gen_line_display(lines: list[SubtitleLine], style: dict) -> list[str]:
    """Simple line-by-line display with emphasis styling."""
    events = []
    for line in lines:
        style_name = "Emphasis" if line.is_emphasis else "Default"

        # Pop-in animation for emphasis
        text = line.text.replace("\\n", "\\N")
        if line.is_emphasis and style.get("pop_in"):
            text = (
                f"{{\\fscx120\\fscy120\\t(0,150,\\fscx100\\fscy100)}}"
                f"{text}"
            )

        events.append(
            f"Dialogue: 0,{_ts(line.start)},{_ts(line.end)},{style_name},,0,0,0,,{text}"
        )
    return events


def _gen_word_highlight(
    lines: list[SubtitleLine],
    word_segments: list[WordSegment],
    style: dict,
) -> list[str]:
    """CapCut-style word-by-word highlighting with pop animation."""
    events = []

    for line in lines:
        # Find word segments that fall within this line's time range
        line_words = [
            w for w in word_segments
            if w.start >= line.start - 0.1 and w.end <= line.end + 0.5
        ]

        if not line_words:
            # Fallback: show line as-is
            events.append(
                f"Dialogue: 0,{_ts(line.start)},{_ts(line.end)},Default,,0,0,0,,{line.text}"
            )
            continue

        style_name = "Emphasis" if line.is_emphasis else "Default"

        # For each word, show the full line with that word highlighted
        for wi, current_word in enumerate(line_words):
            parts = []
            for i, w in enumerate(line_words):
                if i == wi:
                    # Current word: highlighted + scale pop
                    if style.get("pop_in"):
                        parts.append(
                            f"{{\\c{style['highlight_color']}\\b1"
                            f"\\fscx115\\fscy115\\t(0,100,\\fscx105\\fscy105)}}"
                            f"{w.word}"
                            f"{{\\c{style['text_color']}\\b0\\fscx100\\fscy100}}"
                        )
                    else:
                        parts.append(
                            f"{{\\c{style['highlight_color']}\\b1}}"
                            f"{w.word}"
                            f"{{\\c{style['text_color']}\\b0}}"
                        )
                else:
                    parts.append(w.word)

            text = " ".join(parts)
            events.append(
                f"Dialogue: 0,{_ts(current_word.start)},{_ts(current_word.end)},{style_name},,0,0,0,,{text}"
            )

    return events


def _gen_karaoke(
    lines: list[SubtitleLine],
    word_segments: list[WordSegment],
    style: dict,
) -> list[str]:
    """Karaoke fill-sweep style."""
    events = []

    for line in lines:
        line_words = [
            w for w in word_segments
            if w.start >= line.start - 0.1 and w.end <= line.end + 0.5
        ]

        if not line_words:
            events.append(
                f"Dialogue: 0,{_ts(line.start)},{_ts(line.end)},Default,,0,0,0,,{line.text}"
            )
            continue

        parts = []
        for w in line_words:
            dur_cs = max(1, int((w.end - w.start) * 100))
            parts.append(f"{{\\kf{dur_cs}}}{w.word}")

        text = " ".join(parts)
        style_name = "Emphasis" if line.is_emphasis else "Default"
        events.append(
            f"Dialogue: 0,{_ts(line.start)},{_ts(line.end)},{style_name},,0,0,0,,{text}"
        )

    return events
