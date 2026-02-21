from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sag.context import Context, MapContext
from sag.exceptions import SAGParseException
from sag.guardrail import GuardrailValidator
from sag.model import ActionStatement, Message
from sag.parser import SAGMessageParser
from sag.schema import SchemaRegistry, SchemaValidator


class ErrorType(Enum):
    PARSE = "PARSE"
    ROUTING = "ROUTING"
    SCHEMA = "SCHEMA"
    GUARDRAIL = "GUARDRAIL"


@dataclass(frozen=True)
class ValidationError:
    error_type: ErrorType
    code: str
    message: str


@dataclass(frozen=True)
class SanitizeResult:
    valid: bool
    message: Optional[Message] = None
    errors: list[ValidationError] = field(default_factory=list)


class AgentRegistry:
    def __init__(self):
        self._agents: set[str] = set()

    def register(self, agent_id: str) -> None:
        self._agents.add(agent_id)

    def is_known(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def unregister(self, agent_id: str) -> None:
        self._agents.discard(agent_id)

    def clear(self) -> None:
        self._agents.clear()


class SAGSanitizer:
    def __init__(
        self,
        schema_registry: SchemaRegistry,
        agent_registry: AgentRegistry,
        default_context: Context | None = None,
        strict: bool = True,
    ):
        self._schema_registry = schema_registry
        self._agent_registry = agent_registry
        self._default_context = default_context or MapContext()
        self._strict = strict
        self._schema_validator = SchemaValidator(schema_registry)

    def sanitize(self, raw_input: str) -> SanitizeResult:
        errors: list[ValidationError] = []

        # Layer 1: Grammar Parse
        try:
            message = SAGMessageParser.parse(raw_input)
        except SAGParseException as e:
            return SanitizeResult(
                valid=False,
                errors=[ValidationError(ErrorType.PARSE, "PARSE_ERROR", str(e))],
            )

        # Layer 2: Routing Guard
        routing_errors = self._validate_routing(message)
        errors.extend(routing_errors)
        if self._strict and routing_errors:
            return SanitizeResult(valid=False, message=message, errors=errors)

        # Layer 3: Schema Validate
        schema_errors = self._validate_schemas(message)
        errors.extend(schema_errors)
        if self._strict and schema_errors:
            return SanitizeResult(valid=False, message=message, errors=errors)

        # Layer 4: Guardrail Check
        guardrail_errors = self._validate_guardrails(message)
        errors.extend(guardrail_errors)
        if self._strict and guardrail_errors:
            return SanitizeResult(valid=False, message=message, errors=errors)

        if errors and self._strict:
            return SanitizeResult(valid=False, message=message, errors=errors)

        return SanitizeResult(valid=True, message=message, errors=errors)

    def sanitize_output(self, message: Message) -> SanitizeResult:
        errors: list[ValidationError] = []

        routing_errors = self._validate_routing(message)
        errors.extend(routing_errors)

        schema_errors = self._validate_schemas(message)
        errors.extend(schema_errors)

        guardrail_errors = self._validate_guardrails(message)
        errors.extend(guardrail_errors)

        if errors and self._strict:
            return SanitizeResult(valid=False, message=message, errors=errors)

        return SanitizeResult(valid=True, message=message, errors=errors)

    def _validate_routing(self, message: Message) -> list[ValidationError]:
        errors: list[ValidationError] = []
        header = message.header

        if header.source and not self._agent_registry.is_known(header.source):
            errors.append(
                ValidationError(ErrorType.ROUTING, "UNKNOWN_SOURCE", f"Unknown source agent: {header.source}")
            )

        if header.destination and not self._agent_registry.is_known(header.destination):
            errors.append(
                ValidationError(
                    ErrorType.ROUTING, "UNKNOWN_DESTINATION", f"Unknown destination agent: {header.destination}"
                )
            )

        return errors

    def _validate_schemas(self, message: Message) -> list[ValidationError]:
        errors: list[ValidationError] = []
        for stmt in message.statements:
            if isinstance(stmt, ActionStatement):
                result = self._schema_validator.validate(stmt)
                if not result.is_valid:
                    errors.append(
                        ValidationError(ErrorType.SCHEMA, result.error_code, result.error_message)
                    )
        return errors

    def _validate_guardrails(self, message: Message) -> list[ValidationError]:
        errors: list[ValidationError] = []
        for stmt in message.statements:
            if isinstance(stmt, ActionStatement):
                result = GuardrailValidator.validate(stmt, self._default_context)
                if not result.is_valid:
                    errors.append(
                        ValidationError(ErrorType.GUARDRAIL, result.error_code, result.error_message)
                    )
        return errors
