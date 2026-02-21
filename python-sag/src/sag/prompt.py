"""LLM prompt builder and validate-retry generator for SAG messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sag.exceptions import SAGParseException
from sag.model import ActionStatement, Message
from sag.parser import SAGMessageParser
from sag.schema import SchemaRegistry, SchemaValidator

# ---------------------------------------------------------------------------
# Grammar constant — human-readable EBNF derived from SAG.g4
# ---------------------------------------------------------------------------

_SAG_GRAMMAR_EBNF = """\
message     ::= header NEWLINE body EOF

header      ::= 'H' version msgId src dst timestamp correlation? ttl?
version     ::= 'v' INT
msgId       ::= 'id=' IDENT
src         ::= 'src=' IDENT
dst         ::= 'dst=' IDENT
timestamp   ::= 'ts=' INT
correlation ::= 'corr=' (IDENT | '-')
ttl         ::= 'ttl=' INT

body        ::= statement (';' statement)* ';'?

statement   ::= actionStmt | queryStmt | assertStmt | controlStmt
              | eventStmt | errorStmt | foldStmt | recallStmt

actionStmt  ::= 'DO' verbCall policyClause? priorityClause? reasonClause?
verbCall    ::= IDENT '(' argList? ')'
argList     ::= arg (',' arg)*
arg         ::= value | namedArg
namedArg    ::= IDENT '=' value

reasonClause   ::= 'BECAUSE' (STRING | expr)
queryStmt      ::= 'Q' expr ('WHERE' expr)?
assertStmt     ::= 'A' path '=' value
controlStmt    ::= 'IF' expr 'THEN' statement ('ELSE' statement)?
eventStmt      ::= 'EVT' IDENT '(' argList? ')'
errorStmt      ::= 'ERR' IDENT STRING?
foldStmt       ::= 'FOLD' IDENT STRING ('STATE' object)?
recallStmt     ::= 'RECALL' IDENT

policyClause   ::= 'P:' IDENT (':' expr)?
priorityClause ::= 'PRIO=' PRIORITY

expr  ::= expr '||' expr          -- logical OR
        | expr '&&' expr          -- logical AND
        | expr ('==' | '!=' | '>' | '<' | '>=' | '<=') expr  -- comparison
        | expr ('+' | '-') expr   -- additive
        | expr ('*' | '/') expr   -- multiplicative
        | primary

primary ::= value | '(' expr ')'

value ::= STRING | INT | FLOAT | BOOL | 'null' | path | list | object
path  ::= IDENT ('.' IDENT)*
list  ::= '[' (value (',' value)*)? ']'
object ::= '{' (member (',' member)*)? '}'
member ::= STRING ':' value

-- Lexer tokens
PRIORITY ::= 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'
BOOL     ::= 'true' | 'false'
INT      ::= [0-9]+
FLOAT    ::= [0-9]+ '.' [0-9]+
IDENT    ::= [a-zA-Z] [a-zA-Z0-9_.-]*
STRING   ::= '"' (any char except '"' and '\\', or '\\' followed by any char)* '"'
"""

# ---------------------------------------------------------------------------
# Quick-reference table — one-line template per statement type
# ---------------------------------------------------------------------------

_SAG_QUICK_REFERENCE = """\
Statement quick reference (one per line, separate with ';'):

  Header:    H v 1 id=<id> src=<source> dst=<destination> ts=<timestamp>
  Action:    DO verb(arg1, arg2, name=value)
  Query:     Q expression WHERE constraint
  Assert:    A path = value
  Control:   IF expr THEN statement ELSE statement
  Event:     EVT eventName(arg1, arg2)
  Error:     ERR errorCode "error message"
  Fold:      FOLD foldId "summary" STATE {"key": "value"}
  Recall:    RECALL foldId

Optional action clauses: P:policyName  PRIO=HIGH  BECAUSE "reason"
Priority values: LOW, NORMAL, HIGH, CRITICAL
Values: "string", 42, 3.14, true, false, null, [list], {"object": "value"}, dotted.path
"""

# ---------------------------------------------------------------------------
# Default examples
# ---------------------------------------------------------------------------

_SAG_EXAMPLES = """\
Example SAG messages:

1) Simple action:
   H v 1 id=msg1 src=agent dst=server ts=1700000000
   DO deploy("myapp", env="production")

2) Multi-statement message:
   H v 1 id=msg2 src=planner dst=executor ts=1700000001
   A status = "ready"; DO launch("service-a"); EVT taskStarted("deployment")

3) Query with constraint:
   H v 1 id=msg3 src=monitor dst=db ts=1700000002
   Q server.health WHERE server.region == "us-east"

