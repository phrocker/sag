import pytest
from sag.model import ActionStatement
from sag.schema import (
    ArgType,
    ArgumentSpec,
    SchemaRegistry,
    SchemaValidationResult,
    SchemaValidator,
    VerbSchema,
)


@pytest.fixture
def registry_and_validator():
    registry = SchemaRegistry()
    validator = SchemaValidator(registry)

    reorder_schema = (
        VerbSchema.Builder("reorder")
        .add_named_arg("item", ArgType.STRING, True, "Item to reorder")
        .add_named_arg("qty", ArgType.INTEGER, True, "Quantity")
        .build()
    )
    registry.register(reorder_schema)

    deploy_schema = (
        VerbSchema.Builder("deploy")
        .add_positional_arg("app", ArgType.STRING, True, "Application name")
        .add_named_arg("version", ArgType.INTEGER, False, "Version number")
        .add_named_arg("env", ArgType.STRING, False, "Environment")
        .build()
    )
    registry.register(deploy_schema)

    return registry, validator


def test_valid_action_with_correct_args(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="reorder",
        args=[],
        named_args={"item": "laptop", "qty": 5},
    )

    result = validator.validate(action)
    assert result.is_valid is True


def test_invalid_action_with_wrong_key_name(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="reorder",
        args=[],
        named_args={"product": "laptop", "qty": 5},
    )

    result = validator.validate(action)
    assert result.is_valid is False
    assert result.error_code == "INVALID_ARGS"
    assert "product" in result.error_message


def test_missing_required_arg(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="reorder",
        args=[],
        named_args={"item": "laptop"},
    )

    result = validator.validate(action)
    assert result.is_valid is False
    assert result.error_code == "MISSING_ARG"
    assert "qty" in result.error_message


def test_type_mismatch(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="reorder",
        args=[],
        named_args={"item": "laptop", "qty": "five"},
    )

    result = validator.validate(action)
    assert result.is_valid is False
    assert result.error_code == "TYPE_MISMATCH"
    assert "qty" in result.error_message


def test_unregistered_verb_passes_validation(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="unknownVerb",
        args=[],
        named_args={"any": "value"},
    )

    result = validator.validate(action)
    assert result.is_valid is True


def test_positional_args_validation(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="deploy",
        args=["myapp"],
        named_args={"version": 2},
    )

    result = validator.validate(action)
    assert result.is_valid is True


def test_missing_required_positional_arg(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="deploy",
        args=[],
        named_args={"version": 2},
    )

    result = validator.validate(action)
    assert result.is_valid is False
    assert result.error_code == "MISSING_ARG"


def test_wrong_type_for_positional_arg(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="deploy",
        args=[123],
        named_args={"version": 2},
    )

    result = validator.validate(action)
    assert result.is_valid is False
    assert result.error_code == "TYPE_MISMATCH"


def test_optional_arg_not_required(registry_and_validator):
    _, validator = registry_and_validator

    action = ActionStatement(
        verb="deploy",
        args=["myapp"],
        named_args={},
    )

    result = validator.validate(action)
    assert result.is_valid is True


def test_to_error_statement():
    result = SchemaValidationResult.failure("INVALID_ARGS", "Test error message")

    error_stmt = result.to_error_statement()
    assert error_stmt is not None
    assert error_stmt.error_code == "INVALID_ARGS"
    assert error_stmt.message == "Test error message"


def test_schema_with_allow_extra_args(registry_and_validator):
    registry, validator = registry_and_validator

    flexible_schema = (
        VerbSchema.Builder("flexibleVerb")
        .add_named_arg("required", ArgType.STRING, True, "Required arg")
        .allow_extra_args(True)
        .build()
    )
    registry.register(flexible_schema)

    action = ActionStatement(
        verb="flexibleVerb",
        args=[],
        named_args={"required": "value", "extra": "allowed"},
    )

    result = validator.validate(action)
    assert result.is_valid is True


def test_registry_operations(registry_and_validator):
    registry, _ = registry_and_validator

    assert registry.size() == 2
    assert registry.has_schema("reorder")
    assert registry.has_schema("deploy")

    schema = registry.get_schema("reorder")
    assert schema is not None
    assert schema.verb_name == "reorder"

    registry.unregister("reorder")
    assert registry.has_schema("reorder") is False
    assert registry.size() == 1

    registry.clear()
    assert registry.size() == 0


# ---------- Value constraint tests ----------


