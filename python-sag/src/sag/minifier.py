from __future__ import annotations

from typing import Any, Optional

from sag.model import (
    ActionStatement,
    AssertStatement,
    ControlStatement,
    ErrorStatement,
    EventStatement,
    FoldStatement,
    Message,
    QueryStatement,
    RecallStatement,
    Statement,
)


class TokenComparison:
    def __init__(
        self,
        sag_length: int,
        json_length: int,
        sag_tokens: int,
        json_tokens: int,
        tokens_saved: int,
        percent_saved: float,
    ):
        self.sag_length = sag_length
        self.json_length = json_length
        self.sag_tokens = sag_tokens
        self.json_tokens = json_tokens
        self.tokens_saved = tokens_saved
        self.percent_saved = percent_saved

    def __repr__(self) -> str:
        return (
            f"SAG: {self.sag_length} chars ({self.sag_tokens} tokens) vs "
            f"JSON: {self.json_length} chars ({self.json_tokens} tokens) - "
            f"Saved: {self.tokens_saved} tokens ({self.percent_saved:.1f}%)"
        )


class MessageMinifier:
    @staticmethod
    def to_minified_string(message: Message, use_relative_timestamp: bool = False) -> str:
        parts: list[str] = []

        header = message.header
        h = f"H v {header.version} id={header.message_id} src={header.source} dst={header.destination} ts={header.timestamp}"

        if header.correlation is not None:
            h += f" corr={header.correlation}"
        if header.ttl is not None:
            h += f" ttl={header.ttl}"

        parts.append(h)
        parts.append("\n")

        stmts = message.statements
        for i, stmt in enumerate(stmts):
            parts.append(_minify_statement(stmt))
            if i < len(stmts) - 1:
                parts.append(";")

        return "".join(parts)

    @staticmethod
    def count_tokens(sag_message: str) -> int:
        import math
        return math.ceil(len(sag_message) / 4.0)

    @staticmethod
    def compare_with_json(message: Message) -> TokenComparison:
        sag_minified = MessageMinifier.to_minified_string(message)
        json_equivalent = _to_json_equivalent(message)

        sag_tokens = MessageMinifier.count_tokens(sag_minified)
        json_tokens = MessageMinifier.count_tokens(json_equivalent)
        saved = json_tokens - sag_tokens
        percent_saved = (saved * 100.0) / json_tokens if json_tokens > 0 else 0.0

        return TokenComparison(
            sag_length=len(sag_minified),
            json_length=len(json_equivalent),
            sag_tokens=sag_tokens,
            json_tokens=json_tokens,
            tokens_saved=saved,
            percent_saved=percent_saved,
        )


def _minify_statement(stmt: Statement) -> str:
    if isinstance(stmt, ActionStatement):
        return _minify_action(stmt)
    elif isinstance(stmt, QueryStatement):
        return _minify_query(stmt)
    elif isinstance(stmt, AssertStatement):
        return _minify_assert(stmt)
    elif isinstance(stmt, ControlStatement):
        return _minify_control(stmt)
    elif isinstance(stmt, EventStatement):
        return _minify_event(stmt)
    elif isinstance(stmt, ErrorStatement):
        return _minify_error(stmt)
    elif isinstance(stmt, FoldStatement):
        return _minify_fold(stmt)
    elif isinstance(stmt, RecallStatement):
        return _minify_recall(stmt)
    return ""


