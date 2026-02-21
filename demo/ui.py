"""Rich TUI for the SAG demo with live metrics panel."""

from __future__ import annotations

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from memory import MemoryMetrics


class DemoUI:
    def __init__(self):
        self.console = Console()
        self._events: list[str] = []

    def print_header(self):
        self.console.print()
        self.console.print(
            Panel(
                "[bold blue]SAG Live Demo[/bold blue] - Conversational Agent with Fold/Unfold\n"
                "Type your message and press Enter. Type [bold]RECALL <id>[/bold] to unfold.\n"
                "Press [bold]Ctrl+C[/bold] to exit.",
                box=box.DOUBLE,
                style="blue",
            )
        )
        self.console.print()

    def print_user_message(self, text: str):
        self.console.print(f"[bold green]You:[/bold green] {text}")

    def print_agent_response(self, text: str):
        self.console.print(f"[bold blue]Agent:[/bold blue] {text}")
        self.console.print()

    def print_fold_event(self, event: str):
        self.console.print(f"  [bold yellow][FOLD][/bold yellow] {event}")
        self._events.append(event)

    def print_recall_result(self, fold_id: str, content: str | None):
        if content:
            self.console.print(f"[bold magenta][RECALL {fold_id}][/bold magenta]")
            for line in content.split("\n---\n"):
                self.console.print(f"  [dim]{line}[/dim]")
        else:
            self.console.print(f"[bold red]Fold {fold_id} not found[/bold red]")
        self.console.print()

    def print_metrics(self, metrics: MemoryMetrics):
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key", style="dim")
        table.add_column("Value", style="bold")

        table.add_row("Messages", str(metrics.total_messages))
        table.add_row("Raw tokens", f"{metrics.raw_tokens:,}")
        table.add_row("Actual tokens", f"{metrics.actual_tokens:,}")
        table.add_row("Compression", f"{metrics.compression_ratio:.1%}")
        table.add_row("Active folds", str(metrics.active_folds))

        self.console.print(
            Panel(table, title="[bold]Memory Metrics[/bold]", box=box.ROUNDED, style="cyan", width=40)
        )

    def print_error(self, message: str):
        self.console.print(f"[bold red]Error:[/bold red] {message}")

    def print_goodbye(self):
        self.console.print("\n[bold blue]Goodbye![/bold blue]")
