"""Grove orchestrator — runs a tree of agents bottom-up.

All inter-agent communication uses proper SAG messages with headers,
correlation IDs, and KNOW statements. The message log captures the
full wire-format history of the execution.

Includes:
- ``Grove``: one-shot bottom-up execution
- ``InteractiveGrove``: step-by-step execution with checkpointing
- ``ChatSession``: conversational loop with the root agent
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from sag.checkpoint import CheckpointManager
from sag.exceptions import SAGParseException
from sag.model import AssertStatement, KnowledgeStatement, Message
from sag.parser import SAGMessageParser
from sag.prompt import LLMClient, PromptBuilder
from sag.tree import AgentNode, TreeEngine


# ---------------------------------------------------------------------------
# Agent runner protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentRunner(Protocol):
    """Interface for running an agent. Swap in LLM, echo, or custom logic."""

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]: ...


# ---------------------------------------------------------------------------
# LLM-backed runner
# ---------------------------------------------------------------------------

_ASSERT_RE = re.compile(r'A\s+([\w.]+)\s*=\s*"([^"]*)"')


class LLMAgentRunner:
    """Runs agents via an LLM client (Claude/OpenAI)."""

    def __init__(self, client: LLMClient, max_tokens: int = 512) -> None:
        self._client = client
        self._max_tokens = max_tokens

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        system_prompt = self._build_system_prompt(node)
        user_content = self._build_user_message(task, child_facts)

        messages = [{"role": "user", "content": user_content}]
        raw = self._client.complete(system_prompt, messages, self._max_tokens)

        facts = self._parse_facts(raw, node)

        # Assert facts into the node's knowledge engine
        for topic, value in facts.items():
            node.knowledge.assert_fact(topic, value)

        return facts

    def _build_system_prompt(self, node: AgentNode) -> str:
        role_prompt = node.metadata.get("prompt", f"You are a {node.role}.")
        topics = node.metadata.get("topics", [])

        builder = (
            PromptBuilder()
            .set_preamble(role_prompt)
            .include_grammar(False)
            .include_default_examples(False)
            .include_quick_reference(False)
        )

        topic_instruction = ""
        if topics:
            topic_list = ", ".join(topics)
            topic_instruction = (
                f"\n\nYou MUST output your findings as SAG ASSERT statements. "
                f"Use these topics: {topic_list}\n"
                f'Format: A topic.name = "your analysis"\n'
                f"Example: A {topics[0]} = \"your finding here\""
            )
        else:
            topic_instruction = (
                "\n\nOutput your findings as SAG ASSERT statements.\n"
                'Format: A topic.name = "your analysis"'
            )

        builder.set_suffix(topic_instruction)
        return builder.build()

    def _build_user_message(
        self, task: str, child_facts: dict[str, str]
    ) -> str:
        parts = [f"Task: {task}"]
        if child_facts:
            parts.append("\nInput from specialist agents:")
            for topic, value in child_facts.items():
                parts.append(f"  - {topic}: {value}")
        return "\n".join(parts)

    def _parse_facts(self, raw: str, node: AgentNode) -> dict[str, str]:
        """Parse LLM response to extract assert facts.

        Strategy:
        1. Try SAGMessageParser with synthetic header
        2. Regex fallback for A topic = "value" patterns
        3. Last resort: wrap entire response as {role}.analysis
        """
        facts: dict[str, str] = {}

        # Strategy 1: full SAG parse with synthetic header
        try:
            header = f"H v 1 id={node.agent_id}-out src={node.agent_id} dst=parent ts={int(time.time())}"
            full_text = f"{header}\n{raw}"
            msg = SAGMessageParser.parse(full_text)
            for stmt in msg.statements:
                if isinstance(stmt, AssertStatement):
                    facts[stmt.path] = str(stmt.value)
            if facts:
                return facts
        except SAGParseException:
            pass

        # Strategy 2: regex fallback
        for match in _ASSERT_RE.finditer(raw):
            facts[match.group(1)] = match.group(2)
        if facts:
            return facts

        # Strategy 3: wrap entire response
        role_key = node.role.lower().replace(" ", "_")
        facts[f"{role_key}.analysis"] = raw.strip()
        return facts


# ---------------------------------------------------------------------------
# Echo runner (no API)
# ---------------------------------------------------------------------------


class EchoAgentRunner:
    """No-API fallback. Generates placeholder facts from metadata."""

    def run(
        self, node: AgentNode, task: str, child_facts: dict[str, str]
    ) -> dict[str, str]:
        topics = node.metadata.get("topics", [])
        facts: dict[str, str] = {}

        if topics:
            for topic in topics:
                facts[topic] = f"[{node.role}] Analysis for {topic} on: {task}"
        else:
            role_key = node.role.lower().replace(" ", "_")
            facts[f"{role_key}.analysis"] = (
                f"[{node.role}] Synthesized analysis on: {task}"
            )

        # Assert into knowledge engine
        for topic, value in facts.items():
            node.knowledge.assert_fact(topic, value)

        return facts


# ---------------------------------------------------------------------------
# Grove result
# ---------------------------------------------------------------------------


@dataclass
class GroveResult:
    """Result of a grove execution."""

    facts: dict[str, tuple[Any, int]] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    report: str = ""
    agents_run: int = 0
    levels_processed: int = 0


# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------

OnAgentStart = Callable[[AgentNode, str], None]
OnAgentDone = Callable[[AgentNode, dict[str, str]], None]
OnPropagate = Callable[[AgentNode, AgentNode, Message], None]


# ---------------------------------------------------------------------------
# Grove orchestrator
# ---------------------------------------------------------------------------


class Grove:
    """Orchestrates a tree of agents processing a task bottom-up.

    All inter-agent communication is via SAG messages:
    - When a child propagates knowledge to its parent, a proper SAG
      Message is built with a header (using CorrelationEngine) and
      KNOW statements for each fact.
    - The parent records the incoming message for correlation tracking.
    - The full message log is captured in GroveResult.
    """

    def __init__(
        self,
        tree: TreeEngine,
        runner: AgentRunner,
        on_agent_start: Optional[OnAgentStart] = None,
        on_agent_done: Optional[OnAgentDone] = None,
        on_propagate: Optional[OnPropagate] = None,
    ) -> None:
        self._tree = tree
        self._runner = runner
        self._on_agent_start = on_agent_start
        self._on_agent_done = on_agent_done
        self._on_propagate = on_propagate

    def execute(self, task: str) -> GroveResult:
        """Execute the grove on a task, processing bottom-up."""
        self._tree.setup_subscriptions("**")
        levels = self._tree.get_levels_bottom_up()
        message_log: list[Message] = []

        agents_run = 0

        for level in levels:
            for node in level:
                # Gather child facts for this node
                child_facts: dict[str, str] = {}
                for child in node.children:
                    for topic, (value, _ver) in child.knowledge.get_all_facts().items():
                        child_facts[topic] = str(value)

                if self._on_agent_start:
                    self._on_agent_start(node, task)

                # Run the agent
                facts = self._runner.run(node, task, child_facts)
                agents_run += 1

                if self._on_agent_done:
                    self._on_agent_done(node, facts)

                # Propagate knowledge up via SAG message
                if node.parent is not None:
                    applied = self._tree.propagate_up(node.agent_id)
                    if applied:
                        msg = _build_propagation_message(node, node.parent, applied)
                        message_log.append(msg)
                        # Parent records incoming for correlation
                        node.parent.correlation.record_incoming(msg)
                        if self._on_propagate:
                            self._on_propagate(node, node.parent, msg)

        # Build result from root
        root = self._tree.get_root()
        root_facts = root.knowledge.get_all_facts()

        report = self._build_report(root_facts, message_log)

        return GroveResult(
            facts=root_facts,
            messages=message_log,
            report=report,
            agents_run=agents_run,
            levels_processed=len(levels),
        )

    def _build_report(
        self,
        facts: dict[str, tuple[Any, int]],
        messages: list[Message],
    ) -> str:
        lines = ["Grove Execution Report", "=" * 40]
        lines.append(f"  Messages exchanged: {len(messages)}")
        lines.append("")
        for topic, (value, _version) in sorted(facts.items()):
            lines.append(f"  {topic}: {value}")
        lines.append("=" * 40)
        return "\n".join(lines)


def _build_propagation_message(
    child: AgentNode,
    parent: AgentNode,
    statements: list[KnowledgeStatement],
) -> Message:
    """Build a SAG Message for child-to-parent knowledge propagation."""
    header = child.correlation.create_response_header(
        source=child.agent_id,
        destination=parent.agent_id,
    )
    return Message(header=header, statements=list(statements))


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of processing a single level in the interactive grove."""

    level: int
    total_levels: int
    agents_run: list[str]
    facts_produced: dict[str, dict[str, str]]
    messages: list[Message]
    is_complete: bool


