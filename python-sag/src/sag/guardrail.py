from __future__ import annotations

from typing import Optional

from sag.context import Context
from sag.exceptions import SAGParseException
from sag.expression import ExpressionEvaluator
from sag.model import ActionStatement, ErrorStatement


class ValidationResult:
    def __init__(self, valid: bool, error_code: Optional[str] = None, error_message: Optional[str] = None):
        self._valid = valid
        self._error_code = error_code
        self._error_message = error_message

    @staticmethod
    def success() -> ValidationResult:
        return ValidationResult(True)

    @staticmethod
    def failure(error_code: str, error_message: str) -> ValidationResult:
        return ValidationResult(False, error_code, error_message)

    @property
    def is_valid(self) -> bool:
        return self._valid

    @property
    def error_code(self) -> Optional[str]:
        return self._error_code

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    def to_error_statement(self) -> Optional[ErrorStatement]:
        if self._valid:
            return None
        return ErrorStatement(error_code=self._error_code, message=self._error_message)

    def __repr__(self) -> str:
        if self._valid:
            return "ValidationResult(valid=True)"
        return f"ValidationResult(valid=False, error_code='{self._error_code}', error_message='{self._error_message}')"


class GuardrailValidator:
    @staticmethod
    def validate(action: ActionStatement, context: Context) -> ValidationResult:
        if action is None:
            return ValidationResult.failure("INVALID_ACTION", "Action cannot be null")

        reason = action.reason
        if reason is None or reason.strip() == "":
            return ValidationResult.success()

        if not _is_expression(reason):
            return ValidationResult.success()

        try:
            result = ExpressionEvaluator.evaluate(reason, context)

            if isinstance(result, bool):
                if not result:
                    return ValidationResult.failure("PRECONDITION_FAILED", f"Precondition not met: {reason}")
                return ValidationResult.success()
            else:
                if result is not None:
                    return ValidationResult.success()
                return ValidationResult.failure("PRECONDITION_FAILED", "Expression evaluated to null")
        except SAGParseException as e:
            return ValidationResult.failure("INVALID_EXPRESSION", f"Failed to evaluate precondition: {e}")


def _is_expression(reason: str) -> bool:
    return any(op in reason for op in (">", "<", "==", "!=", ">=", "<=", "&&", "||"))
