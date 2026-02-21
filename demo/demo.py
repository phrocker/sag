#!/usr/bin/env python3
"""SAG Live Demo - Main entry point."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from root_agent import RootAgent
from ui import DemoUI

PROVIDER_DEFAULTS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

ENV_KEY_NAMES = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def main():
    parser = argparse.ArgumentParser(description="SAG Live Demo - Chatbot with fold/unfold")
    parser.add_argument("--provider", choices=["claude", "openai"], default="claude", help="LLM provider")
    parser.add_argument("--api-key", help="API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    parser.add_argument("--model", default=None, help="Model to use (default depends on provider)")
    parser.add_argument("--budget", type=int, default=10000, help="Token budget")
    parser.add_argument("--threshold", type=float, default=0.7, help="Fold threshold (0-1)")
    parser.add_argument("--no-api", action="store_true", help="Run without LLM API (echo mode)")
    args = parser.parse_args()

    model = args.model or PROVIDER_DEFAULTS[args.provider]

    ui = DemoUI()
    ui.print_header()

    # Set up LLM client
    client = None
    if not args.no_api:
        env_key = ENV_KEY_NAMES[args.provider]
        api_key = args.api_key or os.environ.get(env_key)
        if api_key:
            if args.provider == "openai":
                from openai_client import OpenAIClient
                client = OpenAIClient(api_key=api_key, model=model)
            else:
                from claude_client import ClaudeClient
                client = ClaudeClient(api_key=api_key, model=model)
            ui.console.print(f"[dim]Using {args.provider} model: {model}[/dim]")
        else:
            ui.console.print("[yellow]No API key found. Running in echo mode.[/yellow]")
            ui.console.print(f"[dim]Set {env_key} or use --api-key to enable {args.provider}.[/dim]")

    ui.console.print(f"[dim]Budget: {args.budget:,} tokens | Threshold: {args.threshold:.0%}[/dim]")
    ui.console.print()

    agent = RootAgent(claude_client=client, budget=args.budget, threshold=args.threshold)

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            # Handle RECALL command
            if user_input.upper().startswith("RECALL "):
                fold_id = user_input.split(" ", 1)[1].strip()
                content = agent.process_recall(fold_id)
                ui.print_recall_result(fold_id, content)
                continue

            # Process normal input
            response, fold_events = agent.process_input(user_input)

            # Show fold events
            for event in fold_events:
                ui.print_fold_event(event)

            # Show response
            ui.print_agent_response(response)

            # Show metrics
            metrics = agent.memory.get_metrics()
            ui.print_metrics(metrics)

    except KeyboardInterrupt:
        pass

    ui.print_goodbye()


if __name__ == "__main__":
    main()
