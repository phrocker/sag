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


# --- operator precedence ---------------------------------------------------
#
# ANTLR resolves left-recursive alternatives by their order in the grammar: the
# first alternative binds most tightly. SAG.g4 originally listed them
# loosest-first, which inverted the entire ladder — `2+3*4` evaluated to 20 and
# `1==1&&2==2` to False — and no test noticed, because every existing case used
# a single operator. These pin the ordering itself.


def test_multiplication_binds_tighter_than_addition():
    assert ExpressionEvaluator.evaluate("2+3*4", MapContext()) == 14
    assert ExpressionEvaluator.evaluate("2*3+4", MapContext()) == 10


def test_division_binds_tighter_than_subtraction():
    assert ExpressionEvaluator.evaluate("10-2*3", MapContext()) == 4
    assert ExpressionEvaluator.evaluate("10-6/2", MapContext()) == 7


def test_parentheses_still_override_precedence():
    assert ExpressionEvaluator.evaluate("(2+3)*4", MapContext()) == 20


def test_comparison_binds_tighter_than_and():
    assert ExpressionEvaluator.evaluate("1==1&&2==2", MapContext()) is True
    assert ExpressionEvaluator.evaluate("1==1&&2==3", MapContext()) is False


def test_arithmetic_binds_tighter_than_comparison():
    assert ExpressionEvaluator.evaluate("1+2==3", MapContext()) is True


def test_and_binds_tighter_than_or():
    # Reads as true || (false && false). Under the inverted ladder this grouped
    # as (true || false) && false and returned False.
    assert ExpressionEvaluator.evaluate("true||false&&false", MapContext()) is True
    assert ExpressionEvaluator.evaluate("false&&false||true", MapContext()) is True


def test_a_realistic_guardrail_binds_as_written():
    """The shape that makes this a security concern rather than a maths one: a
    BECAUSE clause is the last layer of the sanitizer, so a guardrail that reads
    correctly but binds wrongly fails with no diagnostic."""
    context = MapContext()
    context.set("role", "admin")
    context.set("env", "prod")

    assert ExpressionEvaluator.evaluate('role=="admin"&&env=="prod"', context) is True

    context.set("env", "staging")
    assert ExpressionEvaluator.evaluate('role=="admin"&&env=="prod"', context) is False


def test_threshold_and_counter_guardrail():
    context = MapContext()
    context.set("approvals", 12)
    context.set("rejections", 0)

    assert ExpressionEvaluator.evaluate("approvals>=10&&rejections==0", context) is True

    context.set("rejections", 1)
    assert ExpressionEvaluator.evaluate("approvals>=10&&rejections==0", context) is False
