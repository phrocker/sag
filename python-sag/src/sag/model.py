from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC
from typing import Any, Optional


class Statement(ABC):
    pass


@dataclass(frozen=True)
class Header:
    version: int
    message_id: str
    source: str
    destination: str
    timestamp: int
    correlation: Optional[str] = None
    ttl: Optional[int] = None


@dataclass(frozen=True)
class ActionStatement(Statement):
    verb: str
    args: list[Any] = field(default_factory=list)
    named_args: dict[str, Any] = field(default_factory=dict)
    policy: Optional[str] = None
    policy_expr: Optional[str] = None
    priority: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class QueryStatement(Statement):
    expression: Any = None
    constraint: Optional[Any] = None


@dataclass(frozen=True)
class AssertStatement(Statement):
    path: str = ""
    value: Any = None


@dataclass(frozen=True)
class ControlStatement(Statement):
    condition: Any = None
    then_statement: Optional[Statement] = None
    else_statement: Optional[Statement] = None


@dataclass(frozen=True)
class EventStatement(Statement):
    event_name: str = ""
    args: list[Any] = field(default_factory=list)
    named_args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ErrorStatement(Statement):
    error_code: str = ""
    message: Optional[str] = None


@dataclass(frozen=True)
class FoldStatement(Statement):
    fold_id: str = ""
    summary: str = ""
    state: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class RecallStatement(Statement):
    fold_id: str = ""


@dataclass(frozen=True)
class Message:
    header: Header = None
    statements: list[Statement] = field(default_factory=list)
