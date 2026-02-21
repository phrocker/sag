from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from sag.model import ActionStatement, ErrorStatement


class ArgType(Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    LIST = "LIST"
    OBJECT = "OBJECT"
    ANY = "ANY"


class ArgumentSpec:
    def __init__(
        self,
        name: str,
        type: ArgType,
        required: bool = True,
        description: str = "",
        *,
        allowed_values: list | None = None,
        pattern: str | None = None,
        min_value: int | float | None = None,
        max_value: int | float | None = None,
    ):
        self.name = name
        self.type = type
        self.required = required
        self.description = description
        self.allowed_values = allowed_values
        self.pattern = pattern
        self.min_value = min_value
        self.max_value = max_value

        if pattern is not None and type != ArgType.STRING:
            raise ValueError(f"pattern constraint only applies to STRING arguments, got {type.value}")
        if min_value is not None or max_value is not None:
            if type not in (ArgType.INTEGER, ArgType.FLOAT):
                raise ValueError(f"range constraints only apply to INTEGER or FLOAT arguments, got {type.value}")


class VerbSchema:
    def __init__(
        self,
        verb_name: str,
        positional_args: list[ArgumentSpec] | None = None,
        named_args: dict[str, ArgumentSpec] | None = None,
        allow_extra_args: bool = False,
    ):
        self.verb_name = verb_name
        self.positional_args = list(positional_args) if positional_args else []
        self.named_args = dict(named_args) if named_args else {}
        self.allow_extra_args = allow_extra_args

    class Builder:
        def __init__(self, verb_name: str):
            self._verb_name = verb_name
            self._positional_args: list[ArgumentSpec] = []
            self._named_args: dict[str, ArgumentSpec] = {}
            self._allow_extra_args = False

        def add_positional_arg(
            self,
            name: str,
            type: ArgType,
            required: bool = True,
            description: str = "",
            *,
            allowed_values: list | None = None,
            pattern: str | None = None,
            min_value: int | float | None = None,
            max_value: int | float | None = None,
        ) -> VerbSchema.Builder:
            self._positional_args.append(ArgumentSpec(
                name, type, required, description,
                allowed_values=allowed_values, pattern=pattern,
                min_value=min_value, max_value=max_value,
            ))
            return self

        def add_named_arg(
            self,
            name: str,
            type: ArgType,
            required: bool = True,
            description: str = "",
            *,
            allowed_values: list | None = None,
            pattern: str | None = None,
            min_value: int | float | None = None,
            max_value: int | float | None = None,
        ) -> VerbSchema.Builder:
            self._named_args[name] = ArgumentSpec(
                name, type, required, description,
                allowed_values=allowed_values, pattern=pattern,
                min_value=min_value, max_value=max_value,
            )
            return self

        def allow_extra_args(self, allow: bool = True) -> VerbSchema.Builder:
            self._allow_extra_args = allow
            return self

        def build(self) -> VerbSchema:
            return VerbSchema(
                verb_name=self._verb_name,
                positional_args=self._positional_args,
                named_args=self._named_args,
                allow_extra_args=self._allow_extra_args,
            )

    def __repr__(self) -> str:
        return (
            f"VerbSchema(verb_name='{self.verb_name}', "
            f"positional_args={len(self.positional_args)}, "
            f"named_args={len(self.named_args)}, "
            f"allow_extra_args={self.allow_extra_args})"
        )


class SchemaRegistry:
    def __init__(self):
        self._schemas: dict[str, VerbSchema] = {}

    def register(self, schema: VerbSchema) -> None:
        self._schemas[schema.verb_name] = schema

    def get_schema(self, verb_name: str) -> Optional[VerbSchema]:
        return self._schemas.get(verb_name)

    def has_schema(self, verb_name: str) -> bool:
        return verb_name in self._schemas

    def unregister(self, verb_name: str) -> None:
        self._schemas.pop(verb_name, None)

    def get_registered_verbs(self) -> set[str]:
        return set(self._schemas.keys())

    def clear(self) -> None:
        self._schemas.clear()

    def size(self) -> int:
        return len(self._schemas)


class SchemaValidationResult:
    def __init__(self, valid: bool, error_code: Optional[str] = None, error_message: Optional[str] = None):
        self._valid = valid
        self._error_code = error_code
        self._error_message = error_message

    @staticmethod
    def success() -> SchemaValidationResult:
        return SchemaValidationResult(True)

    @staticmethod
    def failure(error_code: str, error_message: str) -> SchemaValidationResult:
        return SchemaValidationResult(False, error_code, error_message)

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
            return "SchemaValidationResult(valid=True)"
        return f"SchemaValidationResult(valid=False, error_code='{self._error_code}', error_message='{self._error_message}')"


class SchemaValidator:
    def __init__(self, registry: SchemaRegistry):
        self._registry = registry

    def validate(self, action: ActionStatement) -> SchemaValidationResult:
        if action is None:
            return SchemaValidationResult.failure("INVALID_ACTION", "Action cannot be null")

        verb = action.verb
        schema = self._registry.get_schema(verb)

        if schema is None:
            return SchemaValidationResult.success()

        # Validate positional arguments
        args = action.args
        positional_specs = schema.positional_args

        for i, spec in enumerate(positional_specs):
            if i >= len(args):
                if spec.required:
                    return SchemaValidationResult.failure(
                        "MISSING_ARG",
                        f"Missing required positional argument '{spec.name}' at position {i}",
                    )
            else:
                value = args[i]
                if not _is_type_compatible(value, spec.type):
                    return SchemaValidationResult.failure(
                        "TYPE_MISMATCH",
                        f"Argument '{spec.name}' at position {i} expected type {spec.type.value} but got {_get_type_name(value)}",
                    )
                constraint_result = _validate_value_constraints(value, spec, f"'{spec.name}' at position {i}")
                if constraint_result is not None:
                    return constraint_result

        # Check extra positional args
        if len(args) > len(positional_specs) and not schema.allow_extra_args:
            return SchemaValidationResult.failure(
                "TOO_MANY_ARGS",
                f"Too many positional arguments: expected {len(positional_specs)} but got {len(args)}",
            )

        # Validate named arguments
        named_args = action.named_args
        named_specs = schema.named_args

        # Check for invalid named argument keys
        for key in named_args:
            if key not in named_specs:
                if not schema.allow_extra_args:
                    expected_keys = "', '".join(named_specs.keys())
                    return SchemaValidationResult.failure(
                        "INVALID_ARGS",
                        f"Expected '{expected_keys}', got '{key}'",
                    )

        # Check required named arguments and types
        for key, spec in named_specs.items():
            if key not in named_args:
                if spec.required:
                    return SchemaValidationResult.failure(
                        "MISSING_ARG",
                        f"Missing required named argument '{key}'",
                    )
            else:
                value = named_args[key]
                if not _is_type_compatible(value, spec.type):
                    return SchemaValidationResult.failure(
                        "TYPE_MISMATCH",
                        f"Argument '{key}' expected type {spec.type.value} but got {_get_type_name(value)}",
                    )
                constraint_result = _validate_value_constraints(value, spec, f"'{key}'")
                if constraint_result is not None:
                    return constraint_result

        return SchemaValidationResult.success()


def _validate_value_constraints(
    value: Any, spec: ArgumentSpec, label: str
) -> SchemaValidationResult | None:
    """Return a failure result if *value* violates any constraint on *spec*, else ``None``."""
    if value is None:
        return None

    # Enum constraint
    if spec.allowed_values is not None and value not in spec.allowed_values:
        allowed = ", ".join(repr(v) for v in spec.allowed_values)
        return SchemaValidationResult.failure(
            "VALUE_NOT_ALLOWED",
            f"Argument {label} value {value!r} is not in allowed values [{allowed}]",
        )

    # Pattern constraint (STRING only)
    if spec.pattern is not None and isinstance(value, str):
        if not re.fullmatch(spec.pattern, value):
            return SchemaValidationResult.failure(
                "PATTERN_MISMATCH",
                f"Argument {label} value {value!r} does not match pattern '{spec.pattern}'",
            )

    # Range constraint (INTEGER / FLOAT)
    if spec.min_value is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < spec.min_value:
            return SchemaValidationResult.failure(
                "VALUE_OUT_OF_RANGE",
                f"Argument {label} value {value} is less than minimum {spec.min_value}",
            )
    if spec.max_value is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > spec.max_value:
            return SchemaValidationResult.failure(
                "VALUE_OUT_OF_RANGE",
                f"Argument {label} value {value} is greater than maximum {spec.max_value}",
            )

    return None


def _is_type_compatible(value: Any, expected_type: ArgType) -> bool:
    if value is None:
        return True
    if expected_type == ArgType.ANY:
        return True
    if expected_type == ArgType.STRING:
        return isinstance(value, str)
    elif expected_type == ArgType.INTEGER:
        # Check bool first since Python bool subclasses int
        return isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == ArgType.FLOAT:
        return isinstance(value, float)
    elif expected_type == ArgType.BOOLEAN:
        return isinstance(value, bool)
    elif expected_type == ArgType.LIST:
        return isinstance(value, list)
    elif expected_type == ArgType.OBJECT:
        return isinstance(value, dict)
    return False


def _get_type_name(value: Any) -> str:
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "Boolean"
    elif isinstance(value, int):
        return "Integer"
    elif isinstance(value, float):
        return "Float"
    elif isinstance(value, str):
        return "String"
    elif isinstance(value, list):
        return "List"
    elif isinstance(value, dict):
        return "Object"
    return type(value).__name__
