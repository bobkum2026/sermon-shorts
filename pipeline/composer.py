"""Stage 6: Final composition - title bar, zoom cuts, progress bar, hook, music, fades.

Layout when title_text is set:
┌──────────────────┐
│                  │
│   Video (top ~80%)│
│                  │
│▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│ ← gradient (video → black)
│██████████████████│
│   Title Text     │ ← solid black bar (~20%)
│██████████████████│
└──────────────────┘
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.models import ClipSelection, EmphasisMoment, JobConfig
from services.ffmpeg_wrapper import get_video_info, run_ffmpeg

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"


def compose(
    video_path: Path,
    selection: ClipSelection,
    config: JobConfig,
) -> Path:
    """Apply final effects: title bar, zoom cuts, progress bar, hook, music, fades."""
    output_dir = config.job_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"short_{selection.index:02d}.mp4"

    info = get_video_info(video_path)
    duration = info["duration"]
    width = info["width"]
    height = info["height"]

    # ── If title bar is enabled, do a two-pass approach ──
    has_title = config.title_text or config.scripture_text or config.speaker_text
    if has_title:
        titled_path = config.job_temp_dir / f"clip_{selection.index}_titled.mp4"
        _apply_title_bar(video_path, titled_path, config, width, height, duration)
        video_path = titled_path

    vfilters = []
    afilters = []
    inputs = ["-i", str(video_path)]

    # ── 1. ZOOM CUTS (applied as separate pass for ffmpeg expression safety) ──
    if config.add_zoom_cuts and selection.emphasis_moments:
        zoomed_path = config.job_temp_dir / f"clip_{selection.index}_zoomed.mp4"
        if _apply_zoom_cut(video_path, zoomed_path, selection.emphasis_moments, width, height):
            video_path = zoomed_path
            inputs = ["-i", str(video_path)]

    # ── 2. PROGRESS BAR ──
    if config.add_progress_bar:
        # Place progress bar just above the black bar area (or near bottom)
        if has_title:
            bar_pct = config.bar_ratio / 100.0
            bar_y = int(height * (1.0 - bar_pct - 0.005))
        else:
            bar_y = height - 6 - 20
        bar_h = 4
        vfilters.append(
            f"drawbox=x=0:y={bar_y}:w=iw:h={bar_h}:color=gray@0.3:t=fill"
        )
        vfilters.append(
            f"drawbox=x=0:y={bar_y}"
            f":w='(t/{duration:.2f})*iw'"
            f":h={bar_h}:color=white@0.9:t=fill"
        )

    # ── 3. HOOK + EMOJI via ASS overlay ──
    ass_path = None
    has_overlay = (config.add_hook and selection.hook_text) or (config.add_emoji and selection.emphasis_moments)
    if has_overlay:
        ass_path = _generate_overlay_ass(
            config.job_temp_dir / f"overlay_{selection.index}.ass",
            selection, config, width, height, duration,
        )

    if ass_path:
        escaped_ass = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
        vfilters.append(f"ass='{escaped_ass}'")

    # ── 4. FADE IN/OUT ──
    fade_in = 0.4
    fade_out = 0.8
    if duration > fade_in + fade_out:
        vfilters.append(f"fade=t=in:st=0:d={fade_in}")
        vfilters.append(f"fade=t=out:st={duration - fade_out:.2f}:d={fade_out}")
        afilters.append(f"afade=t=in:st=0:d={fade_in}")
        afilters.append(f"afade=t=out:st={duration - fade_out:.2f}:d={fade_out}")

    # ── 5. BACKGROUND MUSIC ──
    music_path = _find_music_track() if config.add_music else None
    filter_a_complex = None

    if music_path:
        inputs += ["-i", str(music_path)]
        afilters_str = ",".join(afilters) if afilters else "acopy"
        filter_a_complex = (
            f"[0:a]{afilters_str}[speech];"
            f"[1:a]volume=-18dB,afade=t=in:st=0:d=1,"
            f"afade=t=out:st={duration - 1.5:.2f}:d=1.5[music];"
            f"[speech][music]amix=inputs=2:duration=first[aout]"
        )
        afilters = []

    # ── BUILD FFMPEG COMMAND ──
    vf_chain = ",".join(vfilters) if vfilters else None
    af_chain = ",".join(afilters) if afilters else None
    args = inputs[:]

    if filter_a_complex:
        vf_part = f"[0:v]{vf_chain}[vout];" if vf_chain else ""
        full_filter = f"{vf_part}{filter_a_complex}"
        args += ["-filter_complex", full_filter]
        if vf_chain:
            args += ["-map", "[vout]"]
        else:
            args += ["-map", "0:v"]
        args += ["-map", "[aout]"]
    elif vf_chain and af_chain:
        args += ["-vf", vf_chain, "-af", af_chain]
    elif vf_chain:
        args += ["-vf", vf_chain, "-c:a", "copy"]
    elif af_chain:
        args += ["-af", af_chain, "-c:v", "copy"]
    else:
        args += ["-c", "copy"]

    if vf_chain or af_chain or filter_a_complex:
        args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-b:a", "128k"]

    args += ["-shortest", str(final_path)]

    logger.info(
        "Composing clip %d: title=%s, zoom=%s, bar=%s, hook=%s, emoji=%d, music=%s",
        selection.index,
        bool(config.title_text),
        bool(config.add_zoom_cuts and selection.emphasis_moments),
        config.add_progress_bar,
        bool(config.add_hook and selection.hook_text),
        len([em for em in selection.emphasis_moments if em.emoji]),
        bool(music_path),
    )

    run_ffmpeg(args, timeout=600)
    logger.info("Clip %d exported: %s", selection.index, final_path)
    return final_path


# ─────────────────────────────────────────────────────
# TITLE BAR: gradient overlay + title text
# ─────────────────────────────────────────────────────

def _apply_title_bar(
    video_path: Path,
    output_path: Path,
    config: JobConfig,
    width: int,
    height: int,
    duration: float,
) -> None:
    """Overlay a gradient-to-black bar at the bottom with title text.

    Creates a PNG overlay using Pillow, then composites via ffmpeg.
    """
    # Generate gradient overlay PNG
    gradient_png = config.job_temp_dir / f"gradient_overlay.png"
    bar_pct = config.bar_ratio / 100.0  # e.g. 0.40
    _generate_gradient_overlay(gradient_png, width, height, bar_pct)

    # Generate title text ASS — combine 3 lines with \n separator
    title_ass = config.job_temp_dir / f"title_overlay.ass"
    combined_title = "\n".join([config.title_text, config.scripture_text, config.speaker_text])
    _generate_title_ass(title_ass, width, height, duration, combined_title,
                        title_fs=config.title_font_size, sub_fs=config.sub_font_size,
                        bar_pct=bar_pct,
                        title_y_pct=config.title_y_pct / 100.0,
                        sub_y_pct=config.sub_y_pct / 100.0)

    # ffmpeg: overlay gradient PNG + burn title ASS
    escaped_ass = str(title_ass).replace("\\", "\\\\").replace(":", "\\:")
    run_ffmpeg([
        "-i", str(video_path),
        "-i", str(gradient_png),
        "-filter_complex",
        f"[0:v][1:v]overlay=0:0,ass='{escaped_ass}'[vout]",
        "-map", "[vout]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        str(output_path),
    ], timeout=300)

    logger.info("Title bar applied: %s / %s / %s", config.title_text, config.scripture_text, config.speaker_text)


def _generate_gradient_overlay(png_path: Path, width: int, height: int, bar_pct: float) -> None:
    """Generate a transparent-to-black gradient PNG using Pillow."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # bar_pct = 0.40 means bottom 40% is black
    video_pct = 1.0 - bar_pct
    gradient_start = int(height * (video_pct - 0.20))  # Gradient starts 20% above black
    gradient_end = int(height * video_pct)              # Black starts here
    black_start = gradient_end

    # Draw gradient zone (transparent → black)
    for y in range(gradient_start, gradient_end):
        progress = (y - gradient_start) / (gradient_end - gradient_start)
        # Ease-in curve for smoother gradient
        alpha = int(255 * (progress ** 1.5))
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Draw solid black zone
    draw.rectangle([(0, black_start), (width, height)], fill=(0, 0, 0, 255))

    img.save(str(png_path), "PNG")
    logger.debug("Generated gradient overlay: %s", png_path)


