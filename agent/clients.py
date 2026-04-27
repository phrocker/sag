"""Instrumented LLM clients that capture token usage into an AccountingCollector.

Each client satisfies the ``LLMClient`` protocol (returns ``str``) while
recording input/output tokens and latency as a side effect.
"""

from __future__ import annotations

import os
import time
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.accounting import AccountingCollector


class InstrumentedClaudeClient:
    """Anthropic SDK wrapper with cost accounting."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        collector: AccountingCollector | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._collector = collector
        self._client = None

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. Run: pip install anthropic"
                )

    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_client()
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        if self._collector:
            self._collector.record_call(
                self._collector.get_current_agent(),
                response.usage.input_tokens,
                response.usage.output_tokens,
                latency_ms,
                self._model,
            )

        return response.content[0].text

    @property
    def model(self) -> str:
        return self._model


class InstrumentedOpenAIClient:
    """OpenAI SDK wrapper with cost accounting."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        collector: AccountingCollector | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._collector = collector
        self._client = None

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import openai

                self._client = openai.OpenAI(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. Run: pip install openai"
                )

    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_client()
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=full_messages,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        if self._collector:
            self._collector.record_call(
                self._collector.get_current_agent(),
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                latency_ms,
                self._model,
            )

        return response.choices[0].message.content

    @property
    def model(self) -> str:
        return self._model