def _minify_action(action: ActionStatement) -> str:
    parts = [f"DO {action.verb}("]

    # Positional args
    for i, arg in enumerate(action.args):
        parts.append(_minify_value(arg))
        if i < len(action.args) - 1 or action.named_args:
            parts.append(",")

    # Named args
    named_items = list(action.named_args.items())
    for i, (key, val) in enumerate(named_items):
        parts.append(f"{key}={_minify_value(val)}")
        if i < len(named_items) - 1:
            parts.append(",")

    parts.append(")")

    if action.policy is not None:
        parts.append(f" P:{action.policy}")
        if action.policy_expr is not None:
            parts.append(f":{action.policy_expr}")

    if action.priority is not None:
        parts.append(f" PRIO={action.priority}")

    if action.reason is not None:
        parts.append(" BECAUSE ")
        if any(op in action.reason for op in (">", "<", "==", "!=")):
            parts.append(action.reason)
        else:
            parts.append(f'"{_escape_string(action.reason)}"')

    return "".join(parts)


def _minify_query(query: QueryStatement) -> str:
    result = f"Q {query.expression}"
    if query.constraint is not None:
        result += f" WHERE {query.constraint}"
    return result


def _minify_assert(assert_stmt: AssertStatement) -> str:
    return f"A {assert_stmt.path} = {_minify_value(assert_stmt.value)}"


def _minify_control(control: ControlStatement) -> str:
    result = f"IF {control.condition} THEN {_minify_statement(control.then_statement)}"
    if control.else_statement is not None:
        result += f" ELSE {_minify_statement(control.else_statement)}"
    return result


def _minify_event(event: EventStatement) -> str:
    parts = [f"EVT {event.event_name}("]

    for i, arg in enumerate(event.args):
        parts.append(_minify_value(arg))
        if i < len(event.args) - 1 or event.named_args:
            parts.append(",")

    named_items = list(event.named_args.items())
    for i, (key, val) in enumerate(named_items):
        parts.append(f"{key}={_minify_value(val)}")
        if i < len(named_items) - 1:
            parts.append(",")

    parts.append(")")
    return "".join(parts)


def _minify_error(error: ErrorStatement) -> str:
    result = f"ERR {error.error_code}"
    if error.message is not None:
        result += f' "{_escape_string(error.message)}"'
    return result


def _minify_fold(fold: FoldStatement) -> str:
    result = f'FOLD {fold.fold_id} "{_escape_string(fold.summary)}"'
    if fold.state is not None:
        result += f" STATE {_minify_value(fold.state)}"
    return result


def _minify_recall(recall: RecallStatement) -> str:
    return f"RECALL {recall.fold_id}"


def _minify_value(value: Any) -> str:
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        # Match Java's Double.toString behavior for whole numbers
        s = str(value)
        return s
    elif isinstance(value, str):
        return f'"{_escape_string(value)}"'
    elif isinstance(value, list):
        items = ",".join(_minify_value(v) for v in value)
        return f"[{items}]"
    elif isinstance(value, dict):
        members = ",".join(f'"{_escape_string(k)}":{_minify_value(v)}' for k, v in value.items())
        return f"{{{members}}}"
    return str(value)


def _escape_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _to_json_equivalent(message: Message) -> str:
    parts = ["{"]
    h = message.header
    parts.append('"header":{')
    parts.append(f'"version":{h.version},')
    parts.append(f'"messageId":"{h.message_id}",')
    parts.append(f'"source":"{h.source}",')
    parts.append(f'"destination":"{h.destination}",')
    parts.append(f'"timestamp":{h.timestamp}')
    if h.correlation is not None:
        parts.append(f',"correlation":"{h.correlation}"')
    if h.ttl is not None:
        parts.append(f',"ttl":{h.ttl}')
    parts.append("},")

    parts.append('"statements":[')
    for i, stmt in enumerate(message.statements):
        class_name = type(stmt).__name__
        parts.append(f'{{"type":"{class_name}"')
        if isinstance(stmt, ActionStatement):
            parts.append(f',"verb":"{stmt.verb}"')
            if stmt.args:
                parts.append(f',"args":{stmt.args}')
            if stmt.named_args:
                parts.append(f',"namedArgs":{stmt.named_args}')
        parts.append("}")
        if i < len(message.statements) - 1:
            parts.append(",")
    parts.append("]}")

    return "".join(parts)
