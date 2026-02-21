import pytest
from sag.model import ActionStatement
from sag.profiles import SoftwareDevProfile
from sag.schema import ArgType, SchemaRegistry, SchemaValidator, VerbSchema


@pytest.fixture
def registry():
    return SoftwareDevProfile.create_registry()


@pytest.fixture
def validator(registry):
    return SchemaValidator(registry)


class TestRegistryCreation:
    def test_registry_has_all_verbs(self, registry):
        assert registry.size() == 12

    def test_registry_contains_each_verb(self, registry):
        for verb in SoftwareDevProfile.get_verbs():
            assert registry.has_schema(verb), f"Missing verb: {verb}"

    def test_get_verbs_returns_expected_list(self):
        verbs = SoftwareDevProfile.get_verbs()
        expected = [
            "build", "test", "deploy", "rollback", "review", "merge",
            "lint", "scan", "release", "provision", "monitor", "migrate",
        ]
        assert verbs == expected

    def test_get_verbs_returns_new_list(self):
        v1 = SoftwareDevProfile.get_verbs()
        v2 = SoftwareDevProfile.get_verbs()
        assert v1 is not v2

    def test_create_registry_returns_new_instance(self):
        r1 = SoftwareDevProfile.create_registry()
        r2 = SoftwareDevProfile.create_registry()
        assert r1 is not r2


class TestValidActions:
    @pytest.mark.parametrize("verb,args,named_args", [
        ("build", ["myproject"], {}),
        ("build", ["myproject"], {"config": "release", "clean": True}),
        ("test", ["unit"], {}),
        ("test", ["unit"], {"coverage": True, "timeout": 60, "parallel": True}),
        ("deploy", ["webapp"], {}),
        ("deploy", ["webapp"], {"version": 3, "env": "production", "replicas": 5}),
        ("rollback", ["webapp"], {}),
        ("rollback", ["webapp"], {"version": 2, "env": "staging"}),
        ("review", ["PR-123"], {}),
        ("review", ["PR-123"], {"reviewer": "alice", "auto_merge": False}),
        ("merge", ["feature", "main"], {}),
        ("merge", ["feature", "main"], {"strategy": "rebase", "squash": True}),
        ("lint", ["src/"], {}),
        ("lint", ["src/"], {"fix": True, "config": ".eslintrc"}),
        ("scan", ["repo"], {}),
        ("scan", ["repo"], {"scan_type": "sast", "severity": "high"}),
        ("release", ["1.0.0"], {}),
        ("release", ["1.0.0"], {"tag": "v1.0.0", "draft": False, "notes": "Initial release"}),
        ("provision", ["database"], {}),
        ("provision", ["database"], {"provider": "aws", "region": "us-east-1", "count": 3}),
        ("monitor", ["api-service"], {}),
        ("monitor", ["api-service"], {"interval": 30, "alert_threshold": 0.95}),
        ("migrate", ["users_db"], {}),
        ("migrate", ["users_db"], {"direction": "up", "version": "v2", "dry_run": True}),
    ])
    def test_valid_action(self, validator, verb, args, named_args):
        action = ActionStatement(verb=verb, args=args, named_args=named_args)
        result = validator.validate(action)
        assert result.is_valid, f"Expected valid for {verb}: {result.error_message}"


class TestMissingRequiredArgs:
    def test_build_missing_target(self, validator):
        action = ActionStatement(verb="build", args=[], named_args={})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "MISSING_ARG"

    def test_merge_missing_second_positional(self, validator):
        action = ActionStatement(verb="merge", args=["feature"], named_args={})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "MISSING_ARG"

    def test_deploy_missing_app(self, validator):
        action = ActionStatement(verb="deploy", args=[], named_args={"version": 1})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "MISSING_ARG"


