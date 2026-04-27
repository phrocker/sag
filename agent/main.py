#!/usr/bin/env python3
"""Agent Grove — interactive multi-agent tree with cost accounting.

Flow:
  0. Pre-analysis: tools explore the filesystem to ground the task
  1. User describes a task
  2. Analyzer proposes an agent team (LLM-designed or template-based)
  3. User confirms the proposed tree
  4. Agents execute with live status display (optionally using tools)
  5. User explores results: /logs, /cost, /rate, /feedback, or chats with root
  6. Phase 2: optionally generate a full working project from analysis facts

Usage:
    python agent/main.py --api-key $KEY
    python agent/main.py --no-api
    python agent/main.py --no-api "Build a REST API"    # skip task prompt
    python agent/main.py --no-tools "Build a REST API"  # disable tool use
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.accounting import AccountingCollector, PRICING_TIERS
from sag.file_state import FileStateTracker
from sag.fold import FoldEngine
from sag.grove import ChatSession, Grove, LLMAgentRunner, ToolAwareLLMAgentRunner
from sag.knowledge import KnowledgeEngine
from sag.minifier import MessageMinifier

from analyzer import TaskAnalyzer, build_tree_from_proposal, extract_project_dir
from codegen import (
    ClarificationAgent,
    CodeGenExecutor,
    CodeGenPlanner,
    CodeGenResult,
    EditAgent,
    ProjectRunner,
    TestResult,
    TestResultParser,
)
from runner import (
    CostAwareRunner,
    LoggingEchoRunner,
    ToolAwareCostRunner,
    ToolAwareEchoRunner,
)
from clients import InstrumentedClaudeClient, InstrumentedOpenAIClient
from tool_client import make_tool_aware_client
from tools_config import (
    build_chat_executor,
    build_codegen_executor,
    build_grove_executor,
    build_launch_grove_tool,
    build_preanalysis_executor,
)
from session import SessionManager
from ui import AgentUI


PROVIDER_DEFAULTS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

ENV_KEY_NAMES = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


_CHAT_SYSTEM_PROMPT = """\
You are a hands-on coding assistant running LOCALLY on the user's machine. \
You have REAL access to the local filesystem via tools. A multi-agent team \
has analyzed a task and generated code.

CRITICAL RULES — read carefully:
- You are NOT a cloud AI without filesystem access. You are a local agent \
  with tools that read, write, search, and execute on the real filesystem.
- NEVER say "I can't access your filesystem" or "I don't have the ability \
  to browse directories". You CAN and you MUST.
- NEVER give generic advice when you can look at the actual code instead.
- When the user mentions a path, directory, or project — USE YOUR TOOLS \
  to inspect it immediately. Do not ask the user to share details you can \
  look up yourself.

## Filesystem Tools
When the user asks about files, code, or any project:
1. Use list_directory to see what exists
2. Use read_file to show actual file contents
3. Use search_files to find specific patterns
4. Use run_shell when you need commands like `find`, `git`, `wc`, etc.
5. Quote actual code in your responses

When the user asks you to modify code:
1. Use read_file to see the current state
2. Use patch_file to make targeted changes
3. Use read_file again to verify the result

## launch_grove — Sub-Team Execution
You have a special tool called `launch_grove` that spawns a full multi-agent \
team to investigate a complex sub-task. Use it when:
- The question requires deep analysis across multiple concerns (architecture, \
  security, performance, reliability, etc.)
- A single-tool investigation is insufficient — the task benefits from \
  parallel specialist agents (e.g. chaos engineering, security audit, \
  codebase review)
- The user explicitly asks to "run agents", "analyze", or "investigate" \
  something complex

Call it like: launch_grove(task="<detailed description of what to investigate>")

Optionally pass template="chaos" | "software" | "data" to hint at the team shape.

The tool returns discovered facts from the agent team. Summarize the key \
findings for the user and offer to drill deeper into any area.

Be specific and concrete. Show real file paths, real code, real line numbers. \
Never say "the project seems to..." — look and report what's actually there.

# Task
{task}

# Output Directory
{output_dir}

# Generated Files
{file_list}

# Analysis Facts
{facts}
"""

_CHAT_SYSTEM_PROMPT_NO_TOOLS = """\
You are a helpful project assistant. You have access to all the analysis facts \
and design decisions from a multi-agent planning session.

Answer the user's questions conversationally using the facts below as context. \
Be concise and direct. If you don't know something, say so.

# Task
{task}

