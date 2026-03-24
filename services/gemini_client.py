"""Google Gemini API wrapper with retry logic."""

from __future__ import annotations

import json
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Get or create the Gemini model singleton."""
    global _model
    if _model is None:
        import google.generativeai as genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set. Add it to .env file.")
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel("gemini-2.0-flash")
    return _model


def generate(
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    """Call Gemini and return text response."""
    model = _get_model()

    for attempt in range(3):
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            return response.text
        except Exception as e:
            logger.warning("Gemini API attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def generate_json(prompt: str, temperature: float = 0.7) -> dict | list:
    """Call Gemini and parse JSON response."""
    raw = generate(prompt, temperature=temperature)

    # Extract JSON from markdown code blocks if present
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]

    return json.loads(raw.strip())
