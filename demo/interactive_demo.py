#!/usr/bin/env python3
"""SAG Interactive Grove Demo — step-through execution + chat mode."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from rich.console import Console
from rich.panel import Panel
from rich import box

from sag.tree import TreeEngine
from sag.grove import (
    ChatSession,
    EchoAgentRunner,
    Grove,
    InteractiveGrove,
    LLMAgentRunner,
)
from sag.checkpoint import CheckpointManager
from tree_ui import TreeUI

# Reuse tree configuration from tree_demo
from tree_demo import build_grove_tree, PROVIDER_DEFAULTS, ENV_KEY_NAMES


def _run_step_mode(tree: TreeEngine, runner, ui: TreeUI, task: str, cp_dir: str) -> None:
    """Interactive step-through execution."""
    mgr = CheckpointManager(cp_dir)
    ig = InteractiveGrove(
        tree, runner,
        checkpoint_mgr=mgr,
        on_agent_start=ui.on_agent_start,
        on_agent_done=ui.on_agent_done,
        on_propagate=ui.on_propagate,
    )
    levels = ig.setup(task)
    ui.console.print(f"[dim]Tree has {len(levels)} levels to process.[/dim]\n")

    while True:
        try:
            step = ig.step()
        except RuntimeError:
            break

        ui.print_step_result(step)
        ui.console.print()

        if step.is_complete:
            break

        # Interactive prompt between levels
        while True:
            ui.console.print("[bold]Commands:[/bold] [dim](n)ext step | (c)heckpoint | (i)nspect <id> | (e)dit <id> <topic> <value> | (r)ollback <cp_id> | (q)uit[/dim]")
            try:
                cmd = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                ui.console.print("\n[dim]Interrupted[/dim]")
                return

            if not cmd or cmd in ("n", "next"):
                break
            elif cmd in ("c", "checkpoint"):
                cp_id = ig.checkpoint()
                ui.print_checkpoint(cp_id)
            elif cmd.startswith(("i ", "inspect ")):
                parts = cmd.split(maxsplit=1)
                if len(parts) == 2:
                    try:
                        facts = ig.inspect_node(parts[1])
                        ui.print_node_facts(parts[1], facts)
                    except KeyError as e:
                        ui.console.print(f"  [red]{e}[/red]")
            elif cmd.startswith(("e ", "edit ")):
                parts = cmd.split(maxsplit=3)
                if len(parts) == 4:
                    try:
                        ig.edit_fact(parts[1], parts[2], parts[3])
                        ui.console.print(f"  [green]Set {parts[2]} on {parts[1]}[/green]")
                    except KeyError as e:
                        ui.console.print(f"  [red]{e}[/red]")
                else:
                    ui.console.print("  [red]Usage: edit <agent_id> <topic> <value>[/red]")
            elif cmd.startswith(("r ", "rollback ")):
                parts = cmd.split(maxsplit=1)
                if len(parts) == 2:
                    try:
                        ig.rollback(parts[1])
                        ui.print_rollback(parts[1])
                    except FileNotFoundError as e:
                        ui.console.print(f"  [red]{e}[/red]")
            elif cmd in ("q", "quit"):
                return
            else:
                ui.console.print("  [dim]Unknown command[/dim]")

    result = ig.result()
    ui.print_result(result)
    return result


def _run_chat_mode(tree: TreeEngine, runner, ui: TreeUI, task: str, cp_dir: str) -> None:
    """Run grove then enter chat loop with root agent."""
    mgr = CheckpointManager(cp_dir)

    # First do a full grove execution
    ui.console.print("[bold]Phase 1: Running grove...[/bold]\n")
    grove = Grove(
        tree, runner,
        on_agent_start=ui.on_agent_start,
        on_agent_done=ui.on_agent_done,
        on_propagate=ui.on_propagate,
    )
    result = grove.execute(task)
    ui.print_result(result)

    # Enter chat mode
    ui.console.print()
    ui.console.print(
        Panel(
            "Chat with the root agent to refine results.\n"
            "Commands: [bold]checkpoint[/bold], [bold]rollback <id>[/bold], [bold]quit[/bold]",
            title="[bold blue]Chat Mode[/bold blue]",
            box=box.DOUBLE,
            style="blue",
        )
    )

    session = ChatSession(result, tree, runner, checkpoint_mgr=mgr)

    while True:
        try:
            user_input = input("\n[You] > ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.console.print("\n[dim]Goodbye[/dim]")
            return

        if not user_input:
            continue
        elif user_input in ("quit", "exit", "q"):
            return
        elif user_input == "checkpoint":
            cp_id = session.checkpoint()
            ui.print_checkpoint(cp_id)
            continue
        elif user_input.startswith("rollback "):
            cp_id = user_input.split(maxsplit=1)[1]
            try:
                session.rollback(cp_id)
                ui.print_rollback(cp_id)
            except FileNotFoundError as e:
                ui.console.print(f"  [red]{e}[/red]")
            continue

        resp = session.chat(user_input)
        ui.print_chat_response(resp)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAG Interactive Grove Demo")
    parser.add_argument("task", nargs="?", default="Build a REST API for task management",
                        help="Task to assign")
    parser.add_argument("--mode", choices=["step", "chat"], default="step",
                        help="Execution mode: step-through or chat")
    parser.add_argument("--provider", choices=["claude", "openai"], default="claude")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--model", default=None)
    parser.add_argument("--no-api", action="store_true", help="Echo mode")
    parser.add_argument("--checkpoint-dir", default=None,
                        help="Directory for checkpoints (default: temp dir)")
    args = parser.parse_args()

    ui = TreeUI()
    ui.print_header()

    tree = build_grove_tree()
    ui.print_tree(tree)

    # Set up runner
    runner = None
    if not args.no_api:
        model = args.model or PROVIDER_DEFAULTS[args.provider]
        env_key = ENV_KEY_NAMES[args.provider]
        api_key = args.api_key or os.environ.get(env_key)
        if api_key:
            if args.provider == "openai":
                from openai_client import OpenAIClient
                client = OpenAIClient(api_key=api_key, model=model)
            else:
                from claude_client import ClaudeClient
                client = ClaudeClient(api_key=api_key, model=model)
            ui.console.print(f"[dim]Using {args.provider} model: {model}[/dim]\n")
            runner = LLMAgentRunner(client)
        else:
            ui.console.print(f"[yellow]No API key found. Running in echo mode.[/yellow]")
            ui.console.print(f"[dim]Set {env_key} or use --api-key.[/dim]\n")

    if runner is None:
        runner = EchoAgentRunner()
        if args.no_api:
            ui.console.print("[dim]Running in echo mode (--no-api)[/dim]\n")

    ui.print_task(args.task)

    cp_dir = args.checkpoint_dir or tempfile.mkdtemp(prefix="sag_checkpoints_")
    ui.console.print(f"[dim]Checkpoints: {cp_dir}[/dim]\n")

    if args.mode == "step":
        _run_step_mode(tree, runner, ui, args.task, cp_dir)
    else:
        _run_chat_mode(tree, runner, ui, args.task, cp_dir)

    ui.print_goodbye()


if __name__ == "__main__":
    main()
