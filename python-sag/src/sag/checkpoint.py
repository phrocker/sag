"""Checkpoint manager for persisting grove state to disk."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sag.minifier import MessageMinifier
from sag.model import Message
from sag.tree import TreeEngine


@dataclass
class NodeSnapshot:
    """Snapshot of a single agent node's state."""

    agent_id: str
    role: str
    facts: dict[str, tuple[Any, int]]
    local_version: int
    correlation_state: dict[str, str]


@dataclass
class CheckpointMeta:
    """Metadata and payload for a checkpoint."""

    checkpoint_id: str
    task: str
    timestamp: float
    agents_run: int
    current_level: int
    total_levels: int
    node_snapshots: dict[str, NodeSnapshot]
    messages: list[str] = field(default_factory=list)


class CheckpointManager:
    """Serializes and restores grove state to/from JSON files on disk."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        tree: TreeEngine,
        task: str,
        messages: list[Message],
        agents_run: int,
        current_level: int,
        total_levels: int,
    ) -> CheckpointMeta:
        """Snapshot the entire grove state and write it to disk."""
        checkpoint_id = str(uuid.uuid4())

        node_snapshots: dict[str, NodeSnapshot] = {}
        for agent_id in tree.get_all_node_ids():
            node = tree.get_node(agent_id)
            node_snapshots[agent_id] = NodeSnapshot(
                agent_id=agent_id,
                role=node.role,
                facts=node.knowledge.get_all_facts(),
                local_version=node.knowledge.get_local_version(),
                correlation_state=node.correlation.get_state(),
            )

        wire_messages = [
            MessageMinifier.to_minified_string(m) for m in messages
        ]

        meta = CheckpointMeta(
            checkpoint_id=checkpoint_id,
            task=task,
            timestamp=time.time(),
            agents_run=agents_run,
            current_level=current_level,
            total_levels=total_levels,
            node_snapshots=node_snapshots,
            messages=wire_messages,
        )

        path = self._directory / f"{checkpoint_id}.json"
        path.write_text(json.dumps(_meta_to_dict(meta), indent=2))
        return meta

    def load(self, checkpoint_id: str) -> CheckpointMeta:
        """Load a checkpoint from disk by ID."""
        path = self._directory / f"{checkpoint_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint '{checkpoint_id}' not found")
        data = json.loads(path.read_text())
        return _dict_to_meta(data)

    def restore(self, meta: CheckpointMeta, tree: TreeEngine) -> None:
        """Restore a checkpoint's state into a live TreeEngine."""
        for agent_id, snapshot in meta.node_snapshots.items():
            node = tree.get_node(agent_id)
            if node is None:
                continue
            # Restore facts: JSON round-trips tuples as lists
            facts = {
                k: (v[0], v[1]) if isinstance(v, list) else v
                for k, v in snapshot.facts.items()
            }
            node.knowledge.load_state(facts, snapshot.local_version)
            node.correlation.load_state(snapshot.correlation_state)

    def list_checkpoints(self) -> list[CheckpointMeta]:
        """List all checkpoints in the directory, sorted by timestamp."""
        results: list[CheckpointMeta] = []
        for path in self._directory.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                results.append(_dict_to_meta(data))
            except (json.JSONDecodeError, KeyError):
                continue
        results.sort(key=lambda m: m.timestamp)
        return results

    def delete(self, checkpoint_id: str) -> None:
        """Delete a checkpoint file."""
        path = self._directory / f"{checkpoint_id}.json"
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _meta_to_dict(meta: CheckpointMeta) -> dict:
    """Convert CheckpointMeta to a JSON-serializable dict."""
    snapshots = {}
    for agent_id, snap in meta.node_snapshots.items():
        # Convert tuple values to lists for JSON
        facts = {k: list(v) for k, v in snap.facts.items()}
        snapshots[agent_id] = {
            "agent_id": snap.agent_id,
            "role": snap.role,
            "facts": facts,
            "local_version": snap.local_version,
            "correlation_state": snap.correlation_state,
        }
    return {
        "checkpoint_id": meta.checkpoint_id,
        "task": meta.task,
        "timestamp": meta.timestamp,
        "agents_run": meta.agents_run,
        "current_level": meta.current_level,
        "total_levels": meta.total_levels,
        "node_snapshots": snapshots,
        "messages": meta.messages,
    }


def _dict_to_meta(data: dict) -> CheckpointMeta:
    """Reconstruct CheckpointMeta from a JSON-parsed dict."""
    snapshots: dict[str, NodeSnapshot] = {}
    for agent_id, snap_data in data["node_snapshots"].items():
        facts = {
            k: tuple(v) for k, v in snap_data["facts"].items()
        }
        snapshots[agent_id] = NodeSnapshot(
            agent_id=snap_data["agent_id"],
            role=snap_data["role"],
            facts=facts,
            local_version=snap_data["local_version"],
            correlation_state=snap_data.get("correlation_state", {}),
        )
    return CheckpointMeta(
        checkpoint_id=data["checkpoint_id"],
        task=data["task"],
        timestamp=data["timestamp"],
        agents_run=data["agents_run"],
        current_level=data["current_level"],
        total_levels=data["total_levels"],
        node_snapshots=snapshots,
        messages=data.get("messages", []),
    )
