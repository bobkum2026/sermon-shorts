"""Stage 3: AI-powered sermon highlight selection + subtitle refinement + emphasis detection."""

from __future__ import annotations

import json
import logging
from typing import Any

from pipeline.models import (
    ClipSelection, EmphasisMoment, JobConfig, SubtitleLine,
    TranscriptResult, WordSegment,
)

logger = logging.getLogger(__name__)

# ============================================================
# SERMON-SPECIFIC HIGHLIGHT SELECTION PROMPT
# ============================================================
SELECTION_PROMPT = """당신은 설교 숏폼 영상 전문 편집자입니다.
아래 설교 전사 스크립트를 분석하여 숏폼(YouTube Shorts, 릴스, 틱톡)으로 가장 임팩트 있는 {num_clips}개 구간을 선정하세요.

# 전사 스크립트
---
{transcript}
---

영상 총 길이: {duration:.0f}초

# 선정 기준 (우선순위 순)

1. **첫 문장 후킹력**: 처음 1~3초 안에 시청자를 붙잡을 수 있는 시작점
2. **문맥 독립성**: 앞뒤 설교 없이도 의미가 완전히 전달되는 구간
3. **감정 고조**: 설교자의 강조, 호소, 선포, 질문이 살아있는 순간
4. **메시지 응집도**: 하나의 메시지가 짧은 시간 안에 명확히 전달
5. **숏폼 완결성**: 짧지만 여운과 전달력이 있는 마무리

# 피해야 할 구간
- 맥락 없이 이해 불가능한 부분
- 설명만 길고 임팩트 없는 부분
- 호흡이 너무 느린 부분
- 예화 도입만 있고 결론 없는 부분

# 각 클립에 대해 추가 분석

## 자막 후처리
STT 원문을 숏폼용 자막으로 다듬어주세요:
- 의미 단위로 짧게 끊기 (한 줄 최대 15자 내외)
- 군더더기/반복 제거
- 1~2줄씩 표시
- 핵심 강조 구간 표시

## 줌컷 포인트
클립 내에서 감정이 고조되거나 핵심 메시지가 나오는 순간 2~3곳을 선정하세요.
이 순간에 화면을 1.3배 줌인하여 시청자 몰입을 높입니다.

## 이모지
줌컷 순간에 어울리는 이모지 1개씩 제안하세요.

# 응답 형식 (JSON)
{{
  "clips": [
    {{
      "start_time": 45.2,
      "end_time": 102.5,
      "hook_text": "이것이 십자가의 의미입니다",
      "reason": "설교 핵심 메시지가 강력하게 전달되는 구간",
      "subtitles": [
        {{"text": "십자가 앞에 서면", "start": 0.0, "end": 2.5, "emphasis": false}},
        {{"text": "우리의 모든 것이\\n변합니다", "start": 2.5, "end": 5.0, "emphasis": true}}
      ],
      "zoom_moments": [
        {{"time": 15.3, "duration": 1.5, "emoji": "🔥", "reason": "강조 호소 순간"}},
        {{"time": 38.7, "duration": 1.2, "emoji": "✝️", "reason": "핵심 선포"}}
      ]
    }}
  ]
}}

각 클립은 {min_dur}~{max_dur}초, 겹치지 않게, 바이럴 가능성 높은 순으로 정렬."""


def select_clips(
    transcript: TranscriptResult,
    config: JobConfig,
    video_duration: float = 0,
) -> list[ClipSelection]:
    """Use AI to find the best sermon moments for short-form clips."""
    prompt = SELECTION_PROMPT.format(
        num_clips=config.num_clips,
        transcript=transcript.full_text,
        duration=video_duration,
        min_dur=config.min_duration,
        max_dur=config.max_duration,
    )

    logger.info("Selecting %d highlights via %s...", config.num_clips, config.ai_engine)

    raw_response = _call_ai(prompt, config.ai_engine)
    selections = _parse_response(raw_response, config)

    if not selections:
        logger.warning("AI selection failed, falling back to evenly-spaced clips")
        selections = _fallback_even_split(video_duration, config)

    # Snap timestamps to word boundaries and attach word segments
    selections = _snap_to_words(selections, transcript)

    logger.info("Selected %d clips", len(selections))
    for sel in selections:
        logger.info(
            "  Clip %d: %.1f-%.1f (%.0fs) | hook: %s | %d subtitles | %d zoom points",
            sel.index, sel.start_time, sel.end_time, sel.duration,
            sel.hook_text, len(sel.refined_subtitles), len(sel.emphasis_moments),
        )

    return selections


def _call_ai(prompt: str, engine: str) -> Any:
    """Call the selected AI engine."""
    if engine == "gemini":
        from services.gemini_client import generate_json
        return generate_json(prompt, temperature=0.7)
    else:
        from services.openai_client import chat_completion_json
        return chat_completion_json(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o",
            temperature=0.7,
        )


