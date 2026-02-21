from __future__ import annotations

from typing import Any, Optional

from sag.model import (
    FoldStatement,
    KnowledgeStatement,
    SubscribeStatement,
    UnsubscribeStatement,
)


def topic_matches(pattern: str, topic: str) -> bool:
    """Match a topic against a pattern with wildcard support.

    - Exact match: ``system.cpu`` matches ``system.cpu``
    - Single-level wildcard: ``system.*`` matches ``system.cpu`` but NOT ``system.disk.usage``
    - Multi-level wildcard: ``system.**`` matches ``system.cpu`` AND ``system.disk.usage``
    """
    if pattern == topic:
        return True

    if pattern == "**":
        return True

    if pattern.endswith(".**"):
        prefix = pattern[:-3]
        return topic == prefix or topic.startswith(prefix + ".")

    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        if not topic.startswith(prefix + "."):
            return False
        remainder = topic[len(prefix) + 1 :]
        return "." not in remainder

    return False


class KnowledgeEngine:
    """Per-agent knowledge propagation engine.

    Manages local facts, subscriptions, peer tracking, and auto-fold
    when fact count exceeds the knowledge budget.
    """

    def __init__(
        self,
        agent_id: str,
        fold_engine: Optional[Any] = None,
        knowledge_budget: int = 1000,
    ):
        self._agent_id = agent_id
        self._fold_engine = fold_engine
        self._knowledge_budget = knowledge_budget

        self._facts: dict[str, tuple[Any, int]] = {}
        self._subscriptions: set[str] = set()
        self._subscribers: dict[str, set[str]] = {}
        self._version_vectors: dict[str, int] = {}
        self._local_version: int = 0

    # -- Local knowledge --

    def assert_fact(self, topic: str, value: Any) -> KnowledgeStatement:
        self._local_version += 1
        self._facts[topic] = (value, self._local_version)
        return KnowledgeStatement(topic=topic, value=value, version=self._local_version)

    def get_fact(self, topic: str) -> Optional[tuple[Any, int]]:
        return self._facts.get(topic)

    def query_facts(self, pattern: str) -> dict[str, tuple[Any, int]]:
        return {
            t: v for t, v in self._facts.items() if topic_matches(pattern, t)
        }

    # -- Subscriptions --

    def subscribe(self, topic_pattern: str) -> SubscribeStatement:
        self._subscriptions.add(topic_pattern)
        return SubscribeStatement(topic=topic_pattern)

    def unsubscribe(self, topic_pattern: str) -> UnsubscribeStatement:
        self._subscriptions.discard(topic_pattern)
        return UnsubscribeStatement(topic=topic_pattern)

    def add_subscriber(self, agent_id: str, topic_pattern: str) -> None:
        if agent_id not in self._subscribers:
            self._subscribers[agent_id] = set()
        self._subscribers[agent_id].add(topic_pattern)
        if agent_id not in self._version_vectors:
            self._version_vectors[agent_id] = 0

    def remove_subscriber(self, agent_id: str, topic_pattern: str) -> None:
        if agent_id in self._subscribers:
            self._subscribers[agent_id].discard(topic_pattern)
            if not self._subscribers[agent_id]:
                del self._subscribers[agent_id]

    def is_interested(self, topic: str) -> bool:
        return any(topic_matches(p, topic) for p in self._subscriptions)

    # -- Propagation --

    def compute_delta(self, peer_id: str) -> list[KnowledgeStatement]:
        last_seen = self._version_vectors.get(peer_id, 0)
        patterns = self._subscribers.get(peer_id, set())
        if not patterns:
            return []

        delta: list[KnowledgeStatement] = []
        for topic, (value, version) in self._facts.items():
            if version <= last_seen:
                continue
            if any(topic_matches(p, topic) for p in patterns):
                delta.append(
                    KnowledgeStatement(topic=topic, value=value, version=version)
                )

        delta.sort(key=lambda k: k.version)
        return delta

    def apply_incoming(
        self, statements: list[KnowledgeStatement], source_id: str
    ) -> list[KnowledgeStatement]:
        applied: list[KnowledgeStatement] = []
        for stmt in statements:
            existing = self._facts.get(stmt.topic)
            if existing is None or stmt.version > existing[1]:
                self._facts[stmt.topic] = (stmt.value, stmt.version)
                applied.append(stmt)
        return applied

    def acknowledge_sync(self, peer_id: str, up_to_version: int) -> None:
        self._version_vectors[peer_id] = max(
            self._version_vectors.get(peer_id, 0), up_to_version
        )

    # -- Auto-fold --

    def get_knowledge_pressure(self) -> float:
        if self._knowledge_budget <= 0:
            return 0.0
        return len(self._facts) / self._knowledge_budget

    def _auto_fold(self) -> Optional[FoldStatement]:
        if self._fold_engine is None:
            return None
        if len(self._facts) <= self._knowledge_budget:
            return None

        min_acked = self._min_acked_version()

        foldable = [
            (topic, value, version)
            for topic, (value, version) in self._facts.items()
            if version <= min_acked
        ]
        foldable.sort(key=lambda x: x[2])

        if not foldable:
            return None

        to_fold = foldable[: len(self._facts) - self._knowledge_budget]
        if not to_fold:
            return None

        state = {topic: value for topic, value, _ in to_fold}
        summary = f"Folded {len(to_fold)} knowledge facts"
        fold_stmt = self._fold_engine.fold([], summary, state=state)

        for topic, _, _ in to_fold:
            del self._facts[topic]

        return fold_stmt

    def _min_acked_version(self) -> int:
        if not self._version_vectors:
            return self._local_version
        return min(self._version_vectors.values())

    # -- Introspection --

    def get_all_facts(self) -> dict[str, tuple[Any, int]]:
        return dict(self._facts)

    def get_fact_count(self) -> int:
        return len(self._facts)

    def get_local_version(self) -> int:
        return self._local_version

    def get_subscriptions(self) -> set[str]:
        return set(self._subscriptions)

    def get_subscribers(self) -> dict[str, set[str]]:
        return {k: set(v) for k, v in self._subscribers.items()}

    def delete_fact(self, topic: str) -> bool:
        """Remove a single fact. Returns True if the fact existed."""
        if topic in self._facts:
            del self._facts[topic]
            return True
        return False

    def load_state(
        self,
        facts: dict[str, tuple[Any, int]],
        local_version: int,
    ) -> None:
        """Bulk-load facts and version for checkpoint restore."""
        self._facts = dict(facts)
        self._local_version = local_version

    def clear(self) -> None:
        self._facts.clear()
        self._subscriptions.clear()
        self._subscribers.clear()
        self._version_vectors.clear()
        self._local_version = 0