# ---------------------------------------------------------------------------
# Interactive grove
# ---------------------------------------------------------------------------


class InteractiveGrove:
    """Step-by-step grove execution with checkpoint/rollback support.

    Usage::

        ig = InteractiveGrove(tree, runner, checkpoint_mgr)
        ig.setup("Build an API")
        while True:
            step = ig.step()
            # inspect, checkpoint, etc.
            if step.is_complete:
                break
        result = ig.result()
    """

    def __init__(
        self,
        tree: TreeEngine,
        runner: AgentRunner,
        checkpoint_mgr: Optional[CheckpointManager] = None,
        on_agent_start: Optional[OnAgentStart] = None,
        on_agent_done: Optional[OnAgentDone] = None,
        on_propagate: Optional[OnPropagate] = None,
    ) -> None:
        self._tree = tree
        self._runner = runner
        self._checkpoint_mgr = checkpoint_mgr
        self._on_agent_start = on_agent_start
        self._on_agent_done = on_agent_done
        self._on_propagate = on_propagate

        self._task: str = ""
        self._levels: list[list[AgentNode]] = []
        self._current_level: int = 0
        self._agents_run: int = 0
        self._message_log: list[Message] = []
        self._setup_done: bool = False

    def setup(self, task: str) -> list[list[AgentNode]]:
        """Prepare subscriptions and compute levels. Must be called first."""
        self._task = task
        self._tree.setup_subscriptions("**")
        self._levels = self._tree.get_levels_bottom_up()
        self._current_level = 0
        self._agents_run = 0
        self._message_log = []
        self._setup_done = True
        return self._levels

    def step(self) -> StepResult:
        """Process the next level of agents. Raises if not set up or already complete."""
        if not self._setup_done:
            raise RuntimeError("Must call setup() before step()")
        if self._current_level >= len(self._levels):
            raise RuntimeError("Execution already complete")

        level = self._levels[self._current_level]
        agents_run_ids: list[str] = []
        facts_produced: dict[str, dict[str, str]] = {}
        step_messages: list[Message] = []

        for node in level:
            child_facts: dict[str, str] = {}
            for child in node.children:
                for topic, (value, _ver) in child.knowledge.get_all_facts().items():
                    child_facts[topic] = str(value)

            if self._on_agent_start:
                self._on_agent_start(node, self._task)

            facts = self._runner.run(node, self._task, child_facts)
            self._agents_run += 1
            agents_run_ids.append(node.agent_id)
            facts_produced[node.agent_id] = facts

            if self._on_agent_done:
                self._on_agent_done(node, facts)

            if node.parent is not None:
                applied = self._tree.propagate_up(node.agent_id)
                if applied:
                    msg = _build_propagation_message(node, node.parent, applied)
                    self._message_log.append(msg)
                    step_messages.append(msg)
                    node.parent.correlation.record_incoming(msg)
                    if self._on_propagate:
                        self._on_propagate(node, node.parent, msg)

        self._current_level += 1
        is_complete = self._current_level >= len(self._levels)

        return StepResult(
            level=self._current_level - 1,
            total_levels=len(self._levels),
            agents_run=agents_run_ids,
            facts_produced=facts_produced,
            messages=step_messages,
            is_complete=is_complete,
        )

    def complete(self) -> GroveResult:
        """Run all remaining levels and return a GroveResult."""
        if not self._setup_done:
            raise RuntimeError("Must call setup() before complete()")
        while self._current_level < len(self._levels):
            self.step()
        return self.result()

    def result(self) -> GroveResult:
        """Build and return a GroveResult from current state."""
        root = self._tree.get_root()
        root_facts = root.knowledge.get_all_facts()
        lines = ["Grove Execution Report", "=" * 40]
        lines.append(f"  Messages exchanged: {len(self._message_log)}")
        lines.append("")
        for topic, (value, _version) in sorted(root_facts.items()):
            lines.append(f"  {topic}: {value}")
        lines.append("=" * 40)
        return GroveResult(
            facts=root_facts,
            messages=self._message_log,
            report="\n".join(lines),
            agents_run=self._agents_run,
            levels_processed=self._current_level,
        )

    # -- State inspection --

    def inspect_node(self, agent_id: str) -> dict[str, tuple[Any, int]]:
        """Return all facts for a given node."""
        node = self._tree.get_node(agent_id)
        if node is None:
            raise KeyError(f"Node '{agent_id}' not found")
        return node.knowledge.get_all_facts()

    def edit_fact(self, agent_id: str, topic: str, value: Any) -> None:
        """Manually set a fact on a node (for mid-run intervention)."""
        node = self._tree.get_node(agent_id)
        if node is None:
            raise KeyError(f"Node '{agent_id}' not found")
        node.knowledge.assert_fact(topic, value)

    # -- Checkpointing --

    def checkpoint(self) -> str:
        """Save current state and return checkpoint_id."""
        if self._checkpoint_mgr is None:
            raise RuntimeError("No CheckpointManager configured")
        meta = self._checkpoint_mgr.save(
            self._tree,
            self._task,
            self._message_log,
            self._agents_run,
            self._current_level,
            len(self._levels),
        )
        return meta.checkpoint_id

    def rollback(self, checkpoint_id: str) -> None:
        """Restore grove state from a checkpoint."""
        if self._checkpoint_mgr is None:
            raise RuntimeError("No CheckpointManager configured")
        meta = self._checkpoint_mgr.load(checkpoint_id)
        self._checkpoint_mgr.restore(meta, self._tree)
        self._current_level = meta.current_level
        self._agents_run = meta.agents_run
        # Restore message log by reparsing wire messages
        self._message_log = []
        for wire in meta.messages:
            try:
                self._message_log.append(SAGMessageParser.parse(wire))
            except SAGParseException:
                pass

    def list_checkpoints(self) -> list:
        """List available checkpoints."""
        if self._checkpoint_mgr is None:
            return []
        return self._checkpoint_mgr.list_checkpoints()