# Analysis Facts
{facts}
"""


# -- Conversational input detection (no API call) --

_TASK_KEYWORDS = re.compile(
    r'\b(build|create|implement|develop|make|write|add|fix|debug|'
    r'refactor|test|deploy|analyze|review|design|set\s+up|'
    r'generate|migrate|optimize|configure|integrate|chaos)\b', re.I)

_GREETING_RE = re.compile(
    r'^(hi|hello|hey|howdy|yo|sup|good\s+(morning|afternoon|evening))[\s!?.]*$', re.I)

_CHAT_RE = re.compile(
    r'(who\s+are\s+you|what.?s\s+your\s+name|what\s+are\s+you|'
    r'what\s+(day|time|date)\s+is|how\s+are\s+you|thank)', re.I)


def _is_conversational(text: str) -> bool:
    """Detect whether input is conversational (not a task for the pipeline)."""
    if _TASK_KEYWORDS.search(text):
        return False
    if _GREETING_RE.match(text):
        return True
    if _CHAT_RE.search(text):
        return True
    if len(text.split()) <= 4 and not _TASK_KEYWORDS.search(text):
        return True
    return False


_QUICK_SYSTEM = "You are the Agent Grove. Answer briefly and conversationally."


def _quick_chat(client, collector: AccountingCollector, text: str) -> str:
    """Handle a conversational message with a single LLM call or canned response."""
    if client is not None:
        collector.set_current_agent("quick-chat")
        return client.complete(
            _QUICK_SYSTEM,
            [{"role": "user", "content": text}],
            max_tokens=256,
        )

    # Echo mode: canned responses
    lower = text.lower().strip().rstrip("?!.")
    if _GREETING_RE.match(text):
        return "Hello! I'm the Agent Grove. What would you like to work on?"
    if "your name" in lower or "who are you" in lower or "what are you" in lower:
        return (
            "I'm the Agent Grove — I coordinate multi-agent teams "
            "to analyze and build software projects."
        )
    if "date" in lower or "day" in lower:
        return f"Today is {datetime.date.today().strftime('%A, %B %d, %Y')}."
    if "time" in lower:
        return f"The current time is {datetime.datetime.now().strftime('%H:%M:%S')}."
    if "thank" in lower:
        return "You're welcome!"
    if "how are you" in lower:
        return "I'm doing well, thanks for asking! Ready to help with your next project."
    return "I'm here to help! Describe a task and I'll assemble an agent team for it."


class ConversationalChat:
    """Conversational chat backed by direct LLM calls (not the grove runner)."""

    def __init__(
        self,
        client,
        collector: AccountingCollector,
        task: str,
        facts: dict[str, str],
        output_dir: str = "",
        generated_files: list[str] | None = None,
        has_tools: bool = False,
        session_manager: SessionManager | None = None,
    ) -> None:
        self._client = client
        self._collector = collector
        self._task = task
        self._facts = facts
        self._output_dir = output_dir
        self._generated_files = generated_files or []
        self._has_tools = has_tools
        self._session_mgr = session_manager
        self._history: list[dict[str, str]] = []

    def chat(self, user_message: str) -> str:
        """Send a message and get a conversational response."""
        facts_text = "\n".join(f"  {k} = {v}" for k, v in self._facts.items())

        if self._has_tools:
            file_list = "\n".join(f"  {f}" for f in self._generated_files) if self._generated_files else "  (none yet)"
            system = _CHAT_SYSTEM_PROMPT.format(
                task=self._task,
                output_dir=self._output_dir or "(not set)",
                file_list=file_list,
                facts=facts_text,
            )
        else:
            system = _CHAT_SYSTEM_PROMPT_NO_TOOLS.format(
                task=self._task,
                facts=facts_text,
            )

        self._history.append({"role": "user", "content": user_message})

        # Record turn in session
        if self._session_mgr:
            self._session_mgr.add_conversation_turn("user", user_message)

        # Use folded history from session manager if available, else truncate
        if self._session_mgr and self._session_mgr.data:
            messages = self._session_mgr.get_folded_history()
        else:
            messages = self._history[-6:]

        self._collector.set_current_agent("chat")
        reply = self._client.complete(system, messages, max_tokens=1024)

        self._history.append({"role": "assistant", "content": reply})

        # Record assistant turn in session
        if self._session_mgr:
            self._session_mgr.add_conversation_turn("assistant", reply)

        return reply

    def update_generated_files(self, files: list[str], output_dir: str) -> None:
        """Update the list of generated files (e.g. after a codegen run)."""
        self._generated_files = files
        self._output_dir = output_dir


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Agent Grove — Interactive Multi-Agent Tree"
    )
    parser.add_argument(
        "--provider", choices=["claude", "openai"], default="claude",
        help="LLM provider (default: claude)",
    )
    parser.add_argument("--api-key", help="API key (or set env var)")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument(
        "--no-api", action="store_true", help="Echo mode (no API calls)"
    )
    parser.add_argument(
        "--no-tools", action="store_true",
        help="Disable tool use (agents cannot read files, run commands, etc.)",
    )
    parser.add_argument(
        "--output", choices=["rich", "json"], default="rich",
        help="Output format (default: rich TUI)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for generated code (default: ./output/<task-slug>)",
    )
    parser.add_argument(
        "--resume", default=None, metavar="SESSION_ID",
        help="Resume a previously saved session",
    )
    parser.add_argument(
        "--sessions-dir", default=None,
        help="Directory for session files (default: ~/.sag/sessions)",
    )
    parser.add_argument(
        "task", nargs="?", default=None,
        help="Task description (skips interactive prompt if given)",
    )
    args = parser.parse_args()

    model = args.model or PROVIDER_DEFAULTS[args.provider]
    pricing = PRICING_TIERS.get(model)
    collector = AccountingCollector(pricing)
    ui = AgentUI(collector=collector)

    use_tools = not args.no_tools

    # -- Grove Architect: fold engine and file state tracker --
    fold_engine = FoldEngine()
    grove_knowledge = KnowledgeEngine("grove-root", fold_engine=fold_engine)
    file_tracker = FileStateTracker(grove_knowledge)

    # -- Resolve runner and LLM client --
    echo_mode = args.no_api
    client = None
    runner = None
    tool_client_preanalysis = None
    tool_client_grove = None
    tool_client_codegen = None
    tool_client_chat = None

    if not echo_mode:
        env_key = ENV_KEY_NAMES[args.provider]
        api_key = args.api_key or os.environ.get(env_key)
        if api_key:
            if args.provider == "openai":
                client = InstrumentedOpenAIClient(
                    api_key=api_key, model=model, collector=collector,
                )
            else:
                client = InstrumentedClaudeClient(
                    api_key=api_key, model=model, collector=collector,
                )

            if use_tools:
                # Build tool-aware clients per phase (with auto-fold)
                pre_executor = build_preanalysis_executor(
                    confirm_callback=ui.confirm_shell_command,
                )
                tool_client_preanalysis = make_tool_aware_client(
                    client, pre_executor,
                    on_tool_call=ui.on_tool_call,
                    on_tool_result=ui.on_tool_result,
                    should_continue=ui.should_continue_agent,
                    fold_engine=fold_engine,
                )

                grove_executor = build_grove_executor()
                tool_client_grove = make_tool_aware_client(
                    client, grove_executor,
                    on_tool_call=ui.on_tool_call,
                    on_tool_result=ui.on_tool_result,
                    should_continue=ui.should_continue_agent,
                    fold_engine=fold_engine,
                )

                # Tool-aware runner for grove
                ta_runner = ToolAwareLLMAgentRunner(tool_client_grove)
                runner = ToolAwareCostRunner(ta_runner, collector)
            else:
                llm_runner = LLMAgentRunner(client)
                runner = CostAwareRunner(llm_runner, collector)
        else:
            echo_mode = True

    if runner is None:
        if use_tools:
            runner = ToolAwareEchoRunner(
                on_tool_call=ui.on_tool_call,
                on_tool_result=ui.on_tool_result,
            )
        else:
            runner = LoggingEchoRunner()

    # -- Session manager --
    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else None
    session_mgr = SessionManager(sessions_dir)

    # -- JSON mode: non-interactive --
    if args.output == "json":
        task = args.task or "Build a REST API for task management"
        _run_json_mode(task, client, runner, collector, echo_mode)
        return

    # -- Rich interactive mode --
    ui.print_header()

    if echo_mode:
        ui.console.print("[dim]Running in echo mode (--no-api)[/dim]\n")
    else:
        tools_str = " + tools" if use_tools else ""
        ui.console.print(f"[dim]Using {args.provider} model: {model}{tools_str}[/dim]\n")

    # -- Handle --resume: load existing session and jump to command loop --
    if args.resume:
        try:
            session_data = session_mgr.load(args.resume)
            session_mgr.restore_fold_store(fold_engine)
            ui.print_session_loaded(session_data)
        except FileNotFoundError as e:
            ui.console.print(f"  [red]{e}[/red]")
            return

        task = session_data.task
        all_facts = {}
        if session_data.grove_result:
            all_facts = {
                t: v[0] for t, v in session_data.grove_result.get("facts", {}).items()
            }

        # Rebuild logs from session
        from runner import AgentLog
        logs = {}
        for agent_id, log_data in session_data.agent_logs.items():
            log = AgentLog(
                agent_id=log_data["agent_id"],
                role=log_data["role"],
                facts=log_data.get("facts", {}),
                rating=log_data.get("rating"),
                feedback=log_data.get("feedback", ""),
            )
            logs[agent_id] = log

        effective_out_dir = ""
        codegen_result = None
        if session_data.codegen:
            effective_out_dir = session_data.codegen.get("output_dir", "")

        has_tools = use_tools and client is not None
        effective_chat_client = client
        if use_tools and client:
            out_dir_str = effective_out_dir or str(Path(f"./output/{_task_slug(task)}"))
            chat_executor = build_chat_executor(
                out_dir_str,
                confirm_callback=ui.confirm_shell_command,
            )

            # Add launch_grove tool to chat executor
            def _make_grove_runner_resume():
                from runner import CostAwareRunner
                llm_runner = LLMAgentRunner(client)
                return CostAwareRunner(llm_runner, collector)

            grove_tool = build_launch_grove_tool(
                client=client, collector=collector, fold_engine=fold_engine,
                runner_factory=_make_grove_runner_resume,
                ui_callbacks={
                    "on_agent_start": ui.on_agent_start,
                    "on_agent_done": ui.on_agent_done,
                    "on_propagate": ui.on_propagate,
                },
            )
            chat_executor.add_tool(grove_tool)

            tool_client_chat = make_tool_aware_client(
                client, chat_executor,
                on_tool_call=ui.on_tool_call,
                on_tool_result=ui.on_tool_result,
                should_continue=ui.should_continue_agent,
                fold_engine=fold_engine,
            )
            effective_chat_client = tool_client_chat
            has_tools = hasattr(effective_chat_client, 'executor')

        chat = ConversationalChat(
            effective_chat_client, collector, task, all_facts,
            output_dir=effective_out_dir,
            has_tools=has_tools,
            session_manager=session_mgr,
        ) if effective_chat_client else None

        ui.print_help()
        _command_loop(
            ui, logs, chat, collector, tree=None, result=None,
            echo_mode=echo_mode, client=client, task=task,
            all_facts=all_facts, fold_engine=fold_engine,
            file_tracker=file_tracker, session_mgr=session_mgr,
        )
        # Auto-save on exit
        session_mgr.fold_conversation(fold_engine)
        sid = session_mgr.save()
        fold_count = len(session_mgr.data.conversation.get("folds", []))
        ui.print_session_saved(sid, fold_count)
        ui.print_goodbye()
        return

    # 1. Get task (chat-first loop: conversational messages answered inline)
    task = args.task
    if task is None:
        while True:
            task = ui.prompt_task()
            if task is None:
                ui.print_goodbye()
                return
            if task in ("/quit", "/exit", "quit", "exit", "q"):
                ui.print_goodbye()
                return
            if task == "/help":
                ui.print_help()
                continue
            # Conversational input → answer directly, re-prompt
            if _is_conversational(task):
                reply = _quick_chat(client, collector, task)
                ui.print_chat_reply(reply)
                continue
            break
    ui.print_task(task)

    # Create a new session
    session_mgr.new_session(task, provider=args.provider, model=model, echo_mode=echo_mode)

    # Extract target project directory from the task (if any)
    project_dir = extract_project_dir(task)

    # Phase 0: Pre-analysis with tools
    pre_context = ""
    if use_tools:
        target_label = project_dir or "current directory"
        ui.console.print(f"[bold]Phase 0:[/bold] Exploring project ({target_label})...\n")
        analyzer = TaskAnalyzer(
            client=client,
            tool_client=tool_client_preanalysis,
        )
        if client:
            collector.set_current_agent("pre-analysis")
        ui._current_agent_id = "pre-analysis"
        pre_context = analyzer.pre_analyze(task, project_dir=project_dir)
        if pre_context:
            # Show a brief summary
            preview = pre_context[:200]
            if len(pre_context) > 200:
                preview += "..."
            ui.console.print(f"  [dim]{preview}[/dim]\n")
            session_mgr.set_pre_analysis(pre_context)
    else:
        analyzer = TaskAnalyzer(client=client)

    # Set file tracker to project directory if extracted
    if project_dir:
        file_tracker.root_dir = project_dir
        file_tracker.scan(project_dir)

    # 2. Propose agent team
    if client:
        collector.set_current_agent("analyzer")
    proposal = analyzer.propose(task, context=pre_context)
    session_mgr.set_proposal(proposal)
    ui.print_proposal(proposal)

    # 3. Confirm
    if not ui.prompt_confirm_proposal():
        ui.console.print("[dim]Cancelled.[/dim]")
        ui.print_goodbye()
        return

    # 4. Build tree and launch grove in background
    tree = build_tree_from_proposal(proposal)
    ui.init_execution(tree)

    grove = Grove(
        tree, runner,
        on_agent_start=ui.on_agent_start,
        on_agent_done=ui.on_agent_done,
        on_propagate=ui.on_propagate,
    )

    ui.console.print()
    from ui import BackgroundGrove
    bg_grove = ui.run_grove_background(grove, task)
    ui.console.print(
        "[bold green]Execution started.[/bold green] "
        "Chat while agents work. [cyan]/status[/cyan] to check progress.\n"
    )
    ui.print_help()

    output_dir = Path(args.output_dir) if args.output_dir else None

    # Enter command loop immediately — grove runs in background
    _command_loop(
        ui, {}, None, collector, tree, None, echo_mode,
        client=client, task=task, all_facts={},
        output_dir=output_dir, codegen_result=None,
        fold_engine=fold_engine, file_tracker=file_tracker,
        session_mgr=session_mgr,
        sag_chat=None, runner=runner,
        bg_grove=bg_grove,
        use_tools=use_tools,
    )
    # Auto-save session on exit
    session_mgr.set_agent_logs(logs)
    session_mgr.set_accounting(collector)
    session_mgr.fold_conversation(fold_engine)
    sid = session_mgr.save()
    fold_count = len(session_mgr.data.conversation.get("folds", []))
    ui.print_session_saved(sid, fold_count)
    ui.print_goodbye()


def _task_slug(task: str) -> str:
    """Convert a task description into a short directory name.

    Tries to extract a project name (e.g. "called Terrarium" -> "terrarium").
    Falls back to first 3 meaningful words from the task.
    """
    lower = task.lower()

    # Try "called X" or "named X" patterns
    name_match = re.search(r'(?:called|named)\s+["\']?(\w+)', lower)
    if name_match:
        return name_match.group(1)
    # Try "project X" where X isn't a filler word
    proj_match = re.search(r'project\s+["\']?(\w+)', lower)
    if proj_match and proj_match.group(1) not in ("called", "named", "that", "where", "which", "for", "with"):
        return proj_match.group(1)

    # Filter out common filler words and take first few meaningful words
    stop_words = {
        "i", "want", "to", "a", "an", "the", "my", "me", "we", "our",
        "create", "build", "make", "develop", "write", "implement",
        "that", "which", "where", "with", "for", "and", "or", "of",
        "please", "can", "you", "would", "like", "need", "should",
    }
    words = re.findall(r'[a-z]+', lower)
    meaningful = [w for w in words if w not in stop_words and len(w) > 1]
    if meaningful:
        return "-".join(meaningful[:3])
    # Last resort
    slug = re.sub(r'[^a-z0-9]+', '-', lower).strip('-')
    return slug[:25]


def _run_phase2(
    ui: AgentUI,
    client,
    collector: AccountingCollector,
    task: str,
    all_facts: dict[str, str],
    output_dir: Path | None,
    echo_mode: bool,
) -> CodeGenResult | None:
    """Run Phase 2 code generation. Returns result or None if skipped."""
    if not ui.prompt_codegen():
        return None

    # Clarification step: root agent identifies ambiguities
    if client:
        collector.set_current_agent("codegen:clarify")
        ui._current_agent_id = "codegen:clarify"
        clarifier = ClarificationAgent(client)
        clar = clarifier.check(task, all_facts)
        if clar.needs_clarification and clar.questions:
            ui.print_clarification_questions(clar.questions, clar.summary)
            answer = ui.prompt_clarification_answer()
            if answer:
                # Feed answer back to get updated context — for now, append
                # the user's clarification to the task description
                task = f"{task}\n\nClarifications: {answer}"

    # Planning
    collector.set_current_agent("codegen:planner")
    ui._current_agent_id = "codegen:planner"
    planner = CodeGenPlanner(client=client)
    plan = planner.plan(task, all_facts)
    ui.print_codegen_plan(plan)

    if not ui.prompt_confirm_codegen_plan():
        ui.console.print("[dim]Code generation cancelled.[/dim]")
        return None

    # Execution
    if output_dir is None:
        output_dir = Path(f"./output/{_task_slug(task)}")

    executor = CodeGenExecutor(
        client=client,
        collector=collector,
        on_file_start=ui.on_file_start,
        on_file_done=ui.on_file_done,
    )
    codegen_result = ui.run_codegen_with_live(
        executor, plan, task, all_facts, output_dir,
    )
    ui.print_codegen_result(codegen_result)
    ui.print_codegen_report(echo_mode=echo_mode)

    # Auto-verify syntax after generation
    if codegen_result.files_written > 0:
        runner = ProjectRunner(codegen_result.output_dir)
        verify_results = runner.verify_syntax()
        if verify_results:
            ui.print_verify_results(verify_results)

    return codegen_result


def _on_grove_complete(
    ui: AgentUI,
    bg_grove,
    tree,
    runner,
    collector: AccountingCollector,
    client,
    task: str,
    echo_mode: bool,
    use_tools: bool,
    fold_engine: FoldEngine,
    file_tracker: FileStateTracker,
    session_mgr: SessionManager,
) -> tuple:
    """Handle grove completion: dashboard, serialize transcript, set up chat.

    Returns (result, logs, all_facts, sag_chat, chat, effective_client).
    """
    from session import serialize_execution
    from ui import BackgroundGrove

    result = bg_grove.result
    if result is None:
        ui.console.print("[red]Grove execution failed.[/red]")
        if bg_grove.error:
            ui.console.print(f"  [red]{bg_grove.error}[/red]")
        return None, {}, {}, None, None, client

    ui._inline_mode = False
    ui.print_dashboard(result)
    session_mgr.set_grove_result(result)
    report = collector.build_report(tree, result.messages)
    ui.print_accounting_report(report, echo_mode=echo_mode)

    all_facts = {t: str(v) for t, (v, _ver) in result.facts.items()}
    logs = runner.logs if hasattr(runner, "logs") else {}
    session_mgr.set_agent_logs(logs)

    # Serialize SAG transcript to file
    output_path = f"output/{_task_slug(task)}/grove.sag"
    try:
        serialize_execution(result, output_path)
        ui.console.print(f"  [dim]SAG transcript saved: {output_path}[/dim]")
    except Exception:
        pass  # non-fatal

    # Build chat sessions
    effective_chat_client = client
    output_dir_str = str(Path(f"./output/{_task_slug(task)}"))

    if use_tools and client:
        chat_executor = build_chat_executor(
            output_dir_str,
            confirm_callback=ui.confirm_shell_command,
        )

        def _make_grove_runner():
            from runner import CostAwareRunner
            llm_runner = LLMAgentRunner(client)
            return CostAwareRunner(llm_runner, collector)

        grove_tool = build_launch_grove_tool(
            client=client, collector=collector, fold_engine=fold_engine,
            runner_factory=_make_grove_runner,
            parent_tree=tree,
            ui_callbacks={
                "on_agent_start": ui.on_agent_start,
                "on_agent_done": ui.on_agent_done,
                "on_propagate": ui.on_propagate,
            },
        )
        chat_executor.add_tool(grove_tool)

        tool_client_chat = make_tool_aware_client(
            client, chat_executor,
            on_tool_call=ui.on_tool_call,
            on_tool_result=ui.on_tool_result,
            should_continue=ui.should_continue_agent,
            fold_engine=fold_engine,
        )
        effective_chat_client = tool_client_chat
        file_tracker.root_dir = output_dir_str

    has_tools = use_tools and effective_chat_client is not None and hasattr(effective_chat_client, 'executor')

    sag_chat = None
    if result and tree and runner:
        facts_text = "\n".join(f"  {k} = {v}" for k, v in all_facts.items())
        chat_system = _CHAT_SYSTEM_PROMPT.format(
            task=task,
            output_dir=output_dir_str,
            file_list="  (none yet)",
            facts=facts_text,
        )
        sag_chat = ChatSession(
            result, tree, runner,
            client=effective_chat_client if has_tools else None,
            system_prompt=chat_system,
        )

    chat = ConversationalChat(
        effective_chat_client, collector, task, all_facts,
        output_dir=output_dir_str,
        has_tools=has_tools,
        session_manager=session_mgr,
    ) if (effective_chat_client and sag_chat is None) else None

    return result, logs, all_facts, sag_chat, chat, effective_chat_client


def _command_loop(
    ui: AgentUI,
    logs: dict,
    chat: ConversationalChat | None,
    collector: AccountingCollector,
    tree,
    result,
    echo_mode: bool,
    client=None,
    task: str = "",
    all_facts: dict[str, str] | None = None,
    output_dir: Path | None = None,
    codegen_result: CodeGenResult | None = None,
    fold_engine: FoldEngine | None = None,
    file_tracker: FileStateTracker | None = None,
    session_mgr: SessionManager | None = None,
    sag_chat: ChatSession | None = None,
    runner=None,
    bg_grove=None,
    use_tools: bool = False,
) -> None:
    """Main interactive command loop after execution."""
    while True:
        # Check if background grove has completed
        if bg_grove is not None and bg_grove.done.is_set():
            result, logs, all_facts, sag_chat, chat, client = _on_grove_complete(
                ui, bg_grove, tree, runner, collector, client, task,
                echo_mode, use_tools, fold_engine, file_tracker, session_mgr,
            )
            bg_grove = None  # Clear handle

        raw = ui.prompt_chat()
        if raw is None:
            return

        cmd = raw.strip()
        if not cmd:
            continue

        # -- Commands --
        if cmd in ("/quit", "/exit", "quit", "exit", "q"):
            return

        elif cmd == "/help":
            ui.print_help()

        elif cmd == "/logs":
            ui.print_agent_list(logs)

        elif cmd.startswith("/logs "):
            agent_id = cmd.split(maxsplit=1)[1].strip()
            if agent_id in logs:
                metrics = [
                    c for c in collector.get_calls() if c.agent_id == agent_id
                ]
                ui.print_agent_log(logs[agent_id], metrics or None)
            else:
                ui.console.print(f"  [red]Unknown agent: {agent_id}[/red]")
                ui.console.print(f"  [dim]Available: {', '.join(logs.keys())}[/dim]")

        elif cmd == "/cost" or cmd == "/accounting":
            if tree is not None and result is not None:
                report = collector.build_report(tree, result.messages)
                ui.print_accounting_report(report, echo_mode=echo_mode)
            ui.print_codegen_report(echo_mode=echo_mode)

        elif cmd == "/status":
            if bg_grove is not None:
                ui.print_grove_status()
            elif result is not None:
                ui.console.print("  [green]Grove execution complete.[/green]")
            else:
                ui.console.print("  [dim]No grove execution in progress.[/dim]")

        elif cmd == "/transcript" or cmd.startswith("/transcript "):
            if result is None:
                ui.console.print("  [dim]No grove result yet. Wait for execution to complete.[/dim]")
            else:
                from sag.minifier import MessageMinifier as _MM
                parts = cmd.split(None, 1)
                if len(parts) > 1:
                    # /transcript <agent-id>
                    agent_id = parts[1].strip()
                    if agent_id in logs and logs[agent_id].sag_transcript:
                        for wire in logs[agent_id].sag_transcript:
                            ui.console.print(f"  [cyan]{wire}[/cyan]")
                    else:
                        ui.console.print(f"  [dim]No transcript for {agent_id}[/dim]")
                else:
                    # Full execution transcript
                    for msg in result.messages:
                        wire = _MM.to_minified_string(msg)
                        ui.console.print(f"  [cyan]{wire}[/cyan]")

        elif cmd == "/tree":
            if tree is not None:
                ui.print_tree(tree)
            else:
                ui.console.print("  [dim]No agent tree in this session.[/dim]")

        elif cmd == "/facts":
            if result is not None:
                ui.print_facts(result)
            else:
                ui.console.print("  [dim]No grove result in this session.[/dim]")

        elif cmd.startswith("/rate "):
            parts = cmd.split()
            if len(parts) == 3:
                agent_id, rating_str = parts[1], parts[2]
                try:
                    rating = int(rating_str)
                    if not 1 <= rating <= 5:
                        raise ValueError
                except ValueError:
                    ui.console.print("  [red]Rating must be 1-5[/red]")
                    continue
                if agent_id in logs:
                    logs[agent_id].rating = rating
                    ui.print_rating(agent_id, rating)
                else:
                    ui.console.print(f"  [red]Unknown agent: {agent_id}[/red]")
            else:
                ui.console.print("  [dim]Usage: /rate <agent-id> <1-5>[/dim]")

        elif cmd.startswith("/feedback "):
            agent_id = cmd.split(maxsplit=1)[1].strip()
            if agent_id in logs:
                text = ui.prompt_feedback(agent_id)
                if text:
                    logs[agent_id].feedback = text
                    ui.print_feedback_saved(agent_id)
            else:
                ui.console.print(f"  [red]Unknown agent: {agent_id}[/red]")

        elif cmd == "/codegen":
            if result is not None:
                facts = all_facts or {
                    t: str(v) for t, (v, _ver) in result.facts.items()
                }
            else:
                facts = all_facts or {}
            codegen_result = _run_phase2(
                ui, client, collector, task, facts, output_dir, echo_mode,
            )
            # Update chat with newly generated files
            if codegen_result and chat:
                new_files = [
                    f"{codegen_result.output_dir}/{f.spec.path}"
                    for f in codegen_result.files if f.success
                ]
                chat.update_generated_files(new_files, codegen_result.output_dir)

        elif cmd == "/files":
            if codegen_result is not None:
                ui.print_generated_files(codegen_result)
            else:
                ui.console.print(
                    "  [dim]No files generated yet. Run /codegen first.[/dim]"
                )

        elif cmd == "/test" or cmd.startswith("/test "):
            if codegen_result is not None:
                test_cmd = cmd[6:].strip() if cmd.startswith("/test ") else None
                runner = ProjectRunner(codegen_result.output_dir)
                if test_cmd:
                    test_result = runner.run_tests(test_cmd)
                else:
                    test_result = runner.run_tests()
                ui.print_test_result(test_result)
            else:
                ui.console.print(
                    "  [dim]No project to test. Run /codegen first.[/dim]"
                )

        elif cmd.startswith("/run "):
            command = cmd[5:].strip()
            if codegen_result is not None:
                runner = ProjectRunner(codegen_result.output_dir)
                run_result = runner.run(command)
                ui.print_run_result(run_result)
            else:
                ui.console.print(
                    "  [dim]No project directory. Run /codegen first.[/dim]"
                )

        elif cmd == "/grove":
            if tree is not None:
                ui.print_grove_view(tree, fold_engine=fold_engine)
            else:
                ui.console.print("  [dim]No agent tree in this session.[/dim]")

        elif cmd.startswith("/graft "):
            if tree is None:
                ui.console.print("  [dim]No agent tree in this session.[/dim]")
                continue
            # /graft <parent-id> <new-id> <role>
            parts = cmd.split(None, 3)
            if len(parts) < 4:
                ui.console.print("  [dim]Usage: /graft <parent-id> <new-id> <role>[/dim]")
            else:
                _, parent_id, new_id, role = parts
                try:
                    node = tree.graft(parent_id, new_id, role)
                    ui.console.print(
                        f"  [green]Grafted [bold]{new_id}[/bold] ({role}) "
                        f"under {parent_id}[/green]"
                    )
                    ui.print_grove_view(tree, fold_engine=fold_engine)
                except (KeyError, ValueError) as e:
                    ui.console.print(f"  [red]{e}[/red]")

        elif cmd.startswith("/prune "):
            if tree is None:
                ui.console.print("  [dim]No agent tree in this session.[/dim]")
                continue
            agent_id = cmd.split(None, 1)[1].strip()
            try:
                pruned_facts = tree.prune(agent_id, fold_engine=fold_engine)
                ui.console.print(
                    f"  [yellow]Pruned [bold]{agent_id}[/bold] "
                    f"({len(pruned_facts)} facts folded into parent)[/yellow]"
                )
                ui.print_grove_view(tree, fold_engine=fold_engine)
            except (KeyError, ValueError) as e:
                ui.console.print(f"  [red]{e}[/red]")

        elif cmd == "/snapshot":
            if file_tracker and file_tracker.root_dir:
                try:
                    snap_id = file_tracker.snapshot()
                    ui.console.print(
                        f"  [green]Snapshot saved: [bold]{snap_id}[/bold][/green]\n"
                        f"  [dim]Use /restore {snap_id} to roll back.[/dim]"
                    )
                except FileNotFoundError as e:
                    ui.console.print(f"  [red]{e}[/red]")
            else:
                ui.console.print(
                    "  [dim]No project to snapshot. Run /codegen first.[/dim]"
                )

        elif cmd.startswith("/restore "):
            snap_id = cmd.split(None, 1)[1].strip()
            if file_tracker:
                try:
                    restored = file_tracker.restore(snap_id)
                    ui.console.print(
                        f"  [green]Restored {len(restored)} files from snapshot.[/green]"
                    )
                    for f in restored[:10]:
                        ui.console.print(f"    {f}")
                    if len(restored) > 10:
                        ui.console.print(f"    ... and {len(restored) - 10} more")
                except FileNotFoundError as e:
                    ui.console.print(f"  [red]{e}[/red]")
            else:
                ui.console.print("  [dim]File state tracking not available.[/dim]")

        elif cmd == "/state":
            if file_tracker:
                summary = file_tracker.get_summary()
                if summary:
                    ui.console.print("\n  [bold]File State Summary:[/bold]")
                    for status, count in sorted(summary.items()):
                        icon = {"tracked": "\u2713", "modified": "\u270e", "created": "+", "deleted": "\u2717"}.get(status, "?")
                        ui.console.print(f"    {icon} {status}: {count}")
                    modified = file_tracker.get_modified_files()
                    if modified:
                        ui.console.print("\n  [bold]Modified/Created files:[/bold]")
                        for f in modified:
                            ui.console.print(f"    {f.status:10s} {f.path} ({f.size:,} bytes)")
                else:
                    ui.console.print("  [dim]No files tracked. Run /codegen first.[/dim]")
            else:
                ui.console.print("  [dim]File state tracking not available.[/dim]")

        elif cmd == "/chaos":
            if codegen_result is None:
                ui.console.print("  [dim]No project to chaos test. Run /codegen first.[/dim]")
            elif not file_tracker:
                ui.console.print("  [dim]File state tracking not available.[/dim]")
            else:
                # 1. Snapshot
                ui.console.print("\n  [bold yellow]Chaos Engineering Run[/bold yellow]")
                try:
                    snap_id = file_tracker.snapshot()
                    ui.console.print(f"  [green]1. Snapshot saved: {snap_id}[/green]")
                except FileNotFoundError as e:
                    ui.console.print(f"  [red]Cannot snapshot: {e}[/red]")
                    continue

                # 2. Run baseline tests
                runner = ProjectRunner(codegen_result.output_dir)
                ui.console.print("  [cyan]2. Running baseline tests...[/cyan]")
                baseline = runner.run_tests()
                ui.console.print(
                    f"     Baseline: {baseline.summary} "
                    f"({'[green]PASS[/green]' if baseline.success else '[red]FAIL[/red]'})"
                )

                # 3. Show file state
                ui.console.print("  [cyan]3. File state:[/cyan]")
                summary = file_tracker.get_summary()
                for status, count in sorted(summary.items()):
                    ui.console.print(f"     {status}: {count}")

                # 4. Prompt for manual chaos or automatic
                ui.console.print(
                    "\n  [bold]The project is snapshot-protected.[/bold]\n"
                    "  You can now:\n"
                    "  - Chat with the assistant to inject faults (it can patch files)\n"
                    "  - Use [cyan]/test[/cyan] to run tests after modifications\n"
                    "  - Use [cyan]/state[/cyan] to see what changed\n"
                    "  - Use [cyan]/restore " + snap_id + "[/cyan] to rollback\n"
                )

        elif cmd == "/save":
            if session_mgr and session_mgr.data:
                if fold_engine:
                    session_mgr.fold_conversation(fold_engine)
                session_mgr.set_agent_logs(logs)
                session_mgr.set_accounting(collector)
                sid = session_mgr.save()
                fold_count = len(
                    session_mgr.data.conversation.get("folds", [])
                )
                ui.print_session_saved(sid, fold_count)
            else:
                ui.console.print("  [dim]No active session to save.[/dim]")

        elif cmd == "/sessions":
            if session_mgr:
                sessions = session_mgr.list_sessions()
                ui.print_sessions(sessions)
            else:
                ui.console.print("  [dim]Session manager not available.[/dim]")

        elif cmd.startswith("/load "):
            load_id = cmd.split(None, 1)[1].strip()
            if session_mgr:
                try:
                    loaded = session_mgr.load(load_id)
                    if fold_engine:
                        session_mgr.restore_fold_store(fold_engine)
                    ui.print_session_loaded(loaded)
                except FileNotFoundError as e:
                    ui.console.print(f"  [red]{e}[/red]")
            else:
                ui.console.print("  [dim]Session manager not available.[/dim]")

        elif cmd.startswith("/delete-session "):
            del_id = cmd.split(None, 1)[1].strip()
            if session_mgr:
                if session_mgr.delete(del_id):
                    ui.console.print(
                        f"  [green]Session {del_id[:12]}... deleted.[/green]"
                    )
                else:
                    ui.console.print(
                        f"  [red]Session not found: {del_id}[/red]"
                    )
            else:
                ui.console.print("  [dim]Session manager not available.[/dim]")

        elif cmd.startswith("/edit "):
            rest = cmd[6:].strip()
            # Split: first token is the file path, rest is the instruction
            parts = rest.split(None, 1)
            if len(parts) < 2:
                ui.console.print("  [dim]Usage: /edit <file> <instruction>[/dim]")
            elif client is None:
                ui.console.print("  [dim]Edit requires an API key.[/dim]")
            else:
                file_path = parts[0]
                instruction = parts[1]
                # Resolve relative to output dir if codegen ran
                if codegen_result and not os.path.isabs(file_path):
                    file_path = os.path.join(codegen_result.output_dir, file_path)
                edit_client = client  # Use the effective client (may be tool-aware)
                edit_agent = EditAgent(edit_client, collector)
                summary = edit_agent.edit(file_path, instruction)
                ui.print_edit_result(file_path, summary)

        elif cmd.startswith("/ask "):
            # /ask <agent-id> <question> — query a specific agent via SAG
            parts = cmd.split(None, 2)
            if len(parts) < 3:
                ui.console.print("  [dim]Usage: /ask <agent-id> <question>[/dim]")
            elif tree is None or runner is None:
                ui.console.print("  [dim]No agent tree available. /ask requires a grove execution.[/dim]")
            else:
                agent_id = parts[1]
                question = parts[2]
                node = tree.get_node(agent_id)
                if node is None:
                    ui.console.print(f"  [red]Unknown agent: {agent_id}[/red]")
                    all_ids = tree.get_all_node_ids()
                    ui.console.print(f"  [dim]Available: {', '.join(all_ids)}[/dim]")
                else:
                    # Build child_facts from the agent's current knowledge
                    child_facts: dict[str, str] = {}
                    for topic, (value, _ver) in node.knowledge.get_all_facts().items():
                        child_facts[topic] = str(value)
                    # Run the agent with the question
                    facts = runner.run(node, question, child_facts)
                    ui.print_agent_reply(agent_id, facts)

        else:
            # Chat: prefer SAG-based ChatSession when available
            if sag_chat is not None:
                resp = sag_chat.chat(cmd)
                root_id = tree.get_root().agent_id if tree else "root"
                ui.print_agent_reply(root_id, resp.facts_updated)

                # Automatic delegation: check for DELEGATE in the reply
                if tree is not None and runner is not None:
                    from delegation import parse_delegations, process_delegations
                    reply_text = "\n".join(
                        f"{t} = {v}" for t, v in resp.facts_updated.items()
                    )
                    deleg_pairs = parse_delegations(reply_text)
                    if deleg_pairs:
                        deleg_results = process_delegations(
                            reply_text, tree, runner,
                        )
                        for d in deleg_results:
                            if "error" in d:
                                ui.console.print(
                                    f"  [red]Delegation to {d['agent_id']}: {d['error']}[/red]"
                                )
                            else:
                                ui.print_agent_reply(d["agent_id"], d["facts"])

            elif chat:
                reply = chat.chat(cmd)
                ui.print_chat_reply(reply)
            else:
                ui.console.print(
                    "  [dim]Chat requires an API key. Use commands or /help.[/dim]"
                )


def _run_json_mode(task, client, runner, collector, echo_mode):
    """Non-interactive JSON output mode."""
    analyzer = TaskAnalyzer(client=client)
    proposal = analyzer.propose(task)
    tree = build_tree_from_proposal(proposal)

    grove = Grove(tree, runner)
    result = grove.execute(task)
    report = collector.build_report(tree, result.messages)

    logs = runner.logs if hasattr(runner, "logs") else {}
    data = {
        "task": task,
        "agents_run": result.agents_run,
        "levels_processed": result.levels_processed,
        "messages_exchanged": len(result.messages),
        "echo_mode": echo_mode,
        "team": [
            {"agent_id": a.agent_id, "role": a.role, "parent": a.parent_id}
            for a in proposal.agents
        ],
        "totals": {
            "input_tokens": report.total_input_tokens,
            "output_tokens": report.total_output_tokens,
            "total_tokens": report.total_tokens,
            "cost_usd": round(report.total_cost_usd, 6),
            "latency_ms": round(report.total_latency_ms, 1),
        },
        "wire_format": {
            "sag_tokens": report.total_sag_tokens,
            "json_tokens": report.total_json_tokens,
            "tokens_saved": report.total_wire_savings,
            "savings_percent": round(report.wire_savings_percent, 1),
        },
        "agents": [
            {
                "agent_id": s.agent_id, "role": s.role,
                "calls": s.calls,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cost_usd": round(s.cost_usd, 6),
            }
            for s in report.agent_summaries
        ],
        "facts": {
            topic: str(value) for topic, (value, _ver) in result.facts.items()
        },
        "feedback": {
            aid: {"rating": log.rating, "feedback": log.feedback}
            for aid, log in logs.items()
            if log.rating is not None or log.feedback
        },
        "sag_messages": [
            MessageMinifier.to_minified_string(m) for m in result.messages
        ],
    }
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
