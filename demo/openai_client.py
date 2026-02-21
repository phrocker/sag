"""OpenAI SDK wrapper for SAG demo agents."""

from __future__ import annotations

import os


class OpenAIClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self._api_key)
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")

    def complete(self, system_prompt: str, messages: list[dict], max_tokens: int = 1024) -> str:
        self._ensure_client()
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=full_messages,
        )
        return response.choices[0].message.content

    @property
    def model(self) -> str:
        return self._model
