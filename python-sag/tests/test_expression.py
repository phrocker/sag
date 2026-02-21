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
