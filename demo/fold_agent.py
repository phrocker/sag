"""Fold agent: summarizes messages for compression."""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.minifier import MessageMinifier
from sag.model import AssertStatement, Message
from sag.fold import FoldEngine


class FoldAgent:
    def __init__(self, claude_client: object | None = None):
        self._client = claude_client
        self._engine = FoldEngine()
        self._system_prompt = ""

        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "fold_system.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                self._system_prompt = f.read()

    def fold(self, messages: list[Message], state: dict | None = None) -> tuple[str, int, int, dict]:
        """Fold messages, return (fold_id, original_tokens, fold_tokens, facts)."""
        # Count original tokens
        original_tokens = sum(
            MessageMinifier.count_tokens(MessageMinifier.to_minified_string(m))
            for m in messages
        )

        # Generate summary and extract facts
        summary, facts = self._generate_summary(messages)

        # Merge any caller-provided state with extracted facts
        merged_state = dict(state) if state else {}
        merged_state.update(facts)

        # Create fold
        fold_stmt = self._engine.fold(messages, summary, merged_state or None)

        # Count fold tokens
        fold_text = f'FOLD {fold_stmt.fold_id} "{summary}"'
        fold_tokens = MessageMinifier.count_tokens(fold_text)

        return fold_stmt.fold_id, original_tokens, fold_tokens, merged_state

    def unfold(self, fold_id: str) -> list[Message] | None:
        return self._engine.unfold(fold_id)

    def _generate_summary(self, messages: list[Message]) -> tuple[str, dict]:
        """Generate a summary and extract facts. Returns (summary, facts)."""
        if self._client:
            try:
                msg_texts = [MessageMinifier.to_minified_string(m) for m in messages]
                combined = "\n---\n".join(msg_texts)
                result = self._client.complete(
                    self._system_prompt,
                    [{"role": "user", "content": f"Summarize these SAG messages:\n{combined}"}],
                    max_tokens=256,
                )
                return self._parse_summary_response(result)
            except Exception:
                pass

        # Fallback: generate a basic summary and extract facts from assertions
        summary = self._fallback_summary(messages)
        facts = self._extract_facts_from_assertions(messages)
        return summary, facts

    def _parse_summary_response(self, response: str) -> tuple[str, dict]:
        """Parse the two-line LLM response into (summary, facts)."""
        lines = response.strip().splitlines()
        summary = lines[0].strip()[:200] if lines else "conversation exchanged"
        facts = {}
        if len(lines) >= 2:
            try:
                facts = json.loads(lines[1].strip())
                if not isinstance(facts, dict):
                    facts = {}
            except (json.JSONDecodeError, ValueError):
                pass
        return summary, facts

    def _extract_facts_from_assertions(self, messages: list[Message]) -> dict:
        """Fallback fact extraction: scan AssertStatements for key-value facts."""
        facts = {}
        for msg in messages:
            for stmt in msg.statements:
                if isinstance(stmt, AssertStatement) and stmt.path and stmt.value:
                    # Keep assertion values that look like meaningful facts
                    if stmt.path != "response" and isinstance(stmt.value, str) and len(stmt.value) < 200:
                        facts[stmt.path] = stmt.value
        return facts

    def _fallback_summary(self, messages: list[Message]) -> str:
        """Generate a basic summary without LLM."""
        verbs = []
        for msg in messages:
            for stmt in msg.statements:
                if hasattr(stmt, "verb"):
                    verbs.append(stmt.verb)
                elif hasattr(stmt, "event_name"):
                    verbs.append(f"evt:{stmt.event_name}")

        if verbs:
            return f"{len(messages)} messages: {', '.join(verbs[:5])}"
        return f"{len(messages)} messages exchanged"

    @property
    def engine(self) -> FoldEngine:
        return self._engine
