"""Memory pressure detection and metrics tracking."""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.minifier import MessageMinifier
from sag.model import Message


@dataclass
class MemoryMetrics:
    raw_tokens: int = 0
    actual_tokens: int = 0
    compression_ratio: float = 1.0
    active_folds: int = 0
    tree_depth: int = 0
    total_messages: int = 0
    fold_events: list[str] = field(default_factory=list)


class MemoryMonitor:
    def __init__(self, budget: int = 10000, threshold: float = 0.7):
        self._budget = budget
        self._threshold = threshold
        self._raw_tokens = 0
        self._actual_tokens = 0
        self._active_folds = 0
        self._total_messages = 0
        self._fold_events: list[str] = []

    def record_message(self, message: Message) -> None:
        tokens = MessageMinifier.count_tokens(MessageMinifier.to_minified_string(message))
        self._raw_tokens += tokens
        self._actual_tokens += tokens
        self._total_messages += 1

    def record_fold(self, original_tokens: int, fold_tokens: int, description: str) -> None:
        saved = original_tokens - fold_tokens
        self._actual_tokens -= saved
        self._active_folds += 1
        self._fold_events.append(f"Fold: saved {saved} tokens - {description}")

    def should_fold(self) -> bool:
        return self._actual_tokens >= self._budget * self._threshold

    def get_metrics(self) -> MemoryMetrics:
        ratio = self._actual_tokens / self._raw_tokens if self._raw_tokens > 0 else 1.0
        return MemoryMetrics(
            raw_tokens=self._raw_tokens,
            actual_tokens=self._actual_tokens,
            compression_ratio=ratio,
            active_folds=self._active_folds,
            tree_depth=0,
            total_messages=self._total_messages,
            fold_events=list(self._fold_events),
        )

    @property
    def budget(self) -> int:
        return self._budget

    @property
    def budget_pct(self) -> float:
        return self._actual_tokens / self._budget * 100 if self._budget > 0 else 0
