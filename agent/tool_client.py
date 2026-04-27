"""Tool-aware LLM clients with multi-turn tool-calling loop.

Wraps ``InstrumentedClaudeClient`` or ``InstrumentedOpenAIClient`` and adds
automatic tool dispatch: call LLM → detect tool_use blocks → execute via
``ToolExecutor`` → feed results back → repeat until text response.

Each API round-trip is recorded via the underlying client's accounting.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.tools import Tool, ToolCall, ToolExecutor, ToolParam, ToolResult


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ToolTurnRecord:
    """Record of a single tool-use turn in a multi-turn conversation."""

    calls: list[ToolCall]
    results: list[ToolResult]


@dataclass
class CompletionResult:
    """Result of a tool-aware completion."""

    text: str
    tool_turns: list[ToolTurnRecord] = field(default_factory=list)
    total_tool_calls: int = 0
    folds_performed: int = 0


# ---------------------------------------------------------------------------
# Auto-fold helpers
# ---------------------------------------------------------------------------

# Approximate chars-per-token ratio
_CHARS_PER_TOKEN = 4

# When conversation tokens exceed this fraction of budget, fold early turns
_FOLD_THRESHOLD = 0.5


def _msg_content(msg) -> str | list | None:
    """Extract content from a message, whether dict or Pydantic object."""
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "") or ""


def _estimate_tokens(messages: list) -> int:
    """Rough token estimate for a conversation."""
    total = 0
    for msg in messages:
        content = _msg_content(msg)
        if isinstance(content, str):
            total += len(content) // _CHARS_PER_TOKEN
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    c = item.get("content", "")
                    if isinstance(c, str):
                        total += len(c) // _CHARS_PER_TOKEN
                elif hasattr(item, "text"):
                    total += len(item.text) // _CHARS_PER_TOKEN
        elif hasattr(content, "__iter__"):
            for item in content:
                if hasattr(item, "text"):
                    total += len(item.text) // _CHARS_PER_TOKEN
    return total


def _make_fold_summary(content: str) -> str:
    """Create a compact fold summary from tool result content.

    Keeps the first line (usually path/key info) plus a byte count.
    """
    first_line = content.split("\n", 1)[0].rstrip()
    if len(first_line) > 120:
        first_line = first_line[:120] + "..."
    return f"{first_line}\n[... folded: {len(content)} chars, see earlier context]"


def _fold_conversation(
    messages: list[dict],
    context_budget: int,
    fold_engine=None,
) -> tuple[list[dict], int]:
    """Fold early tool results to compress conversation context.

    Replaces the content of early tool result messages with a summary.
    Returns (compressed_messages, number_of_folds_performed).
    """
    if fold_engine is None:
        return messages, 0
    if context_budget <= 0:
        return messages, 0

    current = _estimate_tokens(messages)
    if current < context_budget * _FOLD_THRESHOLD:
        return messages, 0

    # Find foldable tool result messages.
    # Anthropic format: user message with content list containing {"type": "tool_result"}
    # OpenAI format: {"role": "tool", "content": "..."} messages
    foldable_indices = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = _msg_content(msg)

        # OpenAI tool messages
        if role == "tool" and isinstance(content, str) and len(content) > 200:
            foldable_indices.append(i)
            continue

        # Anthropic tool_result blocks
        if isinstance(content, list):
            has_tool_result = any(
                isinstance(item, dict) and item.get("type") == "tool_result"
                for item in content
            )
            if has_tool_result:
                foldable_indices.append(i)

    if not foldable_indices:
        return messages, 0

    # Fold the oldest tool results until we're under budget
    compressed = list(messages)
    folds = 0
    # Keep at least the last 1 tool result unfolded
    foldable = foldable_indices[:-1] if len(foldable_indices) > 1 else []

    for idx in foldable:
        if _estimate_tokens(compressed) < context_budget * _FOLD_THRESHOLD:
            break

        msg = compressed[idx]
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = _msg_content(msg)

        # OpenAI format: simple string content on role=tool
        if role == "tool" and isinstance(content, str) and len(content) > 200:
            tool_id = msg.get("tool_call_id", "unknown") if isinstance(msg, dict) else "unknown"
            summary = _make_fold_summary(content)
            state = {"tool_call_id": tool_id, "original_length": len(content)}
            fold_engine.fold([], f"Tool result {tool_id}", state=state)
            compressed[idx] = {**msg, "content": summary}
            folds += 1
            continue

        # Anthropic format: list of content blocks
        if not isinstance(content, list):
            continue

        folded_items = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                original = item.get("content", "")
                if isinstance(original, str) and len(original) > 200:
                    tool_id = item.get("tool_use_id", "unknown")
                    summary = _make_fold_summary(original)
                    state = {"tool_use_id": tool_id, "original_length": len(original)}
                    fold_engine.fold([], f"Tool result {tool_id}", state=state)
                    folded_items.append({**item, "content": summary})
                    folds += 1
                else:
                    folded_items.append(item)
            else:
                folded_items.append(item)

        compressed[idx] = {**msg, "content": folded_items}

    return compressed, folds


# ---------------------------------------------------------------------------
# Schema converters
# ---------------------------------------------------------------------------


def _param_type_to_json_schema(type_str: str) -> dict[str, str]:
    """Map ToolParam.type to JSON Schema type."""
    mapping = {"string": "string", "integer": "integer", "boolean": "boolean"}
    return {"type": mapping.get(type_str, "string")}


def tools_to_anthropic_schema(tools: list[Tool]) -> list[dict]:
    """Convert Tool list to Anthropic tool schema format."""
    schemas = []
    for tool in tools:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in tool.parameters:
            prop = {**_param_type_to_json_schema(p.type), "description": p.description}
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        schema: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
            },
        }
        if required:
            schema["input_schema"]["required"] = required
        schemas.append(schema)
    return schemas


def tools_to_openai_schema(tools: list[Tool]) -> list[dict]:
    """Convert Tool list to OpenAI function-calling schema format."""
    schemas = []
    for tool in tools:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in tool.parameters:
            prop = {**_param_type_to_json_schema(p.type), "description": p.description}
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        fn_def: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }
        if required:
            fn_def["function"]["parameters"]["required"] = required
        schemas.append(fn_def)
    return schemas


# ---------------------------------------------------------------------------
# Tool-aware Claude client
# ---------------------------------------------------------------------------

# Safety-net ceiling — user controls actual stopping via should_continue callback
MAX_TOOL_TURNS = 100


class ToolAwareClaudeClient:
    """Wraps an InstrumentedClaudeClient with multi-turn tool execution.

    On each call:
    1. Send messages + tool schemas to the API
    2. If response has tool_use blocks, execute them via ToolExecutor
    3. Append tool results and call again
    4. Repeat until we get a text response (or hit max turns)
    5. Auto-fold earlier tool results if context grows too large
    """

    def __init__(
        self,
        client,  # InstrumentedClaudeClient
        executor: ToolExecutor,
        max_turns: int = MAX_TOOL_TURNS,
        on_tool_call: Callable[[ToolCall], None] | None = None,
        on_tool_result: Callable[[ToolResult], None] | None = None,
        should_continue: Callable[[int, list[ToolResult]], str] | None = None,
        fold_engine=None,
        context_budget: int = 100_000,
    ) -> None:
        self._client = client
        self._executor = executor
        self._max_turns = max_turns
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._should_continue = should_continue
        self._fold_engine = fold_engine
        self._context_budget = context_budget

    @property
    def model(self) -> str:
        return self._client.model

    @property
    def executor(self) -> ToolExecutor:
        return self._executor

    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> str:
        """Simple interface matching LLMClient protocol — returns text only."""
        result = self.complete_with_tools(system_prompt, messages, max_tokens)
        return result.text

    def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> CompletionResult:
        """Full tool-aware completion returning CompletionResult."""
        self._client._ensure_client()

        # Capture agent_id once at call start for thread safety — the
        # collector's _current_agent may be overwritten by concurrent agents.
        agent_id = (
            self._client._collector.get_current_agent()
            if self._client._collector
            else ""
        )

        tool_schemas = tools_to_anthropic_schema(self._executor.tools)
        conversation = list(messages)
        tool_turns: list[ToolTurnRecord] = []
        total_calls = 0
        total_folds = 0
        force_text = False  # Set by should_continue("finish")

        for _turn in range(self._max_turns):
            # Check with caller whether to continue exploring
            if _turn > 0 and self._should_continue:
                last_results = tool_turns[-1].results if tool_turns else []
                decision = self._should_continue(_turn, last_results)
                if decision == "stop":
                    break
                elif decision == "finish":
                    force_text = True

            # Auto-fold if context is getting large
            if self._fold_engine:
                conversation, folds = _fold_conversation(
                    conversation, self._context_budget, self._fold_engine,
                )
                total_folds += folds

            # Withhold tools to force text on last turn or user "finish"
            is_last_turn = force_text or _turn == self._max_turns - 1
            offer_tools = tool_schemas if (tool_schemas and not is_last_turn) else None

            import time

            start = time.perf_counter()
            response = self._client._client.messages.create(
                model=self._client.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=conversation,
                tools=offer_tools,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            # Record accounting
            if self._client._collector:
                self._client._collector.record_call(
                    agent_id,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    latency_ms,
                    self._client.model,
                )

            # Check for tool use
            tool_use_blocks = [
                b for b in response.content if b.type == "tool_use"
            ]

            if not tool_use_blocks:
                # Pure text response — extract and return
                text_parts = [
                    b.text for b in response.content if hasattr(b, "text")
                ]
                return CompletionResult(
                    text="\n".join(text_parts),
                    tool_turns=tool_turns,
                    total_tool_calls=total_calls,
                    folds_performed=total_folds,
                )

            # Execute tool calls
            calls: list[ToolCall] = []
            results: list[ToolResult] = []
            tool_result_content: list[dict] = []

            for block in tool_use_blocks:
                tc = ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                )
                calls.append(tc)
                total_calls += 1

                if self._on_tool_call:
                    self._on_tool_call(tc)

                tr = self._executor.execute(tc)
                results.append(tr)

                if self._on_tool_result:
                    self._on_tool_result(tr)

                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": tr.output,
                    "is_error": tr.is_error,
                })

            tool_turns.append(ToolTurnRecord(calls=calls, results=results))

            # Append assistant message (with tool_use) and tool results
            conversation.append({"role": "assistant", "content": response.content})
            conversation.append({"role": "user", "content": tool_result_content})

        # Max turns exhausted — extract any text from the last response
        text_parts = [
            b.text for b in response.content if hasattr(b, "text")
        ]
        fallback = "\n".join(text_parts).strip() if text_parts else ""
        if not fallback:
            fallback = (
                "(max tool turns reached — agent used all tool turns "
                "without producing a final text response)"
            )
        return CompletionResult(
            text=fallback,
            tool_turns=tool_turns,
            total_tool_calls=total_calls,
            folds_performed=total_folds,
        )


# ---------------------------------------------------------------------------
# Tool-aware OpenAI client
# ---------------------------------------------------------------------------


class ToolAwareOpenAIClient:
    """Wraps an InstrumentedOpenAIClient with multi-turn tool execution."""

    def __init__(
        self,
        client,  # InstrumentedOpenAIClient
        executor: ToolExecutor,
        max_turns: int = MAX_TOOL_TURNS,
        on_tool_call: Callable[[ToolCall], None] | None = None,
        on_tool_result: Callable[[ToolResult], None] | None = None,
        should_continue: Callable[[int, list[ToolResult]], str] | None = None,
        fold_engine=None,
        context_budget: int = 100_000,
    ) -> None:
        self._client = client
        self._executor = executor
        self._max_turns = max_turns
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._should_continue = should_continue
        self._fold_engine = fold_engine
        self._context_budget = context_budget

    @property
    def model(self) -> str:
        return self._client.model

    @property
    def executor(self) -> ToolExecutor:
        return self._executor

    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> str:
        result = self.complete_with_tools(system_prompt, messages, max_tokens)
        return result.text

    def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> CompletionResult:
        self._client._ensure_client()

        # Capture agent_id once at call start for thread safety.
        agent_id = (
            self._client._collector.get_current_agent()
            if self._client._collector
            else ""
        )

        tool_schemas = tools_to_openai_schema(self._executor.tools)
        conversation = [{"role": "system", "content": system_prompt}] + list(messages)
        tool_turns: list[ToolTurnRecord] = []
        total_calls = 0
        total_folds = 0
        force_text = False

        for _turn in range(self._max_turns):
            # Check with caller whether to continue exploring
            if _turn > 0 and self._should_continue:
                last_results = tool_turns[-1].results if tool_turns else []
                decision = self._should_continue(_turn, last_results)
                if decision == "stop":
                    break
                elif decision == "finish":
                    force_text = True

            # Auto-fold if context is getting large
            if self._fold_engine:
                conversation, folds = _fold_conversation(
                    conversation, self._context_budget, self._fold_engine,
                )
                total_folds += folds

            # Withhold tools to force text on last turn or user "finish"
            is_last_turn = force_text or _turn == self._max_turns - 1

            import time

            start = time.perf_counter()
            kwargs: dict[str, Any] = {
                "model": self._client.model,
                "max_tokens": max_tokens,
                "messages": conversation,
            }
            if tool_schemas and not is_last_turn:
                kwargs["tools"] = tool_schemas
            response = self._client._client.chat.completions.create(**kwargs)
            latency_ms = (time.perf_counter() - start) * 1000

            if self._client._collector:
                self._client._collector.record_call(
                    agent_id,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    latency_ms,
                    self._client.model,
                )

            choice = response.choices[0]
            tool_calls_raw = choice.message.tool_calls

            if not tool_calls_raw:
                return CompletionResult(
                    text=choice.message.content or "",
                    tool_turns=tool_turns,
                    total_tool_calls=total_calls,
                    folds_performed=total_folds,
                )

            # Execute tool calls
            calls: list[ToolCall] = []
            results: list[ToolResult] = []

            # Append assistant message first (OpenAI requires it).
            # Convert to dict to keep conversation homogeneous.
            asst_msg = {
                "role": "assistant",
                "content": choice.message.content or "",
            }
            if tool_calls_raw:
                asst_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls_raw
                ]
            conversation.append(asst_msg)

            for raw_call in tool_calls_raw:
                try:
                    args = json.loads(raw_call.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}

                tc = ToolCall(
                    id=raw_call.id,
                    name=raw_call.function.name,
                    arguments=args,
                )
                calls.append(tc)
                total_calls += 1

                if self._on_tool_call:
                    self._on_tool_call(tc)

                tr = self._executor.execute(tc)
                results.append(tr)

                if self._on_tool_result:
                    self._on_tool_result(tr)

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tr.output,
                })

            tool_turns.append(ToolTurnRecord(calls=calls, results=results))

        # Max turns exhausted — extract any text from the last response
        fallback = (choice.message.content or "").strip() if choice else ""
        if not fallback:
            fallback = (
                "(max tool turns reached — agent used all tool turns "
                "without producing a final text response)"
            )
        return CompletionResult(
            text=fallback,
            tool_turns=tool_turns,
            total_tool_calls=total_calls,
            folds_performed=total_folds,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_tool_aware_client(
    client,
    executor: ToolExecutor,
    on_tool_call: Callable[[ToolCall], None] | None = None,
    on_tool_result: Callable[[ToolResult], None] | None = None,
    should_continue: Callable[[int, list[ToolResult]], str] | None = None,
    fold_engine=None,
    context_budget: int = 100_000,
):
    """Create the appropriate ToolAware client based on the underlying client type.

    Auto-detects whether the client is Anthropic or OpenAI based on class name.
    If ``fold_engine`` is provided, enables auto-fold context compression
    when the conversation exceeds ``context_budget`` tokens.

    The ``should_continue`` callback is called between tool turns with
    (turn_number, last_results) and should return ``"continue"``,
    ``"finish"`` (one more turn without tools), or ``"stop"``.
    """
    from clients import InstrumentedClaudeClient, InstrumentedOpenAIClient

    if isinstance(client, InstrumentedClaudeClient):
        return ToolAwareClaudeClient(
            client, executor,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            should_continue=should_continue,
            fold_engine=fold_engine,
            context_budget=context_budget,
        )
    elif isinstance(client, InstrumentedOpenAIClient):
        return ToolAwareOpenAIClient(
            client, executor,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            should_continue=should_continue,
            fold_engine=fold_engine,
            context_budget=context_budget,
        )
    else:
        raise TypeError(f"Unknown client type: {type(client)}")
