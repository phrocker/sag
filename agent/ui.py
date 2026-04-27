"""Rich TUI for the software agent.

Features:
- Proposal display with confirmation
- Live execution status board (Rich Live) or inline status during background mode
- Post-execution dashboard with /logs, /cost, /rate commands
- RLHF feedback capture
- Accounting report tables
- Phase 2: code generation plan display, live file progress, result summary
- Tool call display: on_tool_call / on_tool_result callbacks
- Shell command confirmation prompt
- Background grove execution with live chat
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import box

from sag.accounting import AccountingCollector, AccountingReport, CallMetrics
from sag.grove import GroveResult
from sag.model import Message
from sag.tools import ToolCall, ToolResult
from sag.tree import AgentNode, TreeEngine

from analyzer import TreeProposal
from runner import AgentLog


@dataclass
class BackgroundGrove:
    """Handle for a grove executing in a background thread."""

    done: threading.Event = field(default_factory=threading.Event)
    result: GroveResult | None = None
    error: Exception | None = None
    thread: threading.Thread | None = None


class AgentUI:
    """Rich TUI for the interactive software agent."""

    def __init__(
        self,
        console: Console | None = None,
        collector: AccountingCollector | None = None,
    ) -> None:
        self.console = console or Console()
        self._collector = collector
        # Execution tracking for live display
        self._agent_status: dict[str, str] = {}
        self._agent_facts: dict[str, dict[str, str]] = {}
        self._tree: TreeEngine | None = None
        self._live: Live | None = None
        # Tool call tracking
        self._agent_tool_calls: dict[str, int] = {}
        self._agent_last_tool: dict[str, str] = {}  # agent_id -> "tool(args)"
        self._current_agent_id: str | None = None
        # Thread safety for concurrent agent execution
        self._lock = threading.Lock()
        self._input_lock = threading.Lock()
        self._thread_local = threading.local()
        # Inline mode: print status lines instead of Rich Live table
        self._inline_mode: bool = False

    # -- Header --

    def print_header(self) -> None:
        self.console.print()
        self.console.print(
            Panel(
                "[bold blue]Agent Grove[/bold blue]\n"
                "Describe a task. Agents are proposed, confirmed, then executed.\n"
                "Type [bold]/help[/bold] for commands.",
                box=box.DOUBLE,
                style="blue",
            )
        )
        self.console.print()

    # -- Interactive prompts --

    def _wait_for_input(self, prompt: str = "> ") -> str | None:
        """Wait for terminal input."""
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def prompt_task(self) -> str | None:
        """Ask the user what to work on. Returns None on empty/interrupt."""
        self.console.print("[bold]What would you like to work on?[/bold] [dim](or just chat)[/dim]")
        task = self._wait_for_input("> ")
        if not task:
            return None
        self.console.print()
        return task

    def prompt_confirm_proposal(self) -> bool:
        """Ask user to confirm the proposed agent tree. Returns True to proceed."""
        while True:
            self.console.print(
                "[bold]Proceed with this team?[/bold] [dim](Y/n)[/dim]"
            )
            answer = self._wait_for_input("> ")
            if answer is None:
                return False
            if self._handle_prompt_command(answer):
                continue
            return answer.lower() in ("", "y", "yes")

    def prompt_chat(self) -> str | None:
        """Prompt for a command or chat message. Returns None on interrupt."""
        return self._wait_for_input("\n> ")

    # -- Proposal display --

    def print_proposal(self, proposal: TreeProposal) -> None:
        """Show proposed agent tree with rationale."""
        # Build tree structure from flat list
        root_spec = None
        children_map: dict[str | None, list] = {}
        for agent in proposal.agents:
            children_map.setdefault(agent.parent_id, []).append(agent)
            if agent.parent_id is None:
                root_spec = agent

        if root_spec is None:
            self.console.print("[red]Invalid proposal: no root agent[/red]")
            return

        rich_tree = Tree(
            f"[bold]{root_spec.role}[/bold] [dim]({root_spec.agent_id})[/dim]"
        )
        self._build_proposal_tree(root_spec.agent_id, children_map, rich_tree)

        self.console.print(
            Panel(rich_tree, title="[bold]Proposed Agent Team[/bold]", box=box.ROUNDED)
        )
        if proposal.rationale:
            self.console.print(f"  [dim]{proposal.rationale}[/dim]")
        self.console.print()

    def _build_proposal_tree(
        self, parent_id: str, children_map: dict, rich_node: Tree
    ) -> None:
        for child in children_map.get(parent_id, []):
            label = f"[bold]{child.role}[/bold] [dim]({child.agent_id})[/dim]"
            child_tree = rich_node.add(label)
            self._build_proposal_tree(child.agent_id, children_map, child_tree)

    # -- Live execution display --

    def print_task(self, task: str) -> None:
        self.console.print(
            Panel(
                task,
                title="[bold green]Task[/bold green]",
                box=box.ROUNDED,
                style="green",
            )
        )
        self.console.print()

    def init_execution(self, tree: TreeEngine) -> None:
        """Prepare for live execution tracking."""
        self._tree = tree
        self._agent_status.clear()
        self._agent_facts.clear()
        self._agent_tool_calls.clear()
        self._agent_last_tool.clear()
        for agent_id in tree.get_all_node_ids():
            self._agent_status[agent_id] = "pending"

    def _build_status_table(self) -> Table:
        """Build the live status table."""
        table = Table(
            title="Execution Status",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("", width=2)
        table.add_column("Agent", style="bold cyan", min_width=12)
        table.add_column("Role", style="dim", min_width=16)
        table.add_column("Activity", style="dim", min_width=20)
        table.add_column("Tools", justify="right", width=5)
        table.add_column("Facts", justify="right", width=5)
        table.add_column("Cost", justify="right", width=8, style="green")

        if self._tree is None:
            return table

        # Show agents in execution order (bottom-up)
        for level in self._tree.get_levels_bottom_up():
            for node in level:
                status = self._agent_status.get(node.agent_id, "pending")
                icon = {"pending": "\u25cb", "running": "\u25cf", "done": "\u2713"}[
                    status
                ]
                style = {"pending": "dim", "running": "yellow", "done": "green"}[
                    status
                ]

                # Activity column: show last tool call when running
                activity = ""
                if status == "running":
                    last_tool = self._agent_last_tool.get(node.agent_id, "")
                    if last_tool:
                        activity = f"[yellow]{last_tool}[/yellow]"
                    else:
                        activity = "[yellow]thinking...[/yellow]"

                n_tools = self._agent_tool_calls.get(node.agent_id, 0)
                tools_str = str(n_tools) if n_tools > 0 else ""

                n_facts = len(self._agent_facts.get(node.agent_id, {}))
                facts_str = str(n_facts) if status == "done" else ""

                cost_str = ""
                if self._collector:
                    calls = [
                        c
                        for c in self._collector.get_calls()
                        if c.agent_id == node.agent_id
                    ]
                    if calls:
                        total_cost = sum(c.cost_usd for c in calls)
                        cost_str = f"${total_cost:.4f}"

                table.add_row(
                    f"[{style}]{icon}[/{style}]",
                    node.agent_id,
                    node.role,
                    activity,
                    tools_str,
                    facts_str,
                    cost_str,
                )

        return table

    def on_agent_start(self, node: AgentNode, task: str) -> None:
        self._thread_local.agent_id = node.agent_id
        with self._lock:
            self._agent_status[node.agent_id] = "running"
            self._current_agent_id = node.agent_id
        if self._inline_mode:
            self.console.print(
                f"  [yellow]\u25b6[/yellow] [bold]{node.agent_id}[/bold] "
                f"[dim]({node.role})[/dim] started"
            )
        elif self._live:
            self._live.update(self._build_status_table())
            self._live.refresh()

    def on_agent_done(self, node: AgentNode, facts: dict[str, str]) -> None:
        with self._lock:
            self._agent_status[node.agent_id] = "done"
            self._agent_facts[node.agent_id] = dict(facts)
        if self._inline_mode:
            cost_str = ""
            if self._collector:
                calls = [
                    c for c in self._collector.get_calls()
                    if c.agent_id == node.agent_id
                ]
                if calls:
                    total_cost = sum(c.cost_usd for c in calls)
                    cost_str = f" [green]${total_cost:.4f}[/green]"
            self.console.print(
                f"  [green]\u2713[/green] [bold]{node.agent_id}[/bold] done: "
                f"{len(facts)} facts{cost_str}"
            )
        elif self._live:
            self._live.update(self._build_status_table())
            self._live.refresh()

    def on_propagate(
        self, child: AgentNode, parent: AgentNode, msg: Message
    ) -> None:
        pass  # Kept clean during live display

    # -- Tool call callbacks --

    def on_tool_call(self, call: ToolCall) -> None:
        """Called when an agent invokes a tool."""
        agent_id = getattr(self._thread_local, "agent_id", None) or self._current_agent_id or "unknown"
        with self._lock:
            self._agent_tool_calls[agent_id] = (
                self._agent_tool_calls.get(agent_id, 0) + 1
            )
        # Format a short activity string
        activity = call.name
        args = call.arguments
        if call.name == "read_file" and "path" in args:
            path = str(args["path"])
            # Show just the filename or last path component
            short = path.rsplit("/", 1)[-1] if "/" in path else path
            activity = f"read {short}"
        elif call.name == "list_directory":
            path = str(args.get("path", "."))
            activity = f"ls {path}"
        elif call.name == "search_files" and "pattern" in args:
            activity = f'grep "{args["pattern"]}"'
        elif call.name == "run_shell" and "command" in args:
            cmd = str(args["command"])
            activity = cmd[:25] + ("..." if len(cmd) > 25 else "")
        elif call.name == "write_file" and "path" in args:
            short = str(args["path"]).rsplit("/", 1)[-1]
            activity = f"write {short}"
        elif call.name == "patch_file" and "path" in args:
            short = str(args["path"]).rsplit("/", 1)[-1]
            activity = f"patch {short}"
        elif call.name == "web_fetch" and "url" in args:
            url = str(args["url"])
            # Show domain
            domain = url.split("//")[-1].split("/")[0] if "//" in url else url[:20]
            activity = f"fetch {domain}"
        elif call.name == "web_search" and "query" in args:
            q = str(args["query"])
            activity = f'search "{q[:20]}"'

        # Truncate for table display
        if len(activity) > 30:
            activity = activity[:27] + "..."
        with self._lock:
            self._agent_last_tool[agent_id] = activity
        if self._live:
            self._live.update(self._build_status_table())
            self._live.refresh()

    def on_tool_result(self, result: ToolResult) -> None:
        """Called when a tool returns a result."""
        if self._live:
            self._live.update(self._build_status_table())
            self._live.refresh()

    def should_continue_agent(self, turn: int, results: list) -> str:
        """Ask the user whether an agent should keep exploring.

        Called between tool turns. Returns "continue", "finish", or "stop".
        Prompts every 5 turns starting after turn 10.
        """
        # Let agents explore without interruption
        if turn < 50:
            return "continue"
        # Check in every 50 turns after that
        if (turn - 50) % 50 != 0:
            return "continue"

        agent_id = getattr(self._thread_local, "agent_id", None) or self._current_agent_id or "agent"
        n_tools = self._agent_tool_calls.get(agent_id, 0)

        with self._input_lock:
            if self._live:
                self._live.stop()

            self.console.print(
                f"\n  [bold]{agent_id}[/bold]: {n_tools} tool calls across {turn} turns. "
                "[dim]Enter[/dim]=continue  [dim]s[/dim]=wrap up  [dim]q[/dim]=stop"
            )
            try:
                answer = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "q"

            if self._live:
                self._live.start()
                self._live.update(self._build_status_table())

        if answer in ("s", "stop", "finish"):
            return "finish"
        elif answer in ("q", "quit"):
            return "stop"
        return "continue"

    def confirm_shell_command(self, command: str) -> bool:
        """Prompt the user to confirm a shell command.

        Returns True if the user allows it, False otherwise.
        """
        with self._input_lock:
            self.console.print(
                f"\n  [bold yellow]Agent wants to run:[/bold yellow] [cyan]{command}[/cyan]"
            )
            try:
                answer = input("  Allow? (y/N) > ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                return False
            return answer.lower() in ("y", "yes")

    def run_with_live(self, grove, task: str) -> GroveResult:
        """Execute the grove with a live-updating status display."""
        with Live(
            self._build_status_table(),
            console=self.console,
            refresh_per_second=4,
        ) as live:
            self._live = live
            result = grove.execute(task)
            # Final update
            live.update(self._build_status_table())
            self._live = None
        return result

    def run_grove_background(self, grove, task: str) -> BackgroundGrove:
        """Start grove execution in a background thread.

        Returns a BackgroundGrove handle immediately. Status lines are
        printed inline (no Rich Live table) so the user can type commands.
        """
        self._inline_mode = True
        bg = BackgroundGrove()

        def _run():
            try:
                bg.result = grove.execute(task)
            except Exception as exc:
                bg.error = exc
            finally:
                bg.done.set()

        bg.thread = threading.Thread(target=_run, daemon=True, name="grove-bg")
        bg.thread.start()
        return bg

    def print_grove_status(self) -> None:
        """Print current agent execution status (for /status command)."""
        running = [
            aid for aid, s in self._agent_status.items() if s == "running"
        ]
        done = [
            aid for aid, s in self._agent_status.items() if s == "done"
        ]
        pending = [
            aid for aid, s in self._agent_status.items() if s == "pending"
        ]
        total = len(self._agent_status)
        self.console.print(
            f"  Agents: {len(done)}/{total} done, "
            f"{len(running)} running, {len(pending)} pending"
        )
        if running:
            for aid in running:
                activity = self._agent_last_tool.get(aid, "thinking...")
                self.console.print(
                    f"    [yellow]\u25cf[/yellow] {aid}: {activity}"
                )

    # -- Post-execution dashboard --

    def print_dashboard(self, result: GroveResult) -> None:
        """Print compact execution summary."""
        self.console.print()
        self.console.print(
            Panel(
                f"Agents: [bold]{result.agents_run}[/bold] | "
                f"Levels: [bold]{result.levels_processed}[/bold] | "
                f"Messages: [bold]{len(result.messages)}[/bold] | "
                f"Facts: [bold]{len(result.facts)}[/bold]",
                title="[bold green]Execution Complete[/bold green]",
                box=box.ROUNDED,
                style="green",
            )
        )

    def print_help(self) -> None:
        self.console.print(
            Panel(
                "[bold]Development:[/bold]\n"
                "  [cyan]/codegen[/cyan]          Generate code from analysis\n"
                "  [cyan]/files[/cyan]            List generated files\n"
                "  [cyan]/edit <file> <instr>[/cyan]  Edit a file with instructions\n"
                "  [cyan]/run <command>[/cyan]    Run a command in the project dir\n"
                "  [cyan]/test[/cyan]             Run tests (auto-detect framework)\n"
                "  [cyan]/test <cmd>[/cyan]       Run tests with custom command\n"
                "  [cyan]/chaos[/cyan]            Chaos mode: snapshot, baseline test, inject faults\n"
                "\n"
                "[bold]Grove Architect:[/bold]\n"
                "  [cyan]/grove[/cyan]            Show decorated grove view (facts, folds, state)\n"
                "  [cyan]/graft <pid> <id> <role>[/cyan]  Graft a new agent under parent\n"
                "  [cyan]/prune <id>[/cyan]       Prune an agent (fold knowledge into parent)\n"
                "  [cyan]/state[/cyan]            Show file state tracking summary\n"
                "  [cyan]/snapshot[/cyan]         Save project state (for chaos rollback)\n"
                "  [cyan]/restore <id>[/cyan]     Restore project from snapshot\n"
                "\n"
                "[bold]Session:[/bold]\n"
                "  [cyan]/save[/cyan]             Save current session\n"
                "  [cyan]/sessions[/cyan]         List saved sessions\n"
                "  [cyan]/load <id>[/cyan]        Resume a saved session\n"
                "  [cyan]/delete-session <id>[/cyan]  Delete a saved session\n"
                "\n"
                "[bold]Inspection:[/bold]\n"
                "  [cyan]/status[/cyan]           Show agent execution progress\n"
                "  [cyan]/transcript[/cyan]       Show full SAG wire transcript\n"
                "  [cyan]/transcript <id>[/cyan]  Show SAG transcript for one agent\n"
                "  [cyan]/logs <id>[/cyan]        View an agent's output\n"
                "  [cyan]/logs[/cyan]             List all agents\n"
                "  [cyan]/cost[/cyan]             Show cost accounting report\n"
                "  [cyan]/tree[/cyan]             Show agent tree\n"
                "  [cyan]/facts[/cyan]            Show root knowledge\n"
                "  [cyan]/ask <id> <question>[/cyan]  Query a specific agent via SAG\n"
                "\n"
                "[bold]Feedback:[/bold]\n"
                "  [cyan]/rate <id> <1-5>[/cyan]  Rate an agent's output (RLHF)\n"
                "  [cyan]/feedback <id>[/cyan]    Give redirect feedback to an agent\n"
                "\n"
                "  [cyan]/help[/cyan]             Show this help\n"
                "  [cyan]/quit[/cyan]             Exit\n"
                "\n"
                "Or type a message to chat while agents work.",
                box=box.ROUNDED,
            )
        )

    def print_agent_list(self, logs: dict[str, AgentLog]) -> None:
        """List all agents with fact counts and ratings."""
        table = Table(box=box.ROUNDED, show_header=True, padding=(0, 1))
        table.add_column("Agent", style="bold cyan")
        table.add_column("Role", style="dim")
        table.add_column("Facts", justify="right")
        table.add_column("Rating", justify="center")

        for agent_id, log in logs.items():
            rating_str = ""
            if log.rating is not None:
                stars = "\u2605" * log.rating + "\u2606" * (5 - log.rating)
                rating_str = f"[yellow]{stars}[/yellow]"
            if log.feedback:
                rating_str += " [dim]+feedback[/dim]"
            table.add_row(
                agent_id,
                log.role,
                str(len(log.facts)),
                rating_str,
            )

        self.console.print(table)
        self.console.print(
            "[dim]Use /logs <id> to view details, /rate <id> <1-5> to rate[/dim]"
        )

    def print_agent_log(
        self, log: AgentLog, metrics: list[CallMetrics] | None = None
    ) -> None:
        """Detailed view of a single agent's output."""
        lines: list[str] = []
        for topic, value in log.facts.items():
            lines.append(f"[bold cyan]{topic}[/bold cyan] = {value}")

        if metrics:
            lines.append("")
            total_in = sum(m.input_tokens for m in metrics)
            total_out = sum(m.output_tokens for m in metrics)
            total_cost = sum(m.cost_usd for m in metrics)
            total_latency = sum(m.latency_ms for m in metrics)
            lines.append(
                f"[dim]Input: {total_in:,} tokens  "
                f"Output: {total_out:,} tokens  "
                f"Cost: ${total_cost:.4f}  "
                f"Latency: {total_latency:.0f}ms[/dim]"
            )

        if log.rating is not None:
            stars = "\u2605" * log.rating + "\u2606" * (5 - log.rating)
            lines.append(f"\n[yellow]Rating: {stars}[/yellow]")
        if log.feedback:
            lines.append(f"[yellow]Feedback: {log.feedback}[/yellow]")

        self.console.print(
            Panel(
                "\n".join(lines),
                title=f"[bold]{log.role}[/bold] ({log.agent_id})",
                box=box.ROUNDED,
            )
        )

    def print_facts(self, result: GroveResult) -> None:
        """Show root knowledge."""
        if not result.facts:
            self.console.print("[dim](no facts)[/dim]")
            return
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        table.add_column("Topic", style="bold cyan")
        table.add_column("Value", style="white")
        for topic, (value, _ver) in sorted(result.facts.items()):
            display = str(value)
            if len(display) > 100:
                display = display[:97] + "..."
            table.add_row(topic, display)
        self.console.print(
            Panel(table, title="[bold]Root Knowledge[/bold]", box=box.ROUNDED)
        )

    def print_tree(self, tree: TreeEngine) -> None:
        root = tree.get_root()
        rich_tree = Tree(f"[bold]{root.role}[/bold] [dim]({root.agent_id})[/dim]")
        self._build_rich_tree(root, rich_tree)
        self.console.print(
            Panel(rich_tree, title="[bold]Agent Tree[/bold]", box=box.ROUNDED)
        )

    def print_grove_view(
        self,
        tree: TreeEngine,
        active_agents: set[str] | None = None,
        fold_engine=None,
    ) -> None:
        """Print the decorated Grove View with [ACTIVE], [ASSERT], [FOLDED] tags."""
        root = tree.get_root()
        active = active_agents or set()

        def _decorations(node: AgentNode) -> str:
            tags: list[str] = []
            if node.agent_id in active:
                tags.append("[bold yellow][ACTIVE][/bold yellow]")
            fact_count = node.knowledge.get_fact_count()
            if fact_count > 0:
                tags.append(f"[green][ASSERT:{fact_count}][/green]")
            if fold_engine is not None:
                fold_count = fold_engine.get_fold_count()
                if fold_count > 0:
                    tags.append(f"[blue][FOLDED:{fold_count}][/blue]")
            pressure = node.knowledge.get_knowledge_pressure()
            if pressure > 0.7:
                tags.append(f"[red][PRESSURE:{pressure:.0%}][/red]")
            return " ".join(tags)

        def _build(node: AgentNode, parent_tree: Tree) -> None:
            decos = _decorations(node)
            for child in node.children:
                style = "bold yellow" if child.agent_id in active else "bold"
                label = f"[{style}]{child.role}[/{style}] [dim]({child.agent_id})[/dim] {decos}"
                child_tree = parent_tree.add(label)
                _build(child, child_tree)

        root_decos = _decorations(root)
        root_style = "bold yellow" if root.agent_id in active else "bold"
        rich_tree = Tree(
            f"[{root_style}]{root.role}[/{root_style}] "
            f"[dim]({root.agent_id})[/dim] {root_decos}"
        )
        _build(root, rich_tree)

        # Summary line
        total_facts = sum(
            n.knowledge.get_fact_count()
            for n in [tree.get_node(nid) for nid in tree.get_all_node_ids()]
            if n is not None
        )
        total_nodes = len(tree.get_all_node_ids())
        fold_count = fold_engine.get_fold_count() if fold_engine else 0

        summary = (
            f"Nodes: [bold]{total_nodes}[/bold] | "
            f"Facts: [bold]{total_facts}[/bold] | "
            f"Folds: [bold]{fold_count}[/bold] | "
            f"Active: [bold]{len(active)}[/bold]"
        )

        self.console.print(
            Panel(
                rich_tree,
                title="[bold green]Grove View[/bold green]",
                subtitle=summary,
                box=box.DOUBLE,
                style="green",
            )
        )

    # -- RLHF --

    def print_rating(self, agent_id: str, rating: int) -> None:
        stars = "\u2605" * rating + "\u2606" * (5 - rating)
        self.console.print(
            f"  [yellow]{stars}[/yellow] Rated [bold]{agent_id}[/bold]"
        )

    def prompt_feedback(self, agent_id: str) -> str | None:
        """Prompt for free-text redirect feedback."""
        self.console.print(
            f"[bold]Feedback for {agent_id}:[/bold] "
            "[dim](What should this agent do differently?)[/dim]"
        )
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return None
        return text if text else None

    def print_feedback_saved(self, agent_id: str) -> None:
        self.console.print(
            f"  [green]Feedback saved for[/green] [bold]{agent_id}[/bold]"
        )

    # -- Chat --

    def print_chat_reply(self, reply: str) -> None:
        """Display a conversational chat reply."""
        self.console.print()
        self.console.print(Panel(reply, box=box.ROUNDED, style="cyan"))
        if self._collector:
            calls = self._collector.get_calls()
            if calls:
                last = calls[-1]
                self.console.print(
                    f"  [dim][{last.input_tokens} in / {last.output_tokens} out "
                    f"/ ${last.cost_usd:.4f}][/dim]"
                )

    def print_agent_reply(self, agent_id: str, facts_updated: dict[str, str]) -> None:
        """Display a SAG-based agent reply with updated facts."""
        if not facts_updated:
            self.console.print(
                f"  [dim]{agent_id} produced no facts.[/dim]"
            )
            return
        lines = [f"[bold cyan]{t}[/bold cyan] = {v}" for t, v in facts_updated.items()]
        self.console.print(
            Panel(
                "\n".join(lines),
                title=f"[bold]{agent_id}[/bold]",
                box=box.ROUNDED,
                style="cyan",
            )
        )

    # -- Accounting report --

    def print_accounting_report(
        self, report: AccountingReport, echo_mode: bool = False
    ) -> None:
        self.console.print()

        agent_table = Table(
            title="Per-Agent Token Breakdown",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        agent_table.add_column("Agent", style="bold cyan")
        agent_table.add_column("Role", style="dim")
        agent_table.add_column("Calls", justify="right")
        agent_table.add_column("Input", justify="right")
        agent_table.add_column("Output", justify="right")
        agent_table.add_column("Total", justify="right", style="bold")
        agent_table.add_column("Cost", justify="right", style="green")

        for s in report.agent_summaries:
            agent_table.add_row(
                s.agent_id, s.role, str(s.calls),
                f"{s.input_tokens:,}", f"{s.output_tokens:,}",
                f"{s.total_tokens:,}", f"${s.cost_usd:.4f}",
            )

        agent_table.add_section()
        agent_table.add_row(
            "[bold]TOTAL[/bold]", "",
            str(sum(s.calls for s in report.agent_summaries)),
            f"{report.total_input_tokens:,}",
            f"{report.total_output_tokens:,}",
            f"[bold]{report.total_tokens:,}[/bold]",
            f"[bold green]${report.total_cost_usd:.4f}[/bold green]",
        )
        self.console.print(agent_table)

        if report.message_metrics:
            self.console.print()
            msg_table = Table(
                title="SAG Communication Savings",
                box=box.ROUNDED,
                show_header=True,
                padding=(0, 1),
            )
            msg_table.add_column("Message Route", style="dim")
            msg_table.add_column("SAG", justify="right")
            msg_table.add_column("JSON", justify="right")
            msg_table.add_column("Saved", justify="right")

            for m in report.message_metrics:
                route = f"{m.source} -> {m.destination}"
                pct = f"{m.percent_saved:.0f}%"
                if m.tokens_saved >= 0:
                    saved_str = f"[green]{m.tokens_saved} ({pct})[/green]"
                else:
                    saved_str = f"[red]{m.tokens_saved} ({pct})[/red]"
                msg_table.add_row(route, str(m.sag_tokens), str(m.json_tokens), saved_str)

            msg_table.add_section()
            pct = f"{report.wire_savings_percent:.0f}%"
            if report.total_wire_savings >= 0:
                total_str = f"[bold green]{report.total_wire_savings} ({pct})[/bold green]"
            else:
                total_str = f"[bold red]{report.total_wire_savings} ({pct})[/bold red]"
            msg_table.add_row(
                "[bold]TOTAL[/bold]",
                str(report.total_sag_tokens),
                str(report.total_json_tokens),
                total_str,
            )
            self.console.print(msg_table)

            if report.total_cost_usd > 0 and report.total_tokens > 0:
                cost_per_token = report.total_cost_usd / report.total_tokens
                json_extra = report.total_wire_savings
                json_cost = json_extra * cost_per_token
                nl_extra = int(report.total_json_tokens * report.nl_multiplier) - report.total_sag_tokens
                nl_cost = nl_extra * cost_per_token
                self.console.print(
                    f"\n  If JSON: +{json_extra:,} tokens (${json_cost:.4f} more)"
                )
                self.console.print(
                    f"  If NL:   ~{nl_extra:,} tokens (${nl_cost:.4f} more)"
                )

        if echo_mode:
            self.console.print("\n  [dim](echo mode -- no API costs)[/dim]")

    # -- Phase 2: Code Generation UI --

    def prompt_codegen(self) -> bool:
        """Ask user if they want to generate code from the analysis results."""
        self.console.print()
        while True:
            self.console.print(
                "[bold]Generate code from these results?[/bold] [dim](Y/n)[/dim]"
            )
            answer = self._wait_for_input("> ")
            if answer is None:
                return False
            if self._handle_prompt_command(answer):
                continue
            return answer.lower() in ("", "y", "yes")

    def print_clarification_questions(self, questions: list[str], summary: str) -> None:
        """Show clarification questions from the root agent."""
        if summary:
            self.console.print(f"\n  [dim]{summary}[/dim]")
        self.console.print()
        self.console.print(
            Panel(
                "\n".join(f"  [bold]{i+1}.[/bold] {q}" for i, q in enumerate(questions)),
                title="[bold yellow]Clarification Needed[/bold yellow]",
                box=box.ROUNDED,
                style="yellow",
            )
        )

    def prompt_clarification_answer(self) -> str | None:
        """Prompt user to answer clarification questions."""
        self.console.print(
            "\n[bold]Answer these questions[/bold] [dim](or press Enter to skip and generate anyway)[/dim]"
        )
        try:
            answer = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return None
        return answer if answer else None

    def print_codegen_plan(self, plan) -> None:
        """Show file manifest as a Rich table."""
        from codegen import CodeGenPlan
        plan: CodeGenPlan

        self.console.print()

        # Tech stack summary
        if plan.tech_stack:
            stack_str = ", ".join(f"{k}: [bold]{v}[/bold]" for k, v in plan.tech_stack.items())
            self.console.print(f"  Tech stack: {stack_str}")
        if plan.rationale:
            self.console.print(f"  [dim]{plan.rationale}[/dim]")
        self.console.print()

        table = Table(
            title="Code Generation Plan",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("#", justify="right", width=3, style="dim")
        table.add_column("File", style="bold cyan", min_width=25)
        table.add_column("Language", style="dim", width=12)
        table.add_column("Description", min_width=30)
        table.add_column("Tokens", justify="right", width=6)

        for i, f in enumerate(plan.files, 1):
            desc = f.description
            if len(desc) > 50:
                desc = desc[:47] + "..."
            table.add_row(
                str(i), f.path, f.language, desc, str(f.max_tokens),
            )

        table.add_section()
        total_tokens = sum(f.max_tokens for f in plan.files)
        table.add_row(
            "", f"[bold]{len(plan.files)} files[/bold]", "", "",
            f"[bold]{total_tokens:,}[/bold]",
        )

        self.console.print(table)

    def prompt_confirm_codegen_plan(self) -> bool:
        """Ask user to confirm the code generation plan."""
        self.console.print()
        while True:
            self.console.print(
                "[bold]Proceed with code generation?[/bold] [dim](Y/n)[/dim]"
            )
            try:
                answer = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                return False
            if self._handle_prompt_command(answer):
                continue
            return answer.lower() in ("", "y", "yes")

    def init_codegen_execution(self, plan) -> None:
        """Prepare for live codegen tracking."""
        from codegen import CodeGenPlan
        plan: CodeGenPlan

        self._codegen_file_status: dict[str, str] = {}
        self._codegen_plan = plan
        for f in plan.files:
            self._codegen_file_status[f.path] = "pending"

    def _build_codegen_table(self) -> Table:
        """Build the live codegen status table."""
        table = Table(
            title="Code Generation",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("", width=2)
        table.add_column("File", style="bold cyan", min_width=25)
        table.add_column("Language", style="dim", width=12)
        table.add_column("Cost", justify="right", width=8, style="green")

        if not hasattr(self, "_codegen_plan"):
            return table

        for f in self._codegen_plan.files:
            status = self._codegen_file_status.get(f.path, "pending")
            icon = {"pending": "\u25cb", "running": "\u25cf", "done": "\u2713", "failed": "\u2717"}[
                status
            ]
            style = {
                "pending": "dim", "running": "yellow",
                "done": "green", "failed": "red",
            }[status]

            cost_str = ""
            if self._collector:
                agent_id = f"codegen:{f.path}"
                calls = [
                    c for c in self._collector.get_calls()
                    if c.agent_id == agent_id
                ]
                if calls:
                    total_cost = sum(c.cost_usd for c in calls)
                    cost_str = f"${total_cost:.4f}"

            table.add_row(
                f"[{style}]{icon}[/{style}]",
                f.path,
                f.language,
                cost_str,
            )

        return table

    def on_file_start(self, spec, idx: int, total: int) -> None:
        """Callback when a file generation starts."""
        self._codegen_file_status[spec.path] = "running"
        if self._live:
            self._live.update(self._build_codegen_table())

    def on_file_done(self, gen_file, idx: int, total: int) -> None:
        """Callback when a file generation completes."""
        status = "done" if gen_file.success else "failed"
        self._codegen_file_status[gen_file.spec.path] = status
        if self._live:
            self._live.update(self._build_codegen_table())

    def run_codegen_with_live(
        self, executor, plan, task: str, facts: dict, output_dir: Path,
    ):
        """Execute code generation with a live-updating status display."""
        from codegen import CodeGenResult

        self.init_codegen_execution(plan)
        self.console.print()

        with Live(
            self._build_codegen_table(),
            console=self.console,
            refresh_per_second=4,
        ) as live:
            self._live = live
            result = executor.execute(plan, task, facts, output_dir)
            live.update(self._build_codegen_table())
            self._live = None

        return result

    def print_codegen_result(self, result) -> None:
        """Print code generation summary."""
        from codegen import CodeGenResult
        result: CodeGenResult

        self.console.print()

        status_style = "green" if result.files_failed == 0 else "yellow"
        self.console.print(
            Panel(
                f"Files written: [bold]{result.files_written}[/bold] | "
                f"Files failed: [bold]{result.files_failed}[/bold] | "
                f"Output: [bold]{result.output_dir}[/bold]",
                title=f"[bold {status_style}]Code Generation Complete[/bold {status_style}]",
                box=box.ROUNDED,
                style=status_style,
            )
        )

        # Show any failures
        for f in result.files:
            if not f.success:
                self.console.print(
                    f"  [red]\u2717 {f.spec.path}: {f.error}[/red]"
                )

    def print_codegen_report(self, echo_mode: bool = False) -> None:
        """Print Phase 2 cost report for codegen agents."""
        if not self._collector:
            return

        calls = self._collector.get_calls()
        codegen_calls = [c for c in calls if c.agent_id.startswith("codegen:")]
        if not codegen_calls:
            return

        self.console.print()

        table = Table(
            title="Phase 2: Code Generation Costs",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("Agent", style="bold cyan")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Total", justify="right", style="bold")
        table.add_column("Cost", justify="right", style="green")

        # Group by agent_id
        agent_calls: dict[str, list] = {}
        for c in codegen_calls:
            agent_calls.setdefault(c.agent_id, []).append(c)

        total_in = total_out = 0
        total_cost = 0.0
        for agent_id, acalls in agent_calls.items():
            inp = sum(c.input_tokens for c in acalls)
            out = sum(c.output_tokens for c in acalls)
            cost = sum(c.cost_usd for c in acalls)
            total_in += inp
            total_out += out
            total_cost += cost
            # Show short name
            short = agent_id.replace("codegen:", "")
            table.add_row(
                short, f"{inp:,}", f"{out:,}",
                f"{inp + out:,}", f"${cost:.4f}",
            )

        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"{total_in:,}", f"{total_out:,}",
            f"[bold]{total_in + total_out:,}[/bold]",
            f"[bold green]${total_cost:.4f}[/bold green]",
        )
        self.console.print(table)

        if echo_mode:
            self.console.print("  [dim](echo mode -- no API costs)[/dim]")

    def print_generated_files(self, result) -> None:
        """List generated files with sizes."""
        from codegen import CodeGenResult
        result: CodeGenResult

        table = Table(
            title="Generated Files",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("#", justify="right", width=3, style="dim")
        table.add_column("File", style="bold cyan", min_width=25)
        table.add_column("Status", width=8)
        table.add_column("Size", justify="right", width=10)

        for i, f in enumerate(result.files, 1):
            if f.success:
                size = len(f.content)
                size_str = f"{size:,} chars"
                status = "[green]\u2713[/green]"
            else:
                size_str = "-"
                status = "[red]\u2717[/red]"
            table.add_row(str(i), f.spec.path, status, size_str)

        self.console.print(table)
        self.console.print(f"  Output directory: [bold]{result.output_dir}[/bold]")

    def print_run_result(self, result) -> None:
        """Display the result of a shell command run."""
        style = "green" if result.success else "red"
        self.console.print(
            Panel(
                result.output,
                title=f"[bold]$ {result.command}[/bold] [{'green' if result.success else 'red'}]"
                      f"(exit {result.exit_code})[/{'green' if result.success else 'red'}]",
                box=box.ROUNDED,
                style=style,
            )
        )

    def print_verify_results(self, results) -> None:
        """Display syntax verification results."""
        if not results:
            self.console.print("  [dim]No files to verify.[/dim]")
            return

        passed = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        table = Table(
            title="Syntax Verification",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("", width=2)
        table.add_column("File", style="bold cyan", min_width=25)
        table.add_column("Result", min_width=30)

        for r in results:
            if r.success:
                table.add_row("\u2713", r.command.replace("py_compile ", ""), "[green]OK[/green]")
            else:
                err = r.output.strip()
                if len(err) > 60:
                    err = err[:57] + "..."
                table.add_row(
                    "[red]\u2717[/red]",
                    r.command.replace("py_compile ", ""),
                    f"[red]{err}[/red]",
                )

        self.console.print(table)

        status = "green" if failed == 0 else "yellow"
        self.console.print(
            f"  [{status}]{passed} passed, {failed} failed[/{status}]"
        )

    def print_test_result(self, result) -> None:
        """Display structured test results."""
        from codegen import TestResult
        result: TestResult

        status_style = "green" if result.success else "red"

        table = Table(
            title=f"Test Results ({result.framework})",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("", width=2)
        table.add_column("Test", style="cyan", min_width=30)
        table.add_column("Status", width=8)
        table.add_column("Detail", style="dim", min_width=20)

        for case in result.cases:
            icon = {
                "passed": "[green]\u2713[/green]",
                "failed": "[red]\u2717[/red]",
                "error": "[red]![/red]",
                "skipped": "[yellow]-[/yellow]",
            }.get(case.status, "?")
            status_str = {
                "passed": "[green]PASS[/green]",
                "failed": "[red]FAIL[/red]",
                "error": "[red]ERROR[/red]",
                "skipped": "[yellow]SKIP[/yellow]",
            }.get(case.status, case.status)
            msg = case.message
            if len(msg) > 40:
                msg = msg[:37] + "..."
            table.add_row(icon, case.name, status_str, msg)

        if result.cases:
            self.console.print(table)

        self.console.print(
            Panel(
                f"Passed: [green]{result.passed}[/green] | "
                f"Failed: [red]{result.failed}[/red] | "
                f"Errors: [red]{result.errors}[/red] | "
                f"Skipped: [yellow]{result.skipped}[/yellow] | "
                f"Total: [bold]{result.total}[/bold]",
                title=f"[bold {status_style}]{'Tests Passed' if result.success else 'Tests Failed'}[/bold {status_style}]",
                box=box.ROUNDED,
                style=status_style,
            )
        )

    def print_edit_result(self, file_path: str, summary: str) -> None:
        """Display the result of an edit operation."""
        self.console.print(
            Panel(
                summary,
                title=f"[bold]Edited: {file_path}[/bold]",
                box=box.ROUNDED,
                style="cyan",
            )
        )

    # -- Session display --

    def print_sessions(self, sessions: list[dict]) -> None:
        """Display a table of saved sessions."""
        if not sessions:
            self.console.print("  [dim]No saved sessions.[/dim]")
            return

        table = Table(
            title="Saved Sessions",
            box=box.ROUNDED,
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("ID", style="dim", width=12)
        table.add_column("Task", style="bold cyan", min_width=30)
        table.add_column("Provider", style="dim", width=10)
        table.add_column("Turns", justify="right", width=6)
        table.add_column("Folds", justify="right", width=6)
        table.add_column("Updated", style="dim", width=20)

        import time as _time

        for s in sessions:
            short_id = s["session_id"][:8] + "..."
            task_label = s.get("label") or s.get("task", "")
            if len(task_label) > 40:
                task_label = task_label[:37] + "..."
            updated = _time.strftime(
                "%Y-%m-%d %H:%M", _time.localtime(s["updated_at"])
            ) if s["updated_at"] else "-"
            mode = "[dim]echo[/dim]" if s.get("echo_mode") else s.get("provider", "")
            table.add_row(
                short_id, task_label, mode,
                str(s.get("turns", 0)), str(s.get("folds", 0)),
                updated,
            )

        self.console.print(table)
        self.console.print(
            "  [dim]Use /load <full-id> to resume a session[/dim]"
        )

    def print_session_saved(self, session_id: str, fold_count: int = 0) -> None:
        """Confirm session save."""
        fold_str = f" ({fold_count} folds)" if fold_count else ""
        self.console.print(
            f"  [green]Session saved:[/green] [bold]{session_id[:12]}...[/bold]{fold_str}"
        )

    def print_session_loaded(self, session_data) -> None:
        """Confirm session load with stats."""
        turns = len(session_data.conversation.get("turns", []))
        folds = len(session_data.conversation.get("folds", []))
        has_grove = session_data.grove_result is not None
        has_codegen = session_data.codegen is not None

        parts = [f"task: [bold]{session_data.task[:50]}[/bold]"]
        parts.append(f"turns: {turns}")
        if folds:
            parts.append(f"folds: {folds}")
        if has_grove:
            parts.append("grove: yes")
        if has_codegen:
            parts.append("codegen: yes")

        self.console.print(
            f"  [green]Session loaded:[/green] {' | '.join(parts)}"
        )

    def print_goodbye(self) -> None:
        self.console.print("\n[bold blue]Done![/bold blue]")

    # -- Helpers --

    def _handle_prompt_command(self, raw: str) -> bool:
        """Handle slash commands typed at a Y/n prompt.

        Returns True if the input was a command (caller should re-prompt).
        Returns False if it was a normal Y/n answer.
        """
        cmd = raw.strip()
        if cmd == "/help":
            self.print_help()
            return True
        if cmd in ("/quit", "/exit", "quit", "exit", "q"):
            # Treat as "no" — caller will get False from the prompt
            return False
        if cmd.startswith("/"):
            self.console.print(
                f"  [dim]Command {cmd} is available after this prompt. "
                f"Answer Y/n or type /help.[/dim]"
            )
            return True
        return False

    def _build_rich_tree(self, node: AgentNode, rich_node: Tree) -> None:
        for child in node.children:
            label = f"[bold]{child.role}[/bold] [dim]({child.agent_id})[/dim]"
            child_tree = rich_node.add(label)
            self._build_rich_tree(child, child_tree)
