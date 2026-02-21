"""Tests for sag.prompt — PromptBuilder, SAGGenerator, and grammar sync."""

from __future__ import annotations

from sag.prompt import (
    LLMClient,
    PromptBuilder,
    SAGGenerator,
    _SAG_EXAMPLES,
    _SAG_GRAMMAR_EBNF,
    _SAG_QUICK_REFERENCE,
    _render_arg_spec,
    _render_schema_docs,
    _render_verb_signature,
)
from sag.schema import ArgType, SchemaRegistry, VerbSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Mock LLM client that returns pre-configured responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[tuple[str, list[dict[str, str]], int]] = []

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> str:
        self.calls.append((system_prompt, list(messages), max_tokens))
        response = self._responses[self._call_index]
        self._call_index = min(self._call_index + 1, len(self._responses) - 1)
        return response


VALID_SAG = (
    'H v 1 id=test1 src=agent dst=user ts=1700000000\n'
    'A response = "hello"'
)

VALID_SAG_ACTION = (
    'H v 1 id=test2 src=agent dst=server ts=1700000001\n'
    'DO deploy("myapp", env="production")'
)

INVALID_SAG = "this is not valid SAG at all"


# ---------------------------------------------------------------------------
# TestPromptBuilder
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_default_build_contains_grammar(self):
        prompt = PromptBuilder().build()
        assert "SAG Grammar (EBNF):" in prompt
        assert "message" in prompt
        assert "actionStmt" in prompt

    def test_default_build_contains_quick_reference(self):
        prompt = PromptBuilder().build()
        assert "Statement quick reference" in prompt
        assert "DO verb(" in prompt

    def test_default_build_contains_examples(self):
        prompt = PromptBuilder().build()
        assert "Example SAG messages:" in prompt
        assert "deploy" in prompt

    def test_custom_preamble(self):
        prompt = (
            PromptBuilder()
            .set_preamble("You are a helpful agent.")
            .build()
        )
        assert prompt.startswith("You are a helpful agent.")

    def test_custom_suffix(self):
        prompt = (
            PromptBuilder()
            .set_suffix("Always respond in SAG format.")
            .build()
        )
        assert prompt.endswith("Always respond in SAG format.")

    def test_disable_grammar(self):
        prompt = (
            PromptBuilder()
            .include_grammar(False)
            .build()
        )
        assert "SAG Grammar (EBNF):" not in prompt
        # Quick reference should still be there
        assert "Statement quick reference" in prompt

    def test_disable_quick_reference(self):
        prompt = (
            PromptBuilder()
            .include_quick_reference(False)
            .build()
        )
        assert "Statement quick reference" not in prompt
        assert "SAG Grammar (EBNF):" in prompt

    def test_disable_default_examples(self):
        prompt = (
            PromptBuilder()
            .include_default_examples(False)
            .build()
        )
        assert "Example SAG messages:" not in prompt

    def test_schema_registry_rendering(self):
        registry = SchemaRegistry()
        registry.register(
            VerbSchema.Builder("deploy")
            .add_positional_arg("app", ArgType.STRING, True, "App name")
            .add_named_arg("env", ArgType.STRING, False, "Environment",
                           allowed_values=["dev", "staging", "production"])
            .build()
        )
        prompt = (
            PromptBuilder()
            .set_schema_registry(registry)
            .include_grammar(False)
            .include_quick_reference(False)
            .include_default_examples(False)
            .build()
        )
        assert "deploy(" in prompt
        assert "app: STRING" in prompt
        assert "env?: STRING" in prompt

    def test_custom_example(self):
        custom = 'H v 1 id=x src=a dst=b ts=0\nDO custom("example")'
        prompt = (
            PromptBuilder()
            .add_example(custom)
            .include_grammar(False)
            .include_quick_reference(False)
            .include_default_examples(False)
            .build()
        )
        assert 'DO custom("example")' in prompt

    def test_builder_chaining(self):
        """All setters return the builder instance for chaining."""
        builder = PromptBuilder()
        result = (
            builder
            .set_preamble("intro")
            .set_suffix("end")
            .include_grammar(True)
            .include_quick_reference(True)
            .include_default_examples(True)
            .add_example("example")
        )
        assert result is builder

    def test_static_accessors(self):
        assert PromptBuilder.get_grammar_ebnf() == _SAG_GRAMMAR_EBNF
        assert PromptBuilder.get_quick_reference() == _SAG_QUICK_REFERENCE
        assert PromptBuilder.get_default_examples() == _SAG_EXAMPLES


# ---------------------------------------------------------------------------
# TestGrammarSync — verify the embedded EBNF matches SAG.g4
# ---------------------------------------------------------------------------


