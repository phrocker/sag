import pytest
from sag.context import MapContext
from sag.sanitizer import AgentRegistry, ErrorType, SAGSanitizer, SanitizeResult
from sag.schema import ArgType, SchemaRegistry, VerbSchema


@pytest.fixture
def setup():
    schema_registry = SchemaRegistry()
    agent_registry = AgentRegistry()

    deploy_schema = (
        VerbSchema.Builder("deploy")
        .add_positional_arg("app", ArgType.STRING, True, "Application name")
        .build()
    )
    schema_registry.register(deploy_schema)

    agent_registry.register("svc1")
    agent_registry.register("svc2")
    agent_registry.register("agent1")
    agent_registry.register("agent2")

    context = MapContext({"balance": 1500})

    sanitizer = SAGSanitizer(
        schema_registry=schema_registry,
        agent_registry=agent_registry,
        default_context=context,
    )

    return sanitizer, schema_registry, agent_registry


def test_valid_input_passes_all_layers(setup):
    sanitizer, _, _ = setup
    raw = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1")'

    result = sanitizer.sanitize(raw)

    assert result.valid is True
    assert result.message is not None
    assert len(result.errors) == 0


def test_invalid_syntax_caught_at_grammar_layer(setup):
    sanitizer, _, _ = setup
    raw = "H v 1 invalid syntax\nDO test()"

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].error_type == ErrorType.PARSE


def test_unknown_source_caught_at_routing_layer(setup):
    sanitizer, _, _ = setup
    raw = 'H v 1 id=msg1 src=unknown_agent dst=svc2 ts=1234567890\nDO deploy("app1")'

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert any(e.error_type == ErrorType.ROUTING for e in result.errors)
    assert any("unknown_agent" in e.message for e in result.errors)


def test_unknown_destination_caught_at_routing_layer(setup):
    sanitizer, _, _ = setup
    raw = 'H v 1 id=msg1 src=svc1 dst=unknown_dst ts=1234567890\nDO deploy("app1")'

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert any(e.error_type == ErrorType.ROUTING for e in result.errors)


def test_wrong_schema_caught_at_schema_layer(setup):
    sanitizer, _, _ = setup
    # deploy requires a STRING positional arg, passing an integer
    raw = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy(42)"

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert any(e.error_type == ErrorType.SCHEMA for e in result.errors)


def test_failed_precondition_caught_at_guardrail_layer(setup):
    sanitizer, _, _ = setup
    # The default context has balance=1500, so balance>2000 will fail
    # Note: no spaces in expression (grammar doesn't allow WS within inline expressions)
    raw = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1") BECAUSE balance>2000'

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert any(e.error_type == ErrorType.GUARDRAIL for e in result.errors)


def test_agent_impersonation_rejected(setup):
    sanitizer, _, agent_registry = setup
    # Register only agent1, not "impersonator"
    raw = 'H v 1 id=msg1 src=impersonator dst=svc2 ts=1234567890\nDO deploy("app1")'

    result = sanitizer.sanitize(raw)

    assert result.valid is False
    assert any(e.code == "UNKNOWN_SOURCE" for e in result.errors)


def test_permissive_mode_collects_warnings():
    schema_registry = SchemaRegistry()
    agent_registry = AgentRegistry()
    agent_registry.register("svc1")
    # svc2 not registered

    sanitizer = SAGSanitizer(
        schema_registry=schema_registry,
        agent_registry=agent_registry,
        strict=False,
    )

    raw = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO anything()"

    result = sanitizer.sanitize(raw)

    # Permissive mode - valid even with warnings
    assert result.valid is True
    assert len(result.errors) > 0  # Has routing warnings


def test_sanitize_output(setup):
    sanitizer, _, _ = setup
    from sag.parser import SAGMessageParser

    raw = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1")'
    message = SAGMessageParser.parse(raw)

    result = sanitizer.sanitize_output(message)
    assert result.valid is True
