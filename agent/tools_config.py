"""Phase-specific tool executor factories.

Each phase of the SAG agent gets a different set of tools and safety
policies:

- **Pre-analysis** (Phase 0): read-only + shell, no writes
- **Grove agents** (Phase 1): browse-only (no shell, no writes)
- **Code generation** (Phase 2): all tools, writes restricted to output_dir
- **Chat**: all tools, writes restricted to output_dir, shell needs confirmation
- **launch_grove** tool: closure-based tool for spawning sub-groves from chat
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.accounting import AccountingCollector
from sag.fold import FoldEngine
from sag.grove import AgentRunner, Grove
from sag.tools import (
    ALL_TOOLS,
    BROWSE_ONLY_TOOLS,
    READ_ONLY_TOOLS,
    DefaultSafetyPolicy,
    Tool,
    ToolExecutor,
    ToolParam,
)
from sag.tree import TreeEngine


def build_preanalysis_executor(
    confirm_callback: Callable[[str], bool] | None = None,
) -> ToolExecutor:
    """Phase 0: Read-only tools for exploring the project before team design.

    Includes shell (for `ls`, `find`, `cat`, etc.) but no writes.
    """
    policy = DefaultSafetyPolicy(
        allowed_tools={t.name for t in READ_ONLY_TOOLS},
        shell_confirmation=False,
    )
    return ToolExecutor(READ_ONLY_TOOLS, policy, confirm_callback)


def build_grove_executor() -> ToolExecutor:
    """Phase 1: Browse-only tools for grove agents.

    No shell, no writes — agents can only read files and fetch URLs.
    """
    policy = DefaultSafetyPolicy(
        allowed_tools={t.name for t in BROWSE_ONLY_TOOLS},
    )
    return ToolExecutor(BROWSE_ONLY_TOOLS, policy)


def build_codegen_executor(
    output_dir: str,
    confirm_callback: Callable[[str], bool] | None = None,
) -> ToolExecutor:
    """Phase 2: All tools for code generation.

    Writes restricted to the output directory. Shell commands allowed
    without confirmation (for running tests, linters, etc.).
    """
    policy = DefaultSafetyPolicy(
        writable_dirs=[os.path.abspath(output_dir)],
        shell_confirmation=False,
    )
    return ToolExecutor(ALL_TOOLS, policy, confirm_callback)


def build_chat_executor(
    output_dir: str | None = None,
    confirm_callback: Callable[[str], bool] | None = None,
) -> ToolExecutor:
    """Chat mode: All tools with shell confirmation required.

    Writes restricted to output_dir if provided.
    """
    writable = [os.path.abspath(output_dir)] if output_dir else None
    policy = DefaultSafetyPolicy(
        writable_dirs=writable,
        shell_confirmation=True,
    )
    return ToolExecutor(ALL_TOOLS, policy, confirm_callback)


def build_launch_grove_tool(
    client: Any,
    collector: AccountingCollector,
    fold_engine: FoldEngine,
    runner_factory: Callable[[], AgentRunner],
    parent_tree: Optional[TreeEngine] = None,
    ui_callbacks: Optional[dict[str, Any]] = None,
) -> Tool:
    """Build a ``launch_grove`` tool whose handler is a closure.

    The returned Tool can be added to a chat ToolExecutor via ``add_tool()``.
    Sub-grove agents use the grove executor (browse-only, no ``launch_grove``
    tool), so sub-groves cannot spawn further sub-groves.

    Parameters
    ----------
    client : LLMClient
        LLM client for TaskAnalyzer + runners.
    collector : AccountingCollector
        Shared accounting collector for cost tracking.
    fold_engine : FoldEngine
        Fold engine for context compression.
    runner_factory : callable
        Returns a fresh AgentRunner for each sub-grove invocation.
    parent_tree : TreeEngine, optional
        If provided, discovered facts are asserted into the root node's
        knowledge under ``grove.<id>.<topic>``.
    ui_callbacks : dict, optional
        Keys: ``on_agent_start``, ``on_agent_done``, ``on_propagate``.
    """
    from analyzer import TaskAnalyzer, build_tree_from_proposal

    cbs = ui_callbacks or {}

    def _handle_launch_grove(
        executor: ToolExecutor, task: str, template: str = "",
    ) -> str:
        grove_id = uuid.uuid4().hex[:8]
        prev_agent = collector.current_agent
        collector.set_current_agent(f"grove:{grove_id}")

        try:
            # 1. Propose agent team
            analyzer = TaskAnalyzer(client=client)
            proposal = analyzer.propose(task, context=template)
            tree = build_tree_from_proposal(proposal)
            agent_count = len(tree.get_all_node_ids())

            # 2. Execute grove
            runner = runner_factory()
            grove = Grove(
                tree, runner,
                on_agent_start=cbs.get("on_agent_start"),
                on_agent_done=cbs.get("on_agent_done"),
                on_propagate=cbs.get("on_propagate"),
            )
            result = grove.execute(task)

            # 3. Collect discovered facts
            facts: dict[str, str] = {}
            for topic, (value, _ver) in result.facts.items():
                facts[topic] = str(value)

            # 4. Assert facts into parent tree's root knowledge
            if parent_tree is not None:
                try:
                    root = parent_tree.get_root()
                    for topic, value in facts.items():
                        root.knowledge.assert_fact(f"grove.{grove_id}.{topic}", value)
                except ValueError:
                    pass  # no root node

            # 5. Format response as SAG wire
            from sag.minifier import MessageMinifier
            from sag.model import Header, KnowledgeStatement, Message

            stmts = [
                KnowledgeStatement(topic=t, value=v, version=1)
                for t, v in sorted(facts.items())
            ]
            header = Header(
                version=1,
                message_id=f"grove-{grove_id}",
                source=f"grove:{grove_id}",
                destination="chat",
                timestamp=0,
            )
            msg = Message(header=header, statements=stmts)
            return MessageMinifier.to_minified_string(msg)

        finally:
            collector.set_current_agent(prev_agent or "chat")

    return Tool(
        name="launch_grove",
        description=(
            "Launch a sub-grove of specialized agents to analyze a complex sub-task. "
            "Use this when a question requires deep investigation by multiple specialists "
            "(e.g. architecture review, chaos engineering analysis, security audit). "
            "Returns discovered facts from the agent team."
        ),
        parameters=[
            ToolParam("task", "string", "Description of the sub-task for the agent team to analyze"),
            ToolParam(
                "template", "string",
                "Optional hint for team template (e.g. 'chaos', 'data', 'software')",
                required=False, default="",
            ),
        ],
        handler=_handle_launch_grove,
    )
