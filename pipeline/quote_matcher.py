"""Quote-based clip selection: find user-provided sentences in the transcript.

Replaces AI selection when user provides specific quotes.
Uses fuzzy text matching to find the best matching position in Whisper output.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from pipeline.models import ClipSelection, JobConfig, TranscriptResult, WordSegment

logger = logging.getLogger(__name__)

# How many seconds of padding to add before/after the matched quote
PAD_BEFORE = 2.0
PAD_AFTER = 3.0


def match_quotes(
    transcript: TranscriptResult,
    config: JobConfig,
) -> list[ClipSelection]:
    """Find each quote in the transcript and return clip selections."""
    selections = []

    for i, quote in enumerate(config.quotes):
        quote = quote.strip()
        if not quote:
            continue

        logger.info("Matching quote %d: '%s'", i, quote[:50])
        match = _find_quote_in_transcript(quote, transcript)

        if match:
            start_time, end_time, matched_words = match

            # Apply padding
            padded_start = max(0, start_time - PAD_BEFORE)
            padded_end = end_time + PAD_AFTER

            # Ensure minimum duration
            if padded_end - padded_start < config.min_duration:
                # Expand equally on both sides
                expand = (config.min_duration - (padded_end - padded_start)) / 2
                padded_start = max(0, padded_start - expand)
                padded_end = padded_end + expand

            # Cap at max duration
            if padded_end - padded_start > config.max_duration:
                padded_end = padded_start + config.max_duration

            # Get all word segments in the clip range (relative timestamps)
            clip_words = [
                WordSegment(
                    word=w.word,
                    start=w.start - padded_start,
                    end=w.end - padded_start,
                )
                for w in transcript.segments
                if padded_start <= w.start and w.end <= padded_end + 0.5
            ]

            sel = ClipSelection(
                index=i,
                start_time=padded_start,
                end_time=padded_end,
                hook_text=_make_hook(quote),
                reason=f"User quote: {quote[:80]}",
                word_segments=clip_words,
                transcript_excerpt=" ".join(w.word for w in clip_words),
            )
            selections.append(sel)

            logger.info(
                "  Matched: %.1f-%.1f (%.0fs), %d words",
                padded_start, padded_end, sel.duration, len(clip_words),
            )
        else:
            logger.warning("  No match found for: '%s'", quote[:80])

    logger.info("Matched %d/%d quotes", len(selections), len(config.quotes))
    return selections


def _find_quote_in_transcript(
    quote: str,
    transcript: TranscriptResult,
) -> tuple[float, float, list[WordSegment]] | None:
    """Find the best matching position of a quote in the transcript.

    Uses a sliding window of words and fuzzy matching.
    Returns (start_time, end_time, matched_words) or None.
    """
    words = transcript.segments
    if not words:
        return None

    quote_clean = _normalize(quote)
    quote_word_count = len(quote_clean.split())

    # Sliding window: try different window sizes around the expected word count
    best_score = 0.0
    best_match = None

    for window_size in range(
        max(1, quote_word_count - 3),
        min(len(words), quote_word_count + 10),
    ):
        for start_idx in range(len(words) - window_size + 1):
            window_words = words[start_idx : start_idx + window_size]
            window_text = _normalize(" ".join(w.word for w in window_words))

            score = SequenceMatcher(None, quote_clean, window_text).ratio()

            if score > best_score:
                best_score = score
                best_match = (
                    window_words[0].start,
                    window_words[-1].end,
                    window_words,
                )

    # Require at least 50% similarity
    if best_score >= 0.5 and best_match:
        logger.info("  Match score: %.1f%%", best_score * 100)
        return best_match

    return None


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip punctuation."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s가-힣]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _make_hook(quote: str, max_len: int = 30) -> str:
    """Create a hook text from the quote."""
    if len(quote) <= max_len:
        return quote
    # Cut at word boundary
    truncated = quote[:max_len]
    last_space = truncated.rfind(' ')
    if last_space > max_len // 2:
        return truncated[:last_space] + "..."
    return truncated + "..."
