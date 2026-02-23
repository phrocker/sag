"""Rich TUI for grove execution with callback hooks."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import box

from sag.tree import AgentNode, TreeEngine
from sag.model import Message
from sag.minifier import MessageMinifier
from sag.grove import ChatResponse, GroveResult, StepResult


class TreeUI:
    """Rich TUI that observes grove execution via callbacks."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # -- Static displays --

    def print_header(self) -> None:
        self.console.print()
        self.console.print(
            Panel(
                "[bold blue]SAG Grove Demo[/bold blue] - Multi-Agent Tree Execution\n"
                "Agents process bottom-up: leaves first, root last.\n"
                "Knowledge propagates upward through the tree.",
                box=box.DOUBLE,
                style="blue",
            )
        )
        self.console.print()

    def print_tree(self, tree: TreeEngine) -> None:
        root = tree.get_root()
        rich_tree = Tree(f"[bold]{root.role}[/bold] [dim]({root.agent_id})[/dim]")
        self._build_rich_tree(root, rich_tree)
        self.console.print(Panel(rich_tree, title="[bold]Agent Tree[/bold]", box=box.ROUNDED))
        self.console.print()

    def print_task(self, task: str) -> None:
        self.console.print(Panel(task, title="[bold green]Task[/bold green]", box=box.ROUNDED, style="green"))
        self.console.print()

    # -- Callbacks for Grove --

    def on_agent_start(self, node: AgentNode, task: str) -> None:
        icon = "\u2192" if node.is_leaf else "\u25b6"
        level = "leaf" if node.is_leaf else ("root" if node.is_root else "lead")
        self.console.print(f"  {icon} [bold cyan]{node.role}[/bold cyan] [dim]({node.agent_id})[/dim] [{level}] ...", end="")

    def on_agent_done(self, node: AgentNode, facts: dict[str, str]) -> None:
        self.console.print(f" [bold green]done[/bold green] ({len(facts)} facts)")
        for topic, value in facts.items():
            display = value if len(value) <= 80 else value[:77] + "..."
            self.console.print(f"      [dim]{topic}[/dim] = [italic]{display}[/italic]")

    def on_propagate(self, child: AgentNode, parent: AgentNode, msg: Message) -> None:
        n_stmts = len(msg.statements)
        self.console.print(
            f"      [yellow]\u2191[/yellow] {n_stmts} facts: "
            f"[dim]{child.agent_id}[/dim] \u2192 [dim]{parent.agent_id}[/dim]"
        )
        wire = MessageMinifier.to_minified_string(msg)
        for line in wire.split("\n"):
            self.console.print(f"        [dim]{line}[/dim]")

    # -- Results --

    def print_result(self, result: GroveResult) -> None:
        self.console.print()
        self.console.print(
            Panel(
                f"Agents run: [bold]{result.agents_run}[/bold] | "
                f"Levels: [bold]{result.levels_processed}[/bold] | "
                f"SAG messages: [bold]{len(result.messages)}[/bold] | "
                f"Root facts: [bold]{len(result.facts)}[/bold]",
                title="[bold]Execution Summary[/bold]",
                box=box.ROUNDED,
                style="green",
            )
        )

        if result.facts:
            table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            table.add_column("Topic", style="bold cyan")
            table.add_column("Value", style="white")

            for topic, (value, _ver) in sorted(result.facts.items()):
                display = str(value)
                if len(display) > 100:
                    display = display[:97] + "..."
                table.add_row(topic, display)

            self.console.print(Panel(table, title="[bold]Root Knowledge[/bold]", box=box.ROUNDED))

    def print_goodbye(self) -> None:
        self.console.print("\n[bold blue]Done![/bold blue]")

    # -- Interactive grove displays --

    def print_step_result(self, step: StepResult) -> None:
        status = "[bold green]COMPLETE[/bold green]" if step.is_complete else "[bold yellow]IN PROGRESS[/bold yellow]"
        self.console.print(
            Panel(
                f"Level [bold]{step.level + 1}[/bold] of {step.total_levels} {status}\n"
                f"Agents: {', '.join(step.agents_run)}",
                title="[bold]Step Result[/bold]",
                box=box.ROUNDED,
            )
        )
        if step.facts_produced:
            for agent_id, facts in step.facts_produced.items():
                for topic, value in facts.items():
                    display = value if len(value) <= 80 else value[:77] + "..."
                    self.console.print(f"    [dim]{agent_id}[/dim] {topic} = [italic]{display}[/italic]")

    def print_checkpoint(self, checkpoint_id: str) -> None:
        self.console.print(f"  [green]Checkpoint saved:[/green] [dim]{checkpoint_id}[/dim]")

    def print_rollback(self, checkpoint_id: str) -> None:
        self.console.print(f"  [yellow]Rolled back to:[/yellow] [dim]{checkpoint_id}[/dim]")

    def print_chat_response(self, resp: ChatResponse) -> None:
        self.console.print()
        if resp.facts_updated:
            table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            table.add_column("Topic", style="bold cyan")
            table.add_column("Value", style="white")
            for topic, value in resp.facts_updated.items():
                display = value if len(value) <= 100 else value[:97] + "..."
                table.add_row(topic, display)
            self.console.print(Panel(table, title="[bold]Updated Facts[/bold]", box=box.ROUNDED))
        else:
            self.console.print("[dim](no facts updated)[/dim]")

    def print_node_facts(self, agent_id: str, facts: dict) -> None:
        if not facts:
            self.console.print(f"  [dim]{agent_id}: (no facts)[/dim]")
            return
        self.console.print(f"  [bold cyan]{agent_id}[/bold cyan]:")
        for topic, (value, ver) in sorted(facts.items()):
            display = str(value)
            if len(display) > 80:
                display = display[:77] + "..."
            self.console.print(f"    {topic} [dim]v{ver}[/dim] = [italic]{display}[/italic]")

    # -- Helpers --

    def _build_rich_tree(self, node: AgentNode, rich_node: Tree) -> None:
        for child in node.children:
            label = f"[bold]{child.role}[/bold] [dim]({child.agent_id})[/dim]"
            child_tree = rich_node.add(label)
            self._build_rich_tree(child, child_tree)
