"""Thin provider layer. The pipeline depends only on LLMClient, so swapping Gemini for
Claude, OpenAI or a local model means adding one class."""

import logging
import random
import time
from typing import Protocol

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

log = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 500, 503}


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    model: str

    def generate_json(self, system: str, user: str, schema: type[BaseModel]) -> str:
        """Return a JSON string that is expected to conform to `schema`."""
        ...


class GeminiClient:
    def __init__(self, api_key: str, model: str, max_attempts: int = 5, base_delay: float = 4.0):
        self.model = model
        self._client = genai.Client(api_key=api_key)
        self._max_attempts = max_attempts
        self._base_delay = base_delay

    def generate_json(self, system: str, user: str, schema: type[BaseModel]) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_schema=schema,
        )
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=user, config=config
                )
                if not response.text:
                    raise LLMError("empty response from model")
                return response.text
            except errors.APIError as e:
                # A daily quota resets in hours; retrying within seconds only wastes time.
                daily_quota = e.code == 429 and "per day" in (e.message or "").lower()
                if e.code not in RETRYABLE_CODES or daily_quota or attempt == self._max_attempts:
                    raise LLMError(f"Gemini API error {e.code}: {e.message}") from e
                # Exponential backoff with jitter: ~4, 8, 16, 32s. Overload (503) spikes last tens of seconds.
                delay = self._base_delay * 2 ** (attempt - 1) * random.uniform(0.8, 1.2)
                log.warning("Gemini %s (attempt %d/%d), retrying in %.0fs", e.code, attempt, self._max_attempts, delay)
                time.sleep(delay)
        raise LLMError("unreachable")
