#!/usr/bin/env python3
"""SAG Grove Demo - Multi-agent tree execution."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.tree import TreeEngine
from sag.grove import EchoAgentRunner, Grove, LLMAgentRunner
from tree_ui import TreeUI

# ---------------------------------------------------------------------------
# Software dev grove configuration
# ---------------------------------------------------------------------------

AGENT_PROMPTS = {
    "pm": (
        "You are a Project Manager. Synthesize reports from your Design Lead, "
        "Engineering Lead, and QA Lead into a coherent project plan. "
        "Focus on timeline, risks, and key decisions."
    ),
    "design-lead": (
        "You are a Design Lead. Synthesize UI and UX specialist reports into "
        "a unified design strategy. Focus on design system coherence and user experience."
    ),
    "eng-lead": (
        "You are an Engineering Lead. Synthesize API and Frontend specialist reports "
        "into an architecture plan. Focus on system design, tech stack, and integration points."
    ),
    "qa-lead": (
        "You are a QA Lead. Synthesize Testing and Security specialist reports "
        "into a quality assurance plan. Focus on coverage, risk areas, and compliance."
    ),
    "ui": (
        "You are a UI specialist. Analyze the visual components, layout, "
        "design system, and responsive behavior needed for the given task."
    ),
    "ux": (
        "You are a UX specialist. Analyze user flows, accessibility, "
        "information architecture, and interaction patterns for the given task."
    ),
    "api": (
        "You are an API architect. Design the endpoints, data models, "
        "authentication, rate limiting, and API contracts for the given task."
    ),
    "frontend": (
        "You are a Frontend architect. Design the component architecture, "
        "state management, routing, and client-side patterns for the given task."
    ),
    "test": (
        "You are a Test strategist. Design the testing strategy including "
        "unit, integration, e2e tests, coverage goals, and CI pipeline for the given task."
    ),
    "security": (
        "You are a Security analyst. Analyze threats, required security controls, "
        "authentication/authorization patterns, and compliance needs for the given task."
    ),
}

AGENT_TOPICS = {
    "pm": ["project.plan", "project.risks", "project.timeline"],
    "design-lead": ["design.strategy", "design.system"],
    "eng-lead": ["engineering.architecture", "engineering.stack"],
    "qa-lead": ["quality.plan", "quality.risks"],
    "ui": ["ui.components", "ui.layout"],
    "ux": ["ux.flows", "ux.accessibility"],
    "api": ["api.endpoints", "api.auth"],
    "frontend": ["frontend.components", "frontend.state"],
    "test": ["test.strategy", "test.coverage"],
    "security": ["security.threats", "security.controls"],
}


def build_grove_tree() -> TreeEngine:
    """Build the software dev grove tree."""
    tree = TreeEngine()

    tree.add_root(
        "pm", "Project Manager",
        prompt=AGENT_PROMPTS["pm"],
        topics=AGENT_TOPICS["pm"],
    )

    for lead_id, lead_role, children in [
        ("design-lead", "Design Lead", [("ui", "UI Agent"), ("ux", "UX Agent")]),
        ("eng-lead", "Engineering Lead", [("api", "API Agent"), ("frontend", "Frontend Agent")]),
        ("qa-lead", "QA Lead", [("test", "Test Agent"), ("security", "Security Agent")]),
    ]:
        tree.add_child(
            "pm", lead_id, lead_role,
            prompt=AGENT_PROMPTS[lead_id],
            topics=AGENT_TOPICS[lead_id],
        )
        for child_id, child_role in children:
            tree.add_child(
                lead_id, child_id, child_role,
                prompt=AGENT_PROMPTS[child_id],
                topics=AGENT_TOPICS[child_id],
            )

    return tree


# ---------------------------------------------------------------------------
# Provider setup
# ---------------------------------------------------------------------------

PROVIDER_DEFAULTS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

ENV_KEY_NAMES = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="SAG Grove Demo - Multi-Agent Tree Execution")
    parser.add_argument("task", nargs="?", default="Build a REST API for task management with user authentication",
                        help="Task to assign to the grove")
    parser.add_argument("--provider", choices=["claude", "openai"], default="claude", help="LLM provider")
    parser.add_argument("--api-key", help="API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    parser.add_argument("--model", default=None, help="Model to use")
    parser.add_argument("--no-api", action="store_true", help="Run without LLM API (echo mode)")
    args = parser.parse_args()

    ui = TreeUI()
    ui.print_header()

    # Build tree
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
            ui.console.print(f"[dim]Set {env_key} or use --api-key to enable {args.provider}.[/dim]\n")

    if runner is None:
        runner = EchoAgentRunner()
        if not args.no_api:
            pass  # already printed warning
        else:
            ui.console.print("[dim]Running in echo mode (--no-api)[/dim]\n")

    # Show task
    ui.print_task(args.task)

    # Execute
    grove = Grove(
        tree,
        runner,
        on_agent_start=ui.on_agent_start,
        on_agent_done=ui.on_agent_done,
        on_propagate=ui.on_propagate,
    )

    result = grove.execute(args.task)

    # Show results
    ui.print_result(result)
    ui.print_goodbye()


if __name__ == "__main__":
    main()