# ---------------------------------------------------------------------------
# Chat session
# ---------------------------------------------------------------------------


@dataclass
class ChatResponse:
    """Response from a chat interaction with the root agent."""

    reply: str
    facts_updated: dict[str, str]
    message: Optional[Message] = None


_KNOW_RE = re.compile(r'KNOW\s+([\w.*]+)\s*=\s*"([^"]*)"')


class ChatSession:
    """Conversational loop with the root agent after an initial grove run.

    Usage::

        session = ChatSession(grove_result, tree, runner)
        resp = session.chat("Can you improve the API design?")
        print(resp.reply)
        print(resp.facts_updated)
    """

    def __init__(
        self,
        grove_result: GroveResult,
        tree: TreeEngine,
        runner: AgentRunner,
        checkpoint_mgr: Optional[CheckpointManager] = None,
    ) -> None:
        self._tree = tree
        self._runner = runner
        self._checkpoint_mgr = checkpoint_mgr
        self._grove_result = grove_result
        self._history: list[tuple[str, str]] = []

    def chat(self, user_message: str) -> ChatResponse:
        """Send a message to the root agent and process the response."""
        root = self._tree.get_root()

        # Build context from root's current knowledge
        current_facts: dict[str, str] = {}
        for topic, (value, _ver) in root.knowledge.get_all_facts().items():
            current_facts[topic] = str(value)

        # Include feedback as a special child_fact
        feedback_facts = dict(current_facts)
        feedback_facts["user.feedback"] = user_message

        # Include history context
        if self._history:
            history_lines = []
            for user_msg, agent_reply in self._history[-3:]:
                history_lines.append(f"User: {user_msg}")
                history_lines.append(f"Agent: {agent_reply}")
            feedback_facts["chat.history"] = "\n".join(history_lines)

        # Run root agent with feedback
        facts = self._runner.run(root, user_message, feedback_facts)

        # Extract KNOW statements from facts to detect updates
        facts_updated: dict[str, str] = {}
        for topic, value in facts.items():
            facts_updated[topic] = str(value)

        # Build a propagation message if facts were produced
        message: Optional[Message] = None
        if facts_updated:
            stmts = [
                KnowledgeStatement(topic=t, value=v, version=root.knowledge.get_local_version())
                for t, v in facts_updated.items()
            ]
            header = root.correlation.create_response_header(
                source=root.agent_id, destination="user"
            )
            message = Message(header=header, statements=stmts)

        # Build a reply string
        reply_parts = []
        for topic, value in facts_updated.items():
            reply_parts.append(f"{topic}: {value}")
        reply = "\n".join(reply_parts) if reply_parts else "(no facts produced)"

        self._history.append((user_message, reply))

        return ChatResponse(
            reply=reply,
            facts_updated=facts_updated,
            message=message,
        )

    def checkpoint(self) -> str:
        """Save current state."""
        if self._checkpoint_mgr is None:
            raise RuntimeError("No CheckpointManager configured")
        meta = self._checkpoint_mgr.save(
            self._tree,
            "chat-session",
            self._grove_result.messages,
            self._grove_result.agents_run,
            self._grove_result.levels_processed,
            self._grove_result.levels_processed,
        )
        return meta.checkpoint_id

    def rollback(self, checkpoint_id: str) -> None:
        """Restore grove state from a checkpoint."""
        if self._checkpoint_mgr is None:
            raise RuntimeError("No CheckpointManager configured")
        meta = self._checkpoint_mgr.load(checkpoint_id)
        self._checkpoint_mgr.restore(meta, self._tree)
        self._history.clear()
