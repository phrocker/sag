from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from sag.model import FoldStatement, Message


class FoldEngine:
    def __init__(self):
        self._store: dict[str, list[Message]] = {}

    def fold(self, messages: list[Message], summary: str, state: dict | None = None) -> FoldStatement:
        fold_id = str(uuid.uuid4()).replace("-", "")[:16]

        self._store[fold_id] = list(messages)

        return FoldStatement(fold_id=fold_id, summary=summary, state=state)

    def unfold(self, fold_id: str) -> Optional[list[Message]]:
        messages = self._store.get(fold_id)
        if messages is not None:
            return list(messages)
        return None

    def has_fold(self, fold_id: str) -> bool:
        return fold_id in self._store

    def detect_pressure(self, messages: list[Message], budget: int, threshold: float = 0.7) -> bool:
        from sag.minifier import MessageMinifier

        total_tokens = 0
        for msg in messages:
            minified = MessageMinifier.to_minified_string(msg)
            total_tokens += MessageMinifier.count_tokens(minified)

        return total_tokens >= budget * threshold

    def get_fold_count(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()
