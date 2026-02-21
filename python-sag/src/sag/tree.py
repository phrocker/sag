"""Agent tree topology and knowledge propagation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sag.correlation import CorrelationEngine
from sag.knowledge import KnowledgeEngine


@dataclass
class AgentNode:
    """A node in an agent tree."""

    agent_id: str
    role: str
    parent: Optional[AgentNode] = field(default=None, repr=False)
    children: list[AgentNode] = field(default_factory=list, repr=False)
    knowledge: KnowledgeEngine = field(default=None, repr=False)
    correlation: CorrelationEngine = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.knowledge is None:
            self.knowledge = KnowledgeEngine(self.agent_id)
        if self.correlation is None:
            self.correlation = CorrelationEngine(self.agent_id)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    @property
    def is_root(self) -> bool:
        return self.parent is None


class TreeEngine:
    """Manages a tree of AgentNodes with traversal and knowledge propagation."""

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}
        self._root: Optional[AgentNode] = None

    # -- Node management --

    def add_root(self, agent_id: str, role: str, **metadata: Any) -> AgentNode:
        """Create and set the root node. Raises if a root already exists."""
        if self._root is not None:
            raise ValueError("Tree already has a root node")
        node = AgentNode(agent_id=agent_id, role=role, metadata=metadata)
        self._nodes[agent_id] = node
        self._root = node
        return node

    def add_child(
        self, parent_id: str, agent_id: str, role: str, **metadata: Any
    ) -> AgentNode:
        """Add a child node under the given parent."""
        parent = self._nodes.get(parent_id)
        if parent is None:
            raise KeyError(f"Parent node '{parent_id}' not found")
        if agent_id in self._nodes:
            raise ValueError(f"Node '{agent_id}' already exists")
        node = AgentNode(
            agent_id=agent_id, role=role, parent=parent, metadata=metadata
        )
        parent.children.append(node)
        self._nodes[agent_id] = node
        return node

    def get_node(self, agent_id: str) -> Optional[AgentNode]:
        return self._nodes.get(agent_id)

    def get_root(self) -> AgentNode:
        if self._root is None:
            raise ValueError("Tree has no root node")
        return self._root

    # -- Traversal --

    def get_leaves(self) -> list[AgentNode]:
        return [n for n in self._nodes.values() if n.is_leaf]

    def get_levels_bottom_up(self) -> list[list[AgentNode]]:
        """Return nodes grouped by depth, from deepest (leaves) to root."""
        if self._root is None:
            return []

        # BFS to assign depths
        depth_map: dict[str, int] = {}
        queue: list[tuple[AgentNode, int]] = [(self._root, 0)]
        max_depth = 0

        while queue:
            node, depth = queue.pop(0)
            depth_map[node.agent_id] = depth
            if depth > max_depth:
                max_depth = depth
            for child in node.children:
                queue.append((child, depth + 1))

        # Group by depth, reversed
        levels: list[list[AgentNode]] = [[] for _ in range(max_depth + 1)]
        for agent_id, depth in depth_map.items():
            levels[depth].append(self._nodes[agent_id])

        levels.reverse()
        return levels

    def get_depth(self) -> int:
        """Return the depth of the tree (0 for a single root)."""
        if self._root is None:
            return 0

        def _depth(node: AgentNode) -> int:
            if not node.children:
                return 0
            return 1 + max(_depth(c) for c in node.children)

        return _depth(self._root)

    def get_all_node_ids(self) -> list[str]:
        """Return all node IDs in the tree."""
        return list(self._nodes.keys())

    # -- Knowledge propagation --

    def propagate_up(self, child_id: str) -> list:
        """Propagate knowledge delta from a child to its parent.

        Returns the list of KnowledgeStatements applied to the parent.
        """
        child = self._nodes.get(child_id)
        if child is None:
            raise KeyError(f"Node '{child_id}' not found")
        if child.parent is None:
            return []

        delta = child.knowledge.compute_delta(child.parent.agent_id)
        if not delta:
            return []

        applied = child.parent.knowledge.apply_incoming(delta, child_id)
        if delta:
            max_version = max(s.version for s in delta)
            child.knowledge.acknowledge_sync(child.parent.agent_id, max_version)
        return applied

    def setup_subscriptions(self, pattern: str = "**") -> None:
        """Wire all parent-child pairs so parents subscribe to children's facts."""
        for node in self._nodes.values():
            for child in node.children:
                child.knowledge.add_subscriber(node.agent_id, pattern)

    # -- Visualization --

    def render_ascii(self) -> str:
        """Render an ASCII tree diagram."""
        if self._root is None:
            return "(empty tree)"

        lines: list[str] = []

        def _render(node: AgentNode, prefix: str, is_last: bool) -> None:
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            if node.is_root:
                lines.append(f"{node.role} ({node.agent_id})")
            else:
                lines.append(f"{prefix}{connector}{node.role} ({node.agent_id})")

            child_prefix = prefix + ("    " if is_last else "\u2502   ")
            for i, child in enumerate(node.children):
                _render(child, child_prefix, i == len(node.children) - 1)

        _render(self._root, "", True)
        return "\n".join(lines)
