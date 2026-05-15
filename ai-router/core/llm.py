from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_FALLBACK_CHAIN = [
    "openai/gpt-4o",
    "anthropic/claude-3-opus",
    "google/gemini-2.0-flash",
    "openai/gpt-4o-mini",
]


class LLMError(Exception):
    """Raised when an LLM request fails."""


class LLM:
    """Wrapper around OpenRouter API with fallback chain support."""

    def __init__(
        self,
        api_key: str,
        fallback_chain: list[str] | None = None,
        timeout: int = 60,
        temperature: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.fallback_chain = fallback_chain or DEFAULT_FALLBACK_CHAIN
        self.timeout = timeout
        self.temperature = temperature

    def call(self, model: str, prompt: str) -> str:
        """Call a specific model via OpenRouter."""
        return self._request(model, prompt)

    def fallback_call(self, prompt: str) -> str:
        """Try each model in the fallback chain until one succeeds."""
        errors: list[str] = []
        for model in self.fallback_chain:
            try:
                return self._request(model, prompt)
            except LLMError as exc:
                logger.warning("Model %s failed: %s", model, exc)
                errors.append(f"{model}: {exc}")
        raise LLMError(
            "All models in fallback chain failed:\n" + "\n".join(errors)
        )

    def _request(self, model: str, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }

        try:
            response = requests.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Request to {model} failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(
                f"Invalid JSON response from {model}: {response.text[:200]}"
            ) from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(
                f"Unexpected response structure from {model}: {data}"
            ) from exc
