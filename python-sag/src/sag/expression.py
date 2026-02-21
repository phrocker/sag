from __future__ import annotations

import re
from typing import Any

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from sag.context import Context
from sag.exceptions import SAGParseException
from sag.generated.SAGLexer import SAGLexer
from sag.generated.SAGParser import SAGParser


class _ThrowingErrorListener(ErrorListener):
    INSTANCE: _ThrowingErrorListener

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise RuntimeError(f"Syntax error at line {line}:{column} - {msg}")


_ThrowingErrorListener.INSTANCE = _ThrowingErrorListener()


class ExpressionEvaluator:
    @staticmethod
    def evaluate(expression: str, context: Context) -> Any:
        if expression is None or expression.strip() == "":
            return None

        try:
            clean = re.sub(r"\s+", "", expression)

            input_stream = InputStream(clean)
            lexer = SAGLexer(input_stream)
            lexer.removeErrorListeners()
            lexer.addErrorListener(_ThrowingErrorListener.INSTANCE)

            tokens = CommonTokenStream(lexer)
            parser = SAGParser(tokens)
            parser.removeErrorListeners()
            parser.addErrorListener(_ThrowingErrorListener.INSTANCE)

            expr_ctx = parser.expr()
            return _evaluate_expr(expr_ctx, context)
        except Exception as e:
            raise SAGParseException(f"Failed to evaluate expression: {e}", cause=e) from e


def _evaluate_expr(ctx, context: Context) -> Any:
    if isinstance(ctx, SAGParser.OrExprContext):
        left = _evaluate_expr(ctx.left, context)
        right = _evaluate_expr(ctx.right, context)
        return _to_boolean(left) or _to_boolean(right)
    elif isinstance(ctx, SAGParser.AndExprContext):
        left = _evaluate_expr(ctx.left, context)
        right = _evaluate_expr(ctx.right, context)
        return _to_boolean(left) and _to_boolean(right)
    elif isinstance(ctx, SAGParser.RelExprContext):
        left = _evaluate_expr(ctx.left, context)
        right = _evaluate_expr(ctx.right, context)
        op = ctx.op.text
        return _evaluate_relational(left, right, op)
    elif isinstance(ctx, SAGParser.AddExprContext):
        left = _evaluate_expr(ctx.left, context)
        right = _evaluate_expr(ctx.right, context)
        op = ctx.op.text
        return _evaluate_arithmetic(left, right, op)
    elif isinstance(ctx, SAGParser.MulExprContext):
        left = _evaluate_expr(ctx.left, context)
        right = _evaluate_expr(ctx.right, context)
        op = ctx.op.text
        return _evaluate_arithmetic(left, right, op)
    elif isinstance(ctx, SAGParser.PrimaryExprContext):
        return _evaluate_primary(ctx.primary(), context)
    return None


def _evaluate_primary(ctx: SAGParser.PrimaryContext, context: Context) -> Any:
    if ctx.value() is not None:
        return _evaluate_value(ctx.value(), context)
    elif ctx.expr() is not None:
        return _evaluate_expr(ctx.expr(), context)
    return None


def _evaluate_value(ctx, context: Context) -> Any:
    if isinstance(ctx, SAGParser.ValStringContext):
        return _unquote(ctx.STRING().getText())
    elif isinstance(ctx, SAGParser.ValIntContext):
        return int(ctx.INT().getText())
    elif isinstance(ctx, SAGParser.ValFloatContext):
        return float(ctx.FLOAT().getText())
    elif isinstance(ctx, SAGParser.ValBoolContext):
        return ctx.BOOL().getText() == "true"
    elif isinstance(ctx, SAGParser.ValNullContext):
        return None
    elif isinstance(ctx, SAGParser.ValPathContext):
        path = ctx.path().getText()
        return context.get(path)
    return None


def _evaluate_relational(left: Any, right: Any, op: str) -> bool:
    if left is None or right is None:
        if op == "==":
            return left is right
        elif op == "!=":
            return left is not right
        return False

    if op == "==":
        return _compare_equals(left, right)
    elif op == "!=":
        return not _compare_equals(left, right)
    elif op in (">", "<", ">=", "<="):
        if not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
            raise ValueError(f"Cannot compare non-numeric values with {op}")
        return _compare_numbers(left, right, op)
    return False


def _compare_numbers(left: Any, right: Any, op: str) -> bool:
    left_num = float(left)
    right_num = float(right)
    if op == ">":
        return left_num > right_num
    elif op == "<":
        return left_num < right_num
    elif op == ">=":
        return left_num >= right_num
    elif op == "<=":
        return left_num <= right_num
    return False


def _compare_equals(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def _evaluate_arithmetic(left: Any, right: Any, op: str) -> float:
    left_num = _to_double(left)
    right_num = _to_double(right)
    if op == "+":
        return left_num + right_num
    elif op == "-":
        return left_num - right_num
    elif op == "*":
        return left_num * right_num
    elif op == "/":
        if right_num == 0:
            raise ArithmeticError("Division by zero")
        return left_num / right_num
    return 0.0


def _to_double(obj: Any) -> float:
    if isinstance(obj, (int, float)):
        return float(obj)
    raise ValueError(f"Cannot convert to number: {obj}")


def _to_boolean(obj: Any) -> bool:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj != 0
    if isinstance(obj, str):
        return len(obj) > 0
    return obj is not None


def _unquote(quoted: str) -> str:
    if quoted.startswith('"') and quoted.endswith('"'):
        return (
            quoted[1:-1]
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
        )
    return quoted
