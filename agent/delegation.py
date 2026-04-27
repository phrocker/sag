"""Automatic delegation: parse DELEGATE statements and re-engage child agents.

The root agent's chat response may contain:
    DELEGATE <agent-id> "<question>"

This module parses those statements, runs the specified child agent,
and returns the results for synthesis.
"""

from __future__ import annotations

import re
from typing import Any


# Pattern: DELEGATE agent-id "question text"
_DELEGATE_RE = re.compile(
    r'DELEGATE\s+([\w-]+)\s+"([^"]+)"',
    re.MULTILINE,
)


DELEGATION_PROMPT_AUGMENTATION = """\

When a question requires specialized knowledge from a child agent, \
you may delegate by including in your response:
DELEGATE <agent-id> "<question>"

The child agent will be run and its response will be fed back to you \
for synthesis. You can delegate to multiple agents in a single response.
Available agents: {agent_ids}
"""


def parse_delegations(text: str) -> list[tuple[str, str]]:
    """Extract DELEGATE statements from text.

    Returns list of (agent_id, question) tuples.
    """
    return _DELEGATE_RE.findall(text)


def process_delegations(
    reply_text: str,
    tree: Any,
    runner: Any,
) -> list[dict[str, Any]]:
    """Parse DELEGATE statements from a reply and execute child agents.

    Returns a list of delegation result dicts.
    """
    delegations = parse_delegations(reply_text)
    if not delegations:
        return []

    results: list[dict[str, Any]] = []
    root = tree.get_root()

    for agent_id, question in delegations:
        node = tree.get_node(agent_id)
        if node is None:
            results.append({
                "agent_id": agent_id,
                "question": question,
                "error": f"Unknown agent: {agent_id}",
                "facts": {},
            })
            continue

        # Build child_facts from the agent's current knowledge
        child_facts: dict[str, str] = {}
        for topic, (value, _ver) in node.knowledge.get_all_facts().items():
            child_facts[topic] = str(value)

        # Run the child agent
        facts = runner.run(node, question, child_facts)

        result = {
            "agent_id": agent_id,
            "question": question,
            "facts": facts,
        }
        results.append(result)

    return results


def build_delegation_prompt(tree: Any) -> str:
    """Build the delegation augmentation for the root agent's system prompt."""
    if tree is None:
        return ""
    all_ids = tree.get_all_node_ids()
    root_id = tree.get_root().agent_id
    child_ids = [aid for aid in all_ids if aid != root_id]
    if not child_ids:
        return ""
    return DELEGATION_PROMPT_AUGMENTATION.format(agent_ids=", ".join(child_ids))