class TestGrammarSync:
    """Ensure the embedded EBNF constant covers all grammar constructs."""

    STATEMENT_TYPES = [
        "actionStmt",
        "queryStmt",
        "assertStmt",
        "controlStmt",
        "eventStmt",
        "errorStmt",
        "foldStmt",
        "recallStmt",
    ]

    KEYWORDS = [
        "DO", "Q", "A", "IF", "THEN", "ELSE", "EVT", "ERR",
        "FOLD", "RECALL", "BECAUSE", "WHERE", "STATE", "PRIO=",
    ]

    def test_all_statement_types_in_ebnf(self):
        for stmt_type in self.STATEMENT_TYPES:
            assert stmt_type in _SAG_GRAMMAR_EBNF, (
                f"Statement type '{stmt_type}' missing from EBNF"
            )

    def test_all_keywords_in_ebnf(self):
        for kw in self.KEYWORDS:
            assert kw in _SAG_GRAMMAR_EBNF, (
                f"Keyword '{kw}' missing from EBNF"
            )

    def test_all_statement_labels_in_quick_reference(self):
        labels = ["Action:", "Query:", "Assert:", "Control:", "Event:",
                   "Error:", "Fold:", "Recall:"]
        for label in labels:
            assert label in _SAG_QUICK_REFERENCE, (
                f"Label '{label}' missing from quick reference"
            )

    def test_expression_operators_in_ebnf(self):
        operators = ["||", "&&", "==", "!=", ">", "<", ">=", "<=",
                      "+", "-", "*", "/"]
        for op in operators:
            assert op in _SAG_GRAMMAR_EBNF, (
                f"Operator '{op}' missing from EBNF"
            )

    def test_value_types_in_ebnf(self):
        types = ["STRING", "INT", "FLOAT", "BOOL", "null", "path",
                 "list", "object"]
        for t in types:
            assert t in _SAG_GRAMMAR_EBNF, (
                f"Value type '{t}' missing from EBNF"
            )


# ---------------------------------------------------------------------------
# TestSAGGenerator
# ---------------------------------------------------------------------------


class TestSAGGenerator:
    def test_success_on_first_attempt(self):
        client = MockLLMClient([VALID_SAG])
        gen = SAGGenerator(client)
        result = gen.generate([{"role": "user", "content": "hello"}])
        assert result.success
        assert result.message is not None
        assert result.attempts == 1
        assert result.errors == []
        assert result.raw_text == VALID_SAG

    def test_retry_on_parse_failure(self):
        client = MockLLMClient([INVALID_SAG, VALID_SAG])
        gen = SAGGenerator(client, max_retries=2)
        result = gen.generate([{"role": "user", "content": "hello"}])
        assert result.success
        assert result.attempts == 2
        assert len(result.errors) == 1
        assert "Parse error" in result.errors[0]

    def test_retry_exhaustion(self):
        client = MockLLMClient([INVALID_SAG])
        gen = SAGGenerator(client, max_retries=1)
        result = gen.generate([{"role": "user", "content": "hello"}])
        assert not result.success
        assert result.message is None
        assert result.attempts == 2  # 1 initial + 1 retry
        assert len(result.errors) == 2

    def test_error_feedback_content(self):
        """Check that retry messages contain the parse error."""
        client = MockLLMClient([INVALID_SAG, VALID_SAG])
        gen = SAGGenerator(client, max_retries=1)
        gen.generate([{"role": "user", "content": "hello"}])
        # Second call should have error feedback appended
        _, messages, _ = client.calls[1]
        # Should include the assistant's failed attempt and error feedback
        assert any("not valid SAG" in m["content"] for m in messages if m["role"] == "user")

    def test_schema_validation_retry(self):
        registry = SchemaRegistry()
        registry.register(
            VerbSchema.Builder("deploy")
            .add_positional_arg("app", ArgType.STRING, True, "App name")
            .build()
        )
        # First response: valid SAG but wrong schema (missing required arg)
        bad_schema_sag = (
            'H v 1 id=t1 src=a dst=b ts=0\n'
            'DO deploy()'
        )
        # Second response: valid SAG with correct schema
        good_schema_sag = (
            'H v 1 id=t2 src=a dst=b ts=1\n'
            'DO deploy("myapp")'
        )
        client = MockLLMClient([bad_schema_sag, good_schema_sag])
        gen = SAGGenerator(client, schema_registry=registry, max_retries=1)
        result = gen.generate([{"role": "user", "content": "deploy"}])
        assert result.success
        assert result.attempts == 2
        assert any("Schema error" in e for e in result.errors)

    def test_disabled_schema_validation(self):
        registry = SchemaRegistry()
        registry.register(
            VerbSchema.Builder("deploy")
            .add_positional_arg("app", ArgType.STRING, True, "App name")
            .build()
        )
        bad_schema_sag = (
            'H v 1 id=t1 src=a dst=b ts=0\n'
            'DO deploy()'
        )
        client = MockLLMClient([bad_schema_sag])
        gen = SAGGenerator(
            client, schema_registry=registry,
            max_retries=0, validate_schema=False,
        )
        result = gen.generate([{"role": "user", "content": "deploy"}])
        assert result.success  # Passes because schema validation is off

    def test_system_prompt_override(self):
        client = MockLLMClient([VALID_SAG])
        gen = SAGGenerator(client)
        gen.generate(
            [{"role": "user", "content": "hello"}],
            system_prompt_override="custom prompt",
        )
        system_prompt_used, _, _ = client.calls[0]
        assert system_prompt_used == "custom prompt"

    def test_prompt_caching(self):
        client = MockLLMClient([VALID_SAG, VALID_SAG])
        gen = SAGGenerator(client)
        prompt1 = gen.system_prompt
        prompt2 = gen.system_prompt
        assert prompt1 is prompt2  # Same object (cached)

    def test_invalidate_prompt_cache(self):
        client = MockLLMClient([VALID_SAG])
        builder = PromptBuilder().set_preamble("v1")
        gen = SAGGenerator(client, prompt_builder=builder)
        prompt_v1 = gen.system_prompt
        assert "v1" in prompt_v1

        builder.set_preamble("v2")
        gen.invalidate_prompt_cache()
        prompt_v2 = gen.system_prompt
        assert "v2" in prompt_v2

    def test_input_immutability(self):
        """generate() must not mutate the caller's message list."""
        client = MockLLMClient([INVALID_SAG, VALID_SAG])
        gen = SAGGenerator(client, max_retries=1)
        original_messages = [{"role": "user", "content": "hello"}]
        original_len = len(original_messages)
        gen.generate(original_messages)
        assert len(original_messages) == original_len

    def test_zero_retries(self):
        client = MockLLMClient([INVALID_SAG])
        gen = SAGGenerator(client, max_retries=0)
        result = gen.generate([{"role": "user", "content": "hello"}])
        assert not result.success
        assert result.attempts == 1