4) Action with priority and reason:
   H v 1 id=msg4 src=ops dst=infra ts=1700000003
   DO scaleUp("web-tier", count=3) PRIO=HIGH BECAUSE "traffic spike detected"

5) Assert a fact:
   H v 1 id=msg5 src=sensor dst=controller ts=1700000004
   A temperature.reading = 72.5

6) Error response:
   H v 1 id=msg6 src=server dst=client ts=1700000005
   ERR TIMEOUT "Request exceeded 30s limit"

7) Fold for context compression:
   H v 1 id=msg7 src=agent dst=memory ts=1700000006
   FOLD conv-chunk-1 "Discussed deployment plan for Q3" STATE {"decision": "approved"}
"""


# ---------------------------------------------------------------------------
# LLM Client protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMClient(Protocol):
    """Structural type for LLM clients.

    Both ``ClaudeClient`` and ``OpenAIClient`` already satisfy this
    interface — no changes to existing code are required.
    """

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Generation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationResult:
    """Result of a SAG generation attempt."""

    message: Message | None
    raw_text: str
    success: bool
    attempts: int
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema rendering helpers
# ---------------------------------------------------------------------------


def _render_arg_spec(spec: Any) -> str:
    """Render a single argument spec as a function-signature fragment."""
    type_name = spec.type.value
    parts: list[str] = []

    if not spec.required:
        parts.append(f"{spec.name}?: {type_name}")
    else:
        parts.append(f"{spec.name}: {type_name}")

    constraints: list[str] = []
    if spec.allowed_values is not None:
        vals = "|".join(repr(v) for v in spec.allowed_values)
        constraints.append(f"[{vals}]")
    if spec.pattern is not None:
        constraints.append(f"pattern={spec.pattern!r}")
    if spec.min_value is not None:
        constraints.append(f">={spec.min_value}")
    if spec.max_value is not None:
        constraints.append(f"<={spec.max_value}")

    if constraints:
        parts.append(f" {' '.join(constraints)}")

    return "".join(parts)


def _render_verb_signature(schema: Any) -> str:
    """Render a VerbSchema as a function-signature string."""
    arg_parts: list[str] = []
    for spec in schema.positional_args:
        arg_parts.append(_render_arg_spec(spec))
    for spec in schema.named_args.values():
        arg_parts.append(_render_arg_spec(spec))
    sig = ", ".join(arg_parts)
    return f"{schema.verb_name}({sig})"


def _render_schema_docs(registry: SchemaRegistry) -> str:
    """Render all schemas in a registry as documentation."""
    verbs = sorted(registry.get_registered_verbs())
    if not verbs:
        return ""
    lines = ["Available verbs and their signatures:", ""]
    for verb in verbs:
        schema = registry.get_schema(verb)
        if schema is not None:
            lines.append(f"  DO {_render_verb_signature(schema)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Builds a system prompt for LLMs that should emit SAG messages.

    Uses a builder pattern with chainable setters.
    """

    def __init__(self) -> None:
        self._preamble: str | None = None
        self._suffix: str | None = None
        self._schema_registry: SchemaRegistry | None = None
        self._custom_examples: list[str] = []
        self._include_grammar = True
        self._include_quick_reference = True
        self._include_default_examples = True

    # -- Chainable setters --------------------------------------------------

    def set_preamble(self, text: str) -> PromptBuilder:
        """Set introductory text placed before the grammar section."""
        self._preamble = text
        return self

    def set_suffix(self, text: str) -> PromptBuilder:
        """Set closing instructions placed after all other sections."""
        self._suffix = text
        return self

    def set_schema_registry(self, registry: SchemaRegistry) -> PromptBuilder:
        """Include verb schema documentation in the prompt."""
        self._schema_registry = registry
        return self

    def add_example(self, text: str) -> PromptBuilder:
        """Append a custom example to the prompt."""
        self._custom_examples.append(text)
        return self

    def include_grammar(self, include: bool) -> PromptBuilder:
        """Toggle the formal EBNF grammar section."""
        self._include_grammar = include
        return self

    def include_quick_reference(self, include: bool) -> PromptBuilder:
        """Toggle the quick-reference table section."""
        self._include_quick_reference = include
        return self

    def include_default_examples(self, include: bool) -> PromptBuilder:
        """Toggle the built-in example messages section."""
        self._include_default_examples = include
        return self

    # -- Static accessors ---------------------------------------------------

    @staticmethod
    def get_grammar_ebnf() -> str:
        """Return the embedded EBNF grammar string."""
        return _SAG_GRAMMAR_EBNF

    @staticmethod
    def get_quick_reference() -> str:
        """Return the quick-reference table string."""
        return _SAG_QUICK_REFERENCE

    @staticmethod
    def get_default_examples() -> str:
        """Return the default example messages string."""
        return _SAG_EXAMPLES

    # -- Build --------------------------------------------------------------

    def build(self) -> str:
        """Assemble the full system prompt from configured sections."""
        sections: list[str] = []

        if self._preamble:
            sections.append(self._preamble)

        if self._include_grammar:
            sections.append("SAG Grammar (EBNF):\n" + _SAG_GRAMMAR_EBNF)

        if self._include_quick_reference:
            sections.append(_SAG_QUICK_REFERENCE)

        if self._schema_registry is not None:
            docs = _render_schema_docs(self._schema_registry)
            if docs:
                sections.append(docs)

        if self._include_default_examples:
            sections.append(_SAG_EXAMPLES)

        for example in self._custom_examples:
            sections.append(example)

        if self._suffix:
            sections.append(self._suffix)

        return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# SAG Generator — validate-retry loop
