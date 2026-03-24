"""OpenAI API wrapper with retry logic."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Get or create the OpenAI client singleton."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set. Add it to .env file.")
        _client = OpenAI(api_key=api_key)
    return _client


def transcribe_audio(
    audio_path: Path,
    language: str = "auto",
    model: str = "whisper-1",
) -> dict:
    """Transcribe audio via OpenAI Whisper API with word-level timestamps."""
    client = get_client()

    kwargs = {
        "model": model,
        "file": open(audio_path, "rb"),
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if language != "auto":
        kwargs["language"] = language

    for attempt in range(3):
        try:
            response = client.audio.transcriptions.create(**kwargs)
            return response.model_dump() if hasattr(response, "model_dump") else dict(response)
        except Exception as e:
            logger.warning("Whisper API attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def chat_completion(
    messages: list[dict],
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
) -> str:
    """Call GPT chat completion with retry."""
    client = get_client()

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    for attempt in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.warning("GPT API attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def chat_completion_json(
    messages: list[dict],
    model: str = "gpt-4o",
    temperature: float = 0.7,
) -> dict | list:
    """Call GPT and parse JSON response."""
    raw = chat_completion(
        messages, model=model, temperature=temperature,
        response_format={"type": "json_object"},
    )
    return json.loads(raw)