class TestTypeMismatch:
    def test_build_target_not_string(self, validator):
        action = ActionStatement(verb="build", args=[123], named_args={})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "TYPE_MISMATCH"

    def test_test_timeout_not_integer(self, validator):
        action = ActionStatement(verb="test", args=["unit"], named_args={"timeout": "slow"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "TYPE_MISMATCH"

    def test_deploy_version_not_integer(self, validator):
        action = ActionStatement(verb="deploy", args=["webapp"], named_args={"version": "latest"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "TYPE_MISMATCH"

    def test_monitor_alert_threshold_not_float(self, validator):
        action = ActionStatement(verb="monitor", args=["svc"], named_args={"alert_threshold": "high"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "TYPE_MISMATCH"

    def test_lint_fix_not_boolean(self, validator):
        action = ActionStatement(verb="lint", args=["src/"], named_args={"fix": "yes"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "TYPE_MISMATCH"


class TestUnknownNamedArgs:
    def test_build_unknown_arg(self, validator):
        action = ActionStatement(verb="build", args=["proj"], named_args={"unknown": "val"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "INVALID_ARGS"

    def test_deploy_unknown_arg(self, validator):
        action = ActionStatement(verb="deploy", args=["app"], named_args={"foo": "bar"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "INVALID_ARGS"


class TestValueConstraints:
    """Tests for value constraints applied in the SoftwareDevProfile."""

    @pytest.mark.parametrize("env", ["dev", "staging", "production"])
    def test_deploy_env_valid(self, validator, env):
        action = ActionStatement(verb="deploy", args=["app"], named_args={"env": env})
        assert validator.validate(action).is_valid

    def test_deploy_env_invalid(self, validator):
        action = ActionStatement(verb="deploy", args=["app"], named_args={"env": "local"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    def test_deploy_replicas_in_range(self, validator):
        action = ActionStatement(verb="deploy", args=["app"], named_args={"replicas": 5})
        assert validator.validate(action).is_valid

    def test_deploy_replicas_out_of_range(self, validator):
        action = ActionStatement(verb="deploy", args=["app"], named_args={"replicas": 0})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    def test_rollback_env_valid(self, validator):
        action = ActionStatement(verb="rollback", args=["app"], named_args={"env": "staging"})
        assert validator.validate(action).is_valid

    def test_rollback_env_invalid(self, validator):
        action = ActionStatement(verb="rollback", args=["app"], named_args={"env": "qa"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    def test_test_timeout_in_range(self, validator):
        action = ActionStatement(verb="test", args=["unit"], named_args={"timeout": 60})
        assert validator.validate(action).is_valid

    def test_test_timeout_out_of_range(self, validator):
        action = ActionStatement(verb="test", args=["unit"], named_args={"timeout": 5000})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    @pytest.mark.parametrize("strategy", ["merge", "rebase", "squash"])
    def test_merge_strategy_valid(self, validator, strategy):
        action = ActionStatement(verb="merge", args=["f", "m"], named_args={"strategy": strategy})
        assert validator.validate(action).is_valid

    def test_merge_strategy_invalid(self, validator):
        action = ActionStatement(verb="merge", args=["f", "m"], named_args={"strategy": "fast-forward"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    @pytest.mark.parametrize("scan_type", ["sast", "dast", "sca", "container"])
    def test_scan_type_valid(self, validator, scan_type):
        action = ActionStatement(verb="scan", args=["repo"], named_args={"scan_type": scan_type})
        assert validator.validate(action).is_valid

    def test_scan_type_invalid(self, validator):
        action = ActionStatement(verb="scan", args=["repo"], named_args={"scan_type": "pentest"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    @pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
    def test_scan_severity_valid(self, validator, severity):
        action = ActionStatement(verb="scan", args=["repo"], named_args={"severity": severity})
        assert validator.validate(action).is_valid

    def test_scan_severity_invalid(self, validator):
        action = ActionStatement(verb="scan", args=["repo"], named_args={"severity": "info"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    @pytest.mark.parametrize("provider", ["aws", "gcp", "azure"])
    def test_provision_provider_valid(self, validator, provider):
        action = ActionStatement(verb="provision", args=["db"], named_args={"provider": provider})
        assert validator.validate(action).is_valid

    def test_provision_provider_invalid(self, validator):
        action = ActionStatement(verb="provision", args=["db"], named_args={"provider": "digitalocean"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    def test_provision_count_in_range(self, validator):
        action = ActionStatement(verb="provision", args=["db"], named_args={"count": 3})
        assert validator.validate(action).is_valid

    def test_provision_count_out_of_range(self, validator):
        action = ActionStatement(verb="provision", args=["db"], named_args={"count": 200})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    def test_monitor_interval_in_range(self, validator):
        action = ActionStatement(verb="monitor", args=["svc"], named_args={"interval": 30})
        assert validator.validate(action).is_valid

    def test_monitor_interval_out_of_range(self, validator):
        action = ActionStatement(verb="monitor", args=["svc"], named_args={"interval": 0})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    def test_monitor_alert_threshold_in_range(self, validator):
        action = ActionStatement(verb="monitor", args=["svc"], named_args={"alert_threshold": 0.95})
        assert validator.validate(action).is_valid

    def test_monitor_alert_threshold_out_of_range(self, validator):
        action = ActionStatement(verb="monitor", args=["svc"], named_args={"alert_threshold": 1.5})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_OUT_OF_RANGE"

    @pytest.mark.parametrize("direction", ["up", "down"])
    def test_migrate_direction_valid(self, validator, direction):
        action = ActionStatement(verb="migrate", args=["db"], named_args={"direction": direction})
        assert validator.validate(action).is_valid

    def test_migrate_direction_invalid(self, validator):
        action = ActionStatement(verb="migrate", args=["db"], named_args={"direction": "sideways"})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "VALUE_NOT_ALLOWED"

    def test_release_version_valid_pattern(self, validator):
        action = ActionStatement(verb="release", args=["1.0.0"], named_args={})
        assert validator.validate(action).is_valid

    def test_release_version_invalid_pattern(self, validator):
        action = ActionStatement(verb="release", args=["v1.0"], named_args={})
        result = validator.validate(action)
        assert not result.is_valid
        assert result.error_code == "PATTERN_MISMATCH"


class TestComposition:
    def test_registry_composes_with_user_schemas(self):
        registry = SoftwareDevProfile.create_registry()
        custom_schema = (
            VerbSchema.Builder("custom_verb")
            .add_positional_arg("name", ArgType.STRING, True, "Custom arg")
            .build()
        )
        registry.register(custom_schema)

        assert registry.size() == 13
        assert registry.has_schema("custom_verb")
        assert registry.has_schema("build")

        validator = SchemaValidator(registry)
        result = validator.validate(
            ActionStatement(verb="custom_verb", args=["test"], named_args={})
        )
        assert result.is_valid

    def test_user_can_override_profile_verb(self):
        registry = SoftwareDevProfile.create_registry()
        custom_build = (
            VerbSchema.Builder("build")
            .add_positional_arg("target", ArgType.STRING, True, "Build target")
            .add_named_arg("debug", ArgType.BOOLEAN, False, "Enable debug mode")
            .build()
        )
        registry.register(custom_build)

        assert registry.size() == 12
        validator = SchemaValidator(registry)

        # Original 'config' named arg should now be rejected
        result = validator.validate(
            ActionStatement(verb="build", args=["proj"], named_args={"config": "release"})
        )
        assert not result.is_valid

        # New 'debug' arg should be accepted
        result = validator.validate(
            ActionStatement(verb="build", args=["proj"], named_args={"debug": True})
        )
        assert result.is_valid