def _parse_response(data: Any, config: JobConfig) -> list[ClipSelection]:
    """Parse AI JSON response into ClipSelection objects with all enrichments."""
    try:
        # Handle wrapped or direct array
        if isinstance(data, dict):
            for key in ("clips", "moments", "selections", "results"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break

        if not isinstance(data, list):
            return []

        selections = []
        for i, item in enumerate(data[:config.num_clips]):
            # Parse emphasis/zoom moments
            zoom_moments = []
            for zm in item.get("zoom_moments", []):
                zoom_moments.append(EmphasisMoment(
                    time=float(zm.get("time", 0)),
                    duration=float(zm.get("duration", 1.5)),
                    zoom=float(zm.get("zoom", 1.3)),
                    emoji=str(zm.get("emoji", "")),
                    reason=str(zm.get("reason", "")),
                ))

            # Parse refined subtitles
            subtitles = []
            for sub in item.get("subtitles", []):
                subtitles.append(SubtitleLine(
                    text=str(sub.get("text", "")),
                    start=float(sub.get("start", 0)),
                    end=float(sub.get("end", 0)),
                    is_emphasis=bool(sub.get("emphasis", False)),
                ))

            sel = ClipSelection(
                index=i,
                start_time=float(item["start_time"]),
                end_time=float(item["end_time"]),
                hook_text=str(item.get("hook_text", "")),
                reason=str(item.get("reason", "")),
                emphasis_moments=zoom_moments,
                refined_subtitles=subtitles,
            )

            # Validate and adjust duration
            if sel.duration < config.min_duration:
                sel.end_time = sel.start_time + config.min_duration
            elif sel.duration > config.max_duration:
                sel.end_time = sel.start_time + config.max_duration

            selections.append(sel)

        # Remove overlaps
        selections.sort(key=lambda s: s.start_time)
        non_overlapping = []
        for sel in selections:
            if non_overlapping and sel.start_time < non_overlapping[-1].end_time:
                continue
            non_overlapping.append(sel)

        for i, sel in enumerate(non_overlapping):
            sel.index = i

        return non_overlapping

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("Failed to parse AI response: %s", e)
        return []


def _fallback_even_split(duration: float, config: JobConfig) -> list[ClipSelection]:
    """Evenly split the video into clips as a fallback."""
    clip_dur = (config.min_duration + config.max_duration) / 2
    num = min(config.num_clips, max(1, int(duration / clip_dur)))

    gap = max(0, (duration - num * clip_dur) / (num + 1))
    selections = []
    for i in range(num):
        start = gap + i * (clip_dur + gap)
        end = min(start + clip_dur, duration)
        selections.append(ClipSelection(
            index=i,
            start_time=start,
            end_time=end,
            hook_text=f"Part {i + 1}",
        ))
    return selections


def _snap_to_words(
    selections: list[ClipSelection],
    transcript: TranscriptResult,
) -> list[ClipSelection]:
    """Snap clip boundaries to nearest word boundaries and extract word segments."""
    if not transcript.segments:
        return selections

    for sel in selections:
        start_word = _find_nearest_word(transcript.segments, sel.start_time, prefer="after")
        end_word = _find_nearest_word(transcript.segments, sel.end_time, prefer="before")

        if start_word and end_word:
            sel.start_time = start_word.start
            sel.end_time = end_word.end

        # Extract word segments for this clip (relative timestamps)
        sel.word_segments = [
            WordSegment(
                word=w.word,
                start=w.start - sel.start_time,
                end=w.end - sel.start_time,
            )
            for w in transcript.segments
            if sel.start_time <= w.start and w.end <= sel.end_time + 0.5
        ]

        sel.transcript_excerpt = " ".join(w.word for w in sel.word_segments)

        # If AI didn't provide refined subtitles, generate from word segments
        if not sel.refined_subtitles and sel.word_segments:
            sel.refined_subtitles = _auto_subtitle_lines(sel.word_segments)

    return selections


def _auto_subtitle_lines(words: list[WordSegment], max_chars: int = 20) -> list[SubtitleLine]:
    """Auto-generate subtitle lines from word segments when AI doesn't provide them."""
    lines = []
    current_text = ""
    current_start = 0.0

    for w in words:
        if not current_text:
            current_start = w.start

        candidate = (current_text + " " + w.word).strip()
        if len(candidate) > max_chars and current_text:
            lines.append(SubtitleLine(
                text=current_text,
                start=current_start,
                end=w.start,
            ))
            current_text = w.word
            current_start = w.start
        else:
            current_text = candidate

    if current_text:
        lines.append(SubtitleLine(
            text=current_text,
            start=current_start,
            end=words[-1].end if words else current_start + 1,
        ))

    return lines


def _find_nearest_word(
    segments: list[WordSegment],
    target_time: float,
    prefer: str = "after",
) -> WordSegment | None:
    """Find the word segment nearest to a target time."""
    if not segments:
        return None

    best = None
    best_dist = float("inf")

    for seg in segments:
        ref = seg.start if prefer == "after" else seg.end
        dist = abs(ref - target_time)
        if prefer == "after" and ref < target_time - 1:
            continue
        if prefer == "before" and ref > target_time + 1:
            continue
        if dist < best_dist:
            best = seg
            best_dist = dist

    if best is None:
        best = min(segments, key=lambda s: abs(s.start - target_time))

    return best
