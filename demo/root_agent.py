"""Root conversational agent powered by Claude."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.model import Message, Header, AssertStatement
from sag.correlation import CorrelationEngine
from sag.exceptions import SAGParseException
from sag.prompt import PromptBuilder

from memory import MemoryMonitor
from fold_agent import FoldAgent


class RootAgent:
    def __init__(
        self,
        claude_client: object | None = None,
        budget: int = 10000,
        threshold: float = 0.7,
    ):
        self._client = claude_client
        self._correlation = CorrelationEngine("root")
        self._memory = MemoryMonitor(budget=budget, threshold=threshold)
        self._fold_agent = FoldAgent(claude_client)
        self._history: list[Message] = []
        self._raw_history: list[str] = []
        self._accumulated_state: dict = {}
        self._system_prompt = (
            PromptBuilder()
            .set_preamble(
                "You are a conversational AI agent that communicates using "
                "SAG (Semantic Action Grammar)."
            )
            .set_suffix(
                "When responding to the user, emit SAG messages. "
                "For conversational responses, use:\n"
                'A response = "your response text here"\n\n'
                "You may combine multiple statements in a single message. "
                "For example:\n"
                'A response = "Here is the answer"; '
                'EVT responseGenerated("user_query")\n\n'
                "Keep your responses helpful, concise, and in valid SAG format.\n"
                "If the user speaks in natural language, still respond in SAG format.\n\n"
                "A [Known facts] section may be appended below with key context "
                "preserved from earlier in the conversation. Use these facts when "
                "responding to maintain continuity even after context compression."
            )
            .build()
        )

    def process_input(self, user_text: str) -> tuple[str, list[str]]:
        """Process user input, return (response_text, fold_events)."""
        fold_events: list[str] = []

        # Create user message in SAG format
        user_header = Header(
            version=1,
            message_id=f"user-{int(time.time())}",
            source="user",
            destination="root",
            timestamp=int(time.time()),
        )
        user_msg = Message(
            header=user_header,
            statements=[AssertStatement(path="input", value=user_text)],
        )
        self._history.append(user_msg)
        self._memory.record_message(user_msg)

        # Check memory pressure and fold if needed
        if self._memory.should_fold() and len(self._history) > 4:
            fold_events.extend(self._do_fold())

        # Generate response
        response_text = self._generate_response(user_text)

        # Parse or wrap response as SAG
        response_msg = self._parse_or_wrap_response(response_text)
        self._history.append(response_msg)
        self._memory.record_message(response_msg)

        return response_text, fold_events

    def process_recall(self, fold_id: str) -> str | None:
        """Recall a folded conversation segment."""
        messages = self._fold_agent.unfold(fold_id)
        if messages is None:
            return None

        parts = []
        for msg in messages:
            parts.append(MessageMinifier.to_minified_string(msg))
        return "\n---\n".join(parts)

    def _do_fold(self) -> list[str]:
        """Fold older messages to reduce memory pressure."""
        events = []

        # Fold all but the last 4 messages
        to_fold = self._history[:-4]
        if len(to_fold) < 2:
            return events

        fold_id, original_tokens, fold_tokens, facts = self._fold_agent.fold(to_fold)
        self._memory.record_fold(original_tokens, fold_tokens, f"fold:{fold_id}")

        # Accumulate extracted facts across folds
        if facts:
            self._accumulated_state.update(facts)

        event = f"Folded {len(to_fold)} messages into {fold_id} (saved {original_tokens - fold_tokens} tokens)"
        events.append(event)

        # Replace folded messages with a fold reference
        self._history = self._history[-4:]

        return events

    def _generate_response(self, user_text: str) -> str:
        """Generate response using Claude or fallback."""
        # Build system prompt with accumulated facts
        system_prompt = self._system_prompt
        if self._accumulated_state:
            import json
            facts_str = json.dumps(self._accumulated_state, indent=2)
            system_prompt += f"\n\n[Known facts]\nThese facts were established earlier in the conversation and should be referenced when relevant:\n{facts_str}"

        if self._client:
            try:
                # Build conversation context from recent history
                messages = []
                for msg in self._history[-10:]:  # Last 10 messages for context
                    minified = MessageMinifier.to_minified_string(msg)
                    role = "user" if msg.header.source == "user" else "assistant"
                    messages.append({"role": role, "content": minified})

                # Ensure messages alternate correctly
                if not messages or messages[-1]["role"] != "user":
                    messages.append({"role": "user", "content": user_text})

                result = self._client.complete(
                    system_prompt,
                    messages,
                    max_tokens=512,
                )
                return result
            except Exception as e:
                return f'A response = "I encountered an error: {e}"'

        # Fallback response
        return f'A response = "Echo: {user_text}"'

    def _parse_or_wrap_response(self, response_text: str) -> Message:
        """Parse as SAG or wrap plain text."""
        # Try to parse as a full SAG message
        try:
            if response_text.strip().startswith("H v"):
                return SAGMessageParser.parse(response_text)
        except SAGParseException:
            pass

        # Wrap as a SAG message with assert
        header = self._correlation.create_response_header("root", "user")
        safe_text = response_text.replace('"', '\\"').replace("\n", "\\n")
        msg_text = (
            f"H v 1 id={header.message_id} src=root dst=user ts={header.timestamp}\n"
            f'A response = "{safe_text}"'
        )
        try:
            return SAGMessageParser.parse(msg_text)
        except SAGParseException:
            # Last resort: minimal message
            return Message(
                header=header,
                statements=[AssertStatement(path="response", value=response_text)],
            )

    @property
    def memory(self) -> MemoryMonitor:
        return self._memory

    @property
    def fold_agent(self) -> FoldAgent:
        return self._fold_agent

    @property
    def history(self) -> list[Message]:
        return list(self._history)