# ---------------------------------------------------------------------------


class SAGGenerator:
    """Parse-validate-retry loop around any LLM client.

    Calls the LLM, parses the response as SAG, optionally validates
    action statements against a schema registry, and retries with
    error feedback on failure.
    """

    def __init__(
        self,
        client: LLMClient,
        prompt_builder: PromptBuilder | None = None,
        schema_registry: SchemaRegistry | None = None,
        max_retries: int = 2,
        validate_schema: bool = True,
    ) -> None:
        self._client = client
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._schema_registry = schema_registry
        self._max_retries = max_retries
        self._validate_schema = validate_schema
        self._cached_prompt: str | None = None

        if schema_registry is not None:
            self._prompt_builder.set_schema_registry(schema_registry)

    @property
    def system_prompt(self) -> str:
        """Lazily build and cache the system prompt."""
        if self._cached_prompt is None:
            self._cached_prompt = self._prompt_builder.build()
        return self._cached_prompt

    def invalidate_prompt_cache(self) -> None:
        """Force the system prompt to be rebuilt on next access."""
        self._cached_prompt = None

    def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        system_prompt_override: str | None = None,
    ) -> GenerationResult:
        """Generate a valid SAG message via the LLM with retries.

        Parameters
        ----------
        messages:
            Conversation messages in ``[{"role": ..., "content": ...}]`` form.
        max_tokens:
            Maximum tokens for the LLM response.
        system_prompt_override:
            If provided, use this instead of the cached system prompt.

        Returns
        -------
        GenerationResult
            Contains the parsed message (if successful), raw text,
            attempt count, and any accumulated errors.
        """
        prompt = system_prompt_override if system_prompt_override is not None else self.system_prompt
        # Copy so we don't mutate the caller's list
        conversation = list(messages)
        errors: list[str] = []
        raw_text = ""
        total_attempts = 1 + self._max_retries

        for attempt in range(total_attempts):
            raw_text = self._client.complete(prompt, conversation, max_tokens)

            # --- Parse ---
            try:
                parsed = SAGMessageParser.parse(raw_text)
            except SAGParseException as exc:
                error_msg = f"Parse error: {exc}"
                errors.append(error_msg)
                if attempt < total_attempts - 1:
                    conversation.append({"role": "assistant", "content": raw_text})
                    conversation.append({
                        "role": "user",
                        "content": (
                            f"Your response was not valid SAG. {error_msg}\n"
                            "Please fix the syntax and try again."
                        ),
                    })
                continue

            # --- Schema validation ---
            if self._validate_schema and self._schema_registry is not None:
                validator = SchemaValidator(self._schema_registry)
                schema_error = _validate_message_schema(parsed, validator)
                if schema_error is not None:
                    errors.append(schema_error)
                    if attempt < total_attempts - 1:
                        conversation.append({"role": "assistant", "content": raw_text})
                        conversation.append({
                            "role": "user",
                            "content": (
                                f"SAG parsed OK but schema validation failed: {schema_error}\n"
                                "Please fix the arguments and try again."
                            ),
                        })
                    continue

            return GenerationResult(
                message=parsed,
                raw_text=raw_text,
                success=True,
                attempts=attempt + 1,
                errors=errors,
            )

        # All attempts exhausted
        return GenerationResult(
            message=None,
            raw_text=raw_text,
            success=False,
            attempts=total_attempts,
            errors=errors,
        )


def _validate_message_schema(
    message: Message, validator: SchemaValidator
) -> str | None:
    """Validate all action statements in a message. Return first error or None."""
    for stmt in message.statements:
        if isinstance(stmt, ActionStatement):
            result = validator.validate(stmt)
            if not result.is_valid:
                return f"Schema error on verb '{stmt.verb}': {result.error_message}"
    return None