class TestEnumConstraint:
    @pytest.fixture
    def enum_validator(self):
        registry = SchemaRegistry()
        schema = (
            VerbSchema.Builder("setenv")
            .add_named_arg("env", ArgType.STRING, True, "Environment",
                           allowed_values=["dev", "staging", "production"])
            .build()
        )
        registry.register(schema)
        return SchemaValidator(registry)

    def test_allowed_value_passes(self, enum_validator):
        action = ActionStatement(verb="setenv", args=[], named_args={"env": "dev"})
        result = enum_validator.validate(action)
        assert result.is_valid

    def test_disallowed_value_fails(self, enum_validator):
        action = ActionStatement(verb="setenv", args=[], named_args={"env": "local"})
        result = enum_validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"
        assert "local" in result.error_message

    def test_null_value_passes_enum(self, enum_validator):
        action = ActionStatement(verb="setenv", args=[], named_args={"env": None})
        result = enum_validator.validate(action)
        assert result.is_valid


class TestPatternConstraint:
    @pytest.fixture
    def pattern_validator(self):
        registry = SchemaRegistry()
        schema = (
            VerbSchema.Builder("tag")
            .add_positional_arg("version", ArgType.STRING, True, "Semver version",
                                pattern=r"^\d+\.\d+\.\d+$")
            .build()
        )
        registry.register(schema)
        return SchemaValidator(registry)

    def test_matching_pattern_passes(self, pattern_validator):
        action = ActionStatement(verb="tag", args=["1.2.3"], named_args={})
        result = pattern_validator.validate(action)
        assert result.is_valid

    def test_non_matching_pattern_fails(self, pattern_validator):
        action = ActionStatement(verb="tag", args=["v1.2"], named_args={})
        result = pattern_validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "PATTERN_MISMATCH"

    def test_null_value_passes_pattern(self, pattern_validator):
        action = ActionStatement(verb="tag", args=[None], named_args={})
        result = pattern_validator.validate(action)
        assert result.is_valid

    def test_pattern_on_non_string_type_raises(self):
        with pytest.raises(ValueError, match="pattern constraint only applies to STRING"):
            ArgumentSpec("x", ArgType.INTEGER, True, "", pattern=r"\d+")


class TestRangeConstraint:
    @pytest.fixture
    def range_validator(self):
        registry = SchemaRegistry()
        schema = (
            VerbSchema.Builder("scale")
            .add_named_arg("replicas", ArgType.INTEGER, True, "Replicas",
                           min_value=1, max_value=100)
            .add_named_arg("threshold", ArgType.FLOAT, False, "Threshold",
                           min_value=0.0, max_value=1.0)
            .build()
        )
        registry.register(schema)
        return SchemaValidator(registry)

    def test_in_range_passes(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 5})
        result = range_validator.validate(action)
        assert result.is_valid

    def test_at_min_boundary_passes(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 1})
        result = range_validator.validate(action)
        assert result.is_valid

    def test_at_max_boundary_passes(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 100})
        result = range_validator.validate(action)
        assert result.is_valid

    def test_below_min_fails(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 0})
        result = range_validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"
        assert "less than minimum" in result.error_message

    def test_above_max_fails(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 101})
        result = range_validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"
        assert "greater than maximum" in result.error_message

    def test_float_range(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 5, "threshold": 0.5})
        result = range_validator.validate(action)
        assert result.is_valid

    def test_float_out_of_range(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": 5, "threshold": 1.5})
        result = range_validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    def test_null_value_passes_range(self, range_validator):
        action = ActionStatement(verb="scale", args=[], named_args={"replicas": None})
        result = range_validator.validate(action)
        assert result.is_valid

    def test_range_on_string_type_raises(self):
        with pytest.raises(ValueError, match="range constraints only apply to INTEGER or FLOAT"):
            ArgumentSpec("x", ArgType.STRING, True, "", min_value=1, max_value=10)


class TestConstraintOrder:
    """Constraints are checked in order: enum -> pattern -> range."""

    def test_enum_checked_before_pattern(self):
        registry = SchemaRegistry()
        schema = (
            VerbSchema.Builder("combo")
            .add_named_arg("val", ArgType.STRING, True, "Value",
                           allowed_values=["abc", "def"], pattern=r"^[a-z]+$")
            .build()
        )
        registry.register(schema)
        validator = SchemaValidator(registry)
        # "xyz" matches pattern but not enum — should get VALUE_NOT_ALLOWED
        action = ActionStatement(verb="combo", args=[], named_args={"val": "xyz"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    def test_positional_enum_constraint(self):
        registry = SchemaRegistry()
        schema = (
            VerbSchema.Builder("choose")
            .add_positional_arg("color", ArgType.STRING, True, "Color",
                                allowed_values=["red", "green", "blue"])
            .build()
        )
        registry.register(schema)
        validator = SchemaValidator(registry)

        good = ActionStatement(verb="choose", args=["red"], named_args={})
        assert validator.validate(good).is_valid

        bad = ActionStatement(verb="choose", args=["yellow"], named_args={})
        result = validator.validate(bad)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"
