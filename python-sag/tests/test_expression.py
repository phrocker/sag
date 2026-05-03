from sag.expression import ExpressionEvaluator
from sag.context import MapContext


def test_evaluate_simple_comparison():
    context = MapContext()
    context.set("balance", 1500)

    result = ExpressionEvaluator.evaluate("balance > 1000", context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_failed_comparison():
    context = MapContext()
    context.set("balance", 400)

    result = ExpressionEvaluator.evaluate("balance > 1000", context)

    assert isinstance(result, bool)
    assert result is False


def test_evaluate_equality():
    context = MapContext()
    context.set("status", "active")

    result = ExpressionEvaluator.evaluate('status == "active"', context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_logical_and():
    context = MapContext()
    context.set("balance", 1500)
    context.set("verified", True)

    result = ExpressionEvaluator.evaluate("(balance > 1000) && (verified == true)", context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_logical_or():
    context = MapContext()
    context.set("balance", 400)
    context.set("verified", True)

    result = ExpressionEvaluator.evaluate("(balance > 1000) || (verified == true)", context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_arithmetic():
    context = MapContext()
    context.set("price", 100)
    context.set("quantity", 5)

    result = ExpressionEvaluator.evaluate("price * quantity", context)

    assert isinstance(result, float)
    assert result == 500.0


def test_evaluate_nested_path():
    context = MapContext()
    context.set("user.balance", 1500)

    result = ExpressionEvaluator.evaluate("user.balance > 1000", context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_boolean_value():
    context = MapContext()
    context.set("active", True)

    result = ExpressionEvaluator.evaluate("active", context)

    assert isinstance(result, bool)
    assert result is True


def test_evaluate_null_value():
    context = MapContext()
    context.set("value", None)

    result = ExpressionEvaluator.evaluate("value == null", context)

    assert isinstance(result, bool)
    assert result is True


# ---------------------------------------------------------------------------
# Phase 7 / SAG 1.2: pathSeg accepts an optional `:suffix` so vertex-id
# style heads (memory:abc, rationale:hex123, etc.) parse as path segments.
# ---------------------------------------------------------------------------

def test_path_with_colon_prefix_greater_than():
    context = MapContext({"memory:abc": {"confidence": 0.9}})
    result = ExpressionEvaluator.evaluate("memory:abc.confidence > 0.5", context)
    assert isinstance(result, bool)
    assert result is True


def test_path_with_colon_prefix_less_than():
    context = MapContext({"memory:abc": {"confidence": 0.9}})
    result = ExpressionEvaluator.evaluate("memory:abc.confidence < 0.5", context)
    assert isinstance(result, bool)
    assert result is False


def test_path_with_rationale_colon_prefix():
    context = MapContext({"rationale:hexabc": {"trust": 0.95}})
    result = ExpressionEvaluator.evaluate(
        "rationale:hexabc.trust >= 0.9", context
    )
    assert result is True


def test_path_with_integer_suffix():
    # `:INT` also valid for positional refs like slot:0, slot:1
    context = MapContext({"slot:0": {"score": 0.8}})
    result = ExpressionEvaluator.evaluate("slot:0.score > 0.5", context)
    assert result is True