# ---------------------------------------------------------------------------
# TestLLMClientProtocol
# ---------------------------------------------------------------------------


class TestLLMClientProtocol:
    def test_mock_satisfies_protocol(self):
        client = MockLLMClient(["test"])
        assert isinstance(client, LLMClient)

    def test_non_conforming_object_fails(self):
        class BadClient:
            pass

        assert not isinstance(BadClient(), LLMClient)


# ---------------------------------------------------------------------------
# Schema rendering helpers
# ---------------------------------------------------------------------------


class TestSchemaRendering:
    def test_render_arg_spec_required(self):
        from sag.schema import ArgumentSpec
        spec = ArgumentSpec("name", ArgType.STRING, required=True)
        rendered = _render_arg_spec(spec)
        assert rendered == "name: STRING"

    def test_render_arg_spec_optional(self):
        from sag.schema import ArgumentSpec
        spec = ArgumentSpec("env", ArgType.STRING, required=False)
        rendered = _render_arg_spec(spec)
        assert rendered == "env?: STRING"

    def test_render_arg_spec_with_allowed_values(self):
        from sag.schema import ArgumentSpec
        spec = ArgumentSpec(
            "env", ArgType.STRING, required=False,
            allowed_values=["dev", "prod"],
        )
        rendered = _render_arg_spec(spec)
        assert "env?: STRING" in rendered
        assert "'dev'" in rendered
        assert "'prod'" in rendered

    def test_render_arg_spec_with_range(self):
        from sag.schema import ArgumentSpec
        spec = ArgumentSpec(
            "count", ArgType.INTEGER, required=True,
            min_value=1, max_value=100,
        )
        rendered = _render_arg_spec(spec)
        assert "count: INTEGER" in rendered
        assert ">=1" in rendered
        assert "<=100" in rendered

    def test_render_verb_signature(self):
        schema = (
            VerbSchema.Builder("deploy")
            .add_positional_arg("app", ArgType.STRING, True)
            .add_named_arg("env", ArgType.STRING, False)
            .build()
        )
        sig = _render_verb_signature(schema)
        assert sig == "deploy(app: STRING, env?: STRING)"

    def test_render_schema_docs_empty_registry(self):
        registry = SchemaRegistry()
        assert _render_schema_docs(registry) == ""

    def test_render_schema_docs_sorted(self):
        registry = SchemaRegistry()
        registry.register(VerbSchema.Builder("zeta").build())
        registry.register(VerbSchema.Builder("alpha").build())
        docs = _render_schema_docs(registry)
        alpha_pos = docs.index("alpha")
        zeta_pos = docs.index("zeta")
        assert alpha_pos < zeta_pos