def _generate_title_ass(
    ass_path: Path,
    width: int,
    height: int,
    duration: float,
    title: str,
    title_fs: int = 90,
    sub_fs: int = 44,
    bar_pct: float = 0.40,
    title_y_pct: float = 0.25,
    sub_y_pct: float = 0.65,
) -> None:
    """Generate ASS subtitle for title in the black bar area."""
    def _ts(s: float) -> str:
        s = max(0, s)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    # Parse the combined title — lines are separated by \n
    lines = title.split("\n") if "\n" in title else [title]
    line1 = lines[0] if len(lines) > 0 else ""  # Title
    line2 = lines[1] if len(lines) > 1 else ""  # Scripture
    line3 = lines[2] if len(lines) > 2 else ""  # Speaker

    # Layout: position within the black bar area using user-defined percentages
    x_center = width // 2
    video_pct = 1.0 - bar_pct  # e.g. 0.60
    # Convert in-bar % to absolute screen position
    y_title = int(height * (video_pct + bar_pct * title_y_pct))
    y_sub = int(height * (video_pct + bar_pct * sub_y_pct))

    # Combine scripture + speaker into one line
    sub_parts = [p for p in [line2, line3] if p]
    sub_line = "  |  ".join(sub_parts)

    content = f"""[Script Info]
Title: Title Overlay
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MainTitle,Noto Sans KR,{title_fs},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,0,0,5,60,60,0,1
Style: SubInfo,Noto Sans KR,{sub_fs},&H00BBBBBB,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if line1:
        events.append(
            f"Dialogue: 20,{_ts(0)},{_ts(duration)},MainTitle,,0,0,0,,"
            f"{{\\pos({x_center},{y_title})}}{line1}"
        )
    if sub_line:
        events.append(
            f"Dialogue: 20,{_ts(0)},{_ts(duration)},SubInfo,,0,0,0,,"
            f"{{\\pos({x_center},{y_sub})}}{sub_line}"
        )

    content += "\n".join(events) + "\n"
    ass_path.write_text(content, encoding="utf-8-sig")


# ─────────────────────────────────────────────────────
# HOOK + EMOJI OVERLAY
# ─────────────────────────────────────────────────────

def _generate_overlay_ass(
    ass_path: Path,
    selection: ClipSelection,
    config: JobConfig,
    width: int,
    height: int,
    duration: float,
) -> Path:
    """Generate ASS file for hook text and emoji overlays."""
    def _ts(s: float) -> str:
        s = max(0, s)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    # Hook position: upper area (35% from top) so it doesn't clash with title bar
    hook_y = int(height * 0.30)

    header = f"""[Script Info]
