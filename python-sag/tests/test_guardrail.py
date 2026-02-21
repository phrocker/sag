from sag.context import MapContext
from sag.guardrail import GuardrailValidator, ValidationResult
from sag.model import ActionStatement


def test_validate_successful_precondition():
    context = MapContext()
    context.set("balance", 1500)

    action = ActionStatement(
        verb="transfer",
        args=[],
        named_args={"amt": 500},
        reason="balance > 1000",
    )

    result = GuardrailValidator.validate(action, context)
    assert result.is_valid is True


def test_validate_failed_precondition():
    context = MapContext()
    context.set("balance", 400)

    action = ActionStatement(
        verb="transfer",
        args=[],
        named_args={"amt": 500},
        reason="balance > 1000",
    )

    result = GuardrailValidator.validate(action, context)
    assert result.is_valid is False
    assert result.error_code == "PRECONDITION_FAILED"
    assert result.error_message is not None


def test_validate_no_reason_clause():
    context = MapContext()

    action = ActionStatement(
        verb="transfer",
        args=[],
        named_args={"amt": 500},
    )

    result = GuardrailValidator.validate(action, context)
    assert result.is_valid is True


def test_validate_string_reason():
    context = MapContext()

    action = ActionStatement(
        verb="transfer",
        args=[],
        named_args={"amt": 500},
        reason="security update",
    )

    result = GuardrailValidator.validate(action, context)
    assert result.is_valid is True


def test_validate_complex_expression():
    context = MapContext()
    context.set("balance", 1500)
    context.set("verified", True)

    action = ActionStatement(
        verb="transfer",
        args=[],
        named_args={"amt": 500},
        reason="(balance > 1000) && (verified == true)",
    )

    result = GuardrailValidator.validate(action, context)
    assert result.is_valid is True


def test_validation_result_to_error_statement():
    result = ValidationResult.failure("PRECONDITION_FAILED", "Balance too low")

    error_stmt = result.to_error_statement()
    assert error_stmt is not None
    assert error_stmt.error_code == "PRECONDITION_FAILED"
    assert error_stmt.message == "Balance too low"
