"""Anthropic SDK wrapper for SAG demo agents."""

from __future__ import annotations

import os


class ClaudeClient:
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    def complete(self, system_prompt: str, messages: list[dict], max_tokens: int = 1024) -> str:
        self._ensure_client()
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    @property
    def model(self) -> str:
        return self._model
