"""Cost-aware agent runner with per-agent log capture.

Includes:
- ``AgentLog``: captured output for a single agent execution
- ``CostAwareRunner``: wraps any runner with accounting
- ``LoggingEchoRunner``: echo mode with log capture
- ``ToolAwareCostRunner``: wraps a tool-aware runner with accounting + logs
- ``ToolAwareEchoRunner``: echo mode that simulates tool calls for UI testing

Each runner captures SAG wire-format transcripts in the AgentLog for
post-execution inspection and serialization.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.accounting import AccountingCollector
from sag.grove import LLMAgentRunner
from sag.minifier import MessageMinifier
from sag.model import Header, KnowledgeStatement, Message
from sag.tools import ToolCall, ToolResult
from sag.tree import AgentNode


def _build_sag_wire(node: AgentNode, facts: dict[str, str]) -> str:
    """Build a SAG wire-format message from an agent's output facts."""
    stmts = [
        KnowledgeStatement(topic=t, value=v, version=1)
        for t, v in sorted(facts.items())
    ]
    parent_id = node.parent.agent_id if node.parent else "root"
    header = Header(
        version=1,
        message_id=f"{node.agent_id}-out",
        source=node.agent_id,
        destination=parent_id,
        timestamp=0,
    )
    msg = Message(header=header, statements=stmts)
    return MessageMinifier.to_minified_string(msg)


@dataclass
class AgentLog:
    """Captured output for a single agent execution."""

    agent_id: str
    role: str
    facts: dict[str, str] = field(default_factory=dict)
    sag_transcript: list[str] = field(default_factory=list)  # SAG wire messages
    rating: int | None = None  # 1-5 user rating (RLHF)
    feedback: str = ""  # User redirect/feedback text


class CostAwareRunner:
    """Wraps any runner, setting the current agent_id on the collector
    before each call so instrumented clients record metrics correctly.
    Also captures per-agent logs for later inspection.
    """

    def __init__(
        self, inner: LLMAgentRunner, collector: AccountingCollector
    ) -> None:
        self._inner = inner
        self._collector = collector
        self.logs: dict[str, AgentLog] = {}
        self._lock = threading.Lock()

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        self._collector.set_current_agent(node.agent_id)
        facts = self._inner.run(node, task, child_facts)
        wire = _build_sag_wire(node, facts)
        with self._lock:
            self.logs[node.agent_id] = AgentLog(
                agent_id=node.agent_id,
                role=node.role,
                facts=dict(facts),
                sag_transcript=[wire],
            )
        return facts


class LoggingEchoRunner:
    """Echo runner that also captures per-agent logs."""

    def __init__(self) -> None:
        self.logs: dict[str, AgentLog] = {}
        self._lock = threading.Lock()

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        import time
        from sag.grove import EchoAgentRunner

        # Small delay so the live display can show "running" state
        time.sleep(0.15)

        facts = EchoAgentRunner().run(node, task, child_facts)
        wire = _build_sag_wire(node, facts)
        with self._lock:
            self.logs[node.agent_id] = AgentLog(
                agent_id=node.agent_id,
                role=node.role,
                facts=dict(facts),
                sag_transcript=[wire],
            )
        return facts


class ToolAwareCostRunner:
    """Wraps a ToolAwareLLMAgentRunner with accounting and log capture.

    Same interface as ``CostAwareRunner`` but for tool-aware runners.
    """

    def __init__(self, inner, collector: AccountingCollector) -> None:
        self._inner = inner
        self._collector = collector
        self.logs: dict[str, AgentLog] = {}
        self._lock = threading.Lock()

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        self._collector.set_current_agent(node.agent_id)
        facts = self._inner.run(node, task, child_facts)
        wire = _build_sag_wire(node, facts)
        with self._lock:
            self.logs[node.agent_id] = AgentLog(
                agent_id=node.agent_id,
                role=node.role,
                facts=dict(facts),
                sag_transcript=[wire],
            )
        return facts


class ToolAwareEchoRunner:
    """Echo runner that simulates tool calls for UI testing.

    In addition to producing echo facts, simulates a list_directory(".")
    tool call so the UI can show tool-use activity.
    """

    def __init__(
        self,
        on_tool_call=None,
        on_tool_result=None,
    ) -> None:
        self.logs: dict[str, AgentLog] = {}
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._tool_calls_count: dict[str, int] = {}
        self._lock = threading.Lock()

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        import time
        from sag.grove import EchoAgentRunner

        # Small delay so the live display can show "running" state
        time.sleep(0.15)

        # Simulate a tool call for UI purposes
        sim_call = ToolCall(
            id=f"echo_{node.agent_id}_1",
            name="list_directory",
            arguments={"path": "."},
        )
        sim_result = ToolResult(
            call_id=sim_call.id,
            tool_name="list_directory",
            output="(simulated) README.md  src/  tests/  setup.py",
        )

        if self._on_tool_call:
            self._on_tool_call(sim_call)
        if self._on_tool_result:
            self._on_tool_result(sim_result)

        with self._lock:
            self._tool_calls_count[node.agent_id] = 1

        # Normal echo execution
        facts = EchoAgentRunner().run(node, task, child_facts)
        wire = _build_sag_wire(node, facts)
        with self._lock:
            self.logs[node.agent_id] = AgentLog(
                agent_id=node.agent_id,
                role=node.role,
                facts=dict(facts),
                sag_transcript=[wire],
            )
        return facts