Title: Overlay
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Noto Sans KR,68,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,3,5,3,5,40,40,0,1
Style: Emoji,Noto Sans KR,100,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,3,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    if config.add_hook and selection.hook_text:
        hook = selection.hook_text.replace("\\", "\\\\")
        events.append(
            f"Dialogue: 10,{_ts(0.2)},{_ts(2.7)},Hook,,0,0,{hook_y},,{{\\fad(300,500)}}{hook}"
        )

    if config.add_emoji:
        for em in selection.emphasis_moments:
            if em.emoji:
                events.append(
                    f"Dialogue: 10,{_ts(em.time)},{_ts(em.time + em.duration)},Emoji,,0,0,0,,"
                    f"{{\\fad(200,300)\\pos({width - 120},120)}}{em.emoji}"
                )

    content = header + "\n".join(events) + "\n"
    ass_path.write_text(content, encoding="utf-8-sig")
    return ass_path


# ─────────────────────────────────────────────────────
# ZOOM CUTS
# ─────────────────────────────────────────────────────

def _apply_zoom_cut(
    input_path: Path,
    output_path: Path,
    moments: list[EmphasisMoment],
    width: int,
    height: int,
) -> bool:
    """Apply zoom cut effect as a separate ffmpeg pass. Returns True on success."""
    em = moments[0]  # Use first emphasis moment for reliability
    t0 = em.time
    t1 = t0 + em.duration
    z = em.zoom

    # Simple approach: use setpts + scale for the zoom portion
    # Even simpler: use the crop filter with expressions
    # Safest: use zoompan with very simple expression (no commas in values)
    try:
        zoom_expr = f"if(between(t\\,{t0:.1f}\\,{t1:.1f})\\,{z:.1f}\\,1)"
        run_ffmpeg([
            "-i", str(input_path),
            "-vf",
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps=30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ], timeout=300)
        return True
    except Exception as e:
        logger.warning("Zoom cut failed, skipping: %s", e)
        return False


def _build_zoom_expression(moments: list[EmphasisMoment], total_duration: float) -> str:
    """Build ffmpeg zoompan expression for emphasis zoom cuts.

    Uses simple if/between chains — avoids nested max() which breaks ffmpeg parser.
    Only the first zoom moment is applied to keep the expression simple and reliable.
    """
    if not moments:
        return "1"

    # Use only the first emphasis moment for reliability
    em = moments[0]
    t0 = em.time
    t1 = t0 + 0.3           # zoom-in complete
    t2 = t0 + em.duration - 0.3  # zoom-out starts
    t3 = t0 + em.duration   # back to 1.0
    z = em.zoom

    # Piecewise: ramp up, hold, ramp down, else 1.0
    expr = (
        f"if(between(t\\,{t0:.2f}\\,{t1:.2f})\\,"
        f"1+{z-1:.2f}*(t-{t0:.2f})/0.3\\,"
        f"if(between(t\\,{t1:.2f}\\,{t2:.2f})\\,"
        f"{z:.2f}\\,"
        f"if(between(t\\,{t2:.2f}\\,{t3:.2f})\\,"
        f"{z:.2f}-{z-1:.2f}*(t-{t2:.2f})/0.3\\,"
        f"1)))"
    )
    return expr


def _find_music_track() -> Path | None:
    """Find a random music track from assets/music/."""
    music_dir = ASSETS_DIR / "music"
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
    return random.choice(tracks) if tracks else None
