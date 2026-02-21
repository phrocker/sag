package com.sentrius.sag.profiles;

import com.sentrius.sag.SchemaRegistry;
import com.sentrius.sag.SchemaValidator;
import com.sentrius.sag.VerbSchema;
import com.sentrius.sag.model.ActionStatement;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.util.*;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;

class SoftwareDevProfileTest {

    private SchemaRegistry registry;
    private SchemaValidator validator;

    @BeforeEach
    void setUp() {
        registry = SoftwareDevProfile.createRegistry();
        validator = new SchemaValidator(registry);
    }

    @Test
    void testRegistryHasAllVerbs() {
        assertEquals(12, registry.size());
    }

    @Test
    void testRegistryContainsEachVerb() {
        for (String verb : SoftwareDevProfile.getVerbs()) {
            assertTrue(registry.hasSchema(verb), "Missing verb: " + verb);
        }
    }

    @Test
    void testGetVerbsReturnsExpectedList() {
        List<String> expected = List.of(
            "build", "test", "deploy", "rollback", "review", "merge",
            "lint", "scan", "release", "provision", "monitor", "migrate"
        );
        assertEquals(expected, SoftwareDevProfile.getVerbs());
    }

    @Test
    void testCreateRegistryReturnsNewInstance() {
        SchemaRegistry r1 = SoftwareDevProfile.createRegistry();
        SchemaRegistry r2 = SoftwareDevProfile.createRegistry();
        assertNotSame(r1, r2);
    }

    static Stream<Arguments> validActions() {
        return Stream.of(
            Arguments.of("build", List.of("myproject"), Map.of()),
            Arguments.of("build", List.of("myproject"), Map.of("config", "release", "clean", true)),
            Arguments.of("test", List.of("unit"), Map.of()),
            Arguments.of("test", List.of("unit"), Map.of("coverage", true, "timeout", 60, "parallel", true)),
            Arguments.of("deploy", List.of("webapp"), Map.of()),
            Arguments.of("deploy", List.of("webapp"), Map.of("version", 3, "env", "production", "replicas", 5)),
            Arguments.of("rollback", List.of("webapp"), Map.of()),
            Arguments.of("rollback", List.of("webapp"), Map.of("version", 2, "env", "staging")),
            Arguments.of("review", List.of("PR-123"), Map.of()),
            Arguments.of("review", List.of("PR-123"), Map.of("reviewer", "alice", "auto_merge", false)),
            Arguments.of("merge", List.of("feature", "main"), Map.of()),
            Arguments.of("merge", List.of("feature", "main"), Map.of("strategy", "rebase", "squash", true)),
            Arguments.of("lint", List.of("src/"), Map.of()),
            Arguments.of("lint", List.of("src/"), Map.of("fix", true, "config", ".eslintrc")),
            Arguments.of("scan", List.of("repo"), Map.of()),
            Arguments.of("scan", List.of("repo"), Map.of("scan_type", "sast", "severity", "high")),
            Arguments.of("release", List.of("1.0.0"), Map.of()),
            Arguments.of("release", List.of("1.0.0"), Map.of("tag", "v1.0.0", "draft", false, "notes", "Initial release")),
            Arguments.of("provision", List.of("database"), Map.of()),
            Arguments.of("provision", List.of("database"), Map.of("provider", "aws", "region", "us-east-1", "count", 3)),
            Arguments.of("monitor", List.of("api-service"), Map.of()),
            Arguments.of("monitor", List.of("api-service"), Map.of("interval", 30, "alert_threshold", 0.95)),
            Arguments.of("migrate", List.of("users_db"), Map.of()),
            Arguments.of("migrate", List.of("users_db"), Map.of("direction", "up", "version", "v2", "dry_run", true))
        );
    }

    @ParameterizedTest
    @MethodSource("validActions")
    void testValidAction(String verb, List<Object> args, Map<String, Object> namedArgs) {
        ActionStatement action = new ActionStatement(verb, args, namedArgs, null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertTrue(result.isValid(), "Expected valid for " + verb + ": " + result.getErrorMessage());
    }

    @Test
    void testBuildMissingTarget() {
        ActionStatement action = new ActionStatement("build", List.of(), Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("MISSING_ARG", result.getErrorCode());
    }

    @Test
    void testMergeMissingSecondPositional() {
        ActionStatement action = new ActionStatement("merge", List.of("feature"), Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("MISSING_ARG", result.getErrorCode());
    }

    @Test
    void testDeployMissingApp() {
        ActionStatement action = new ActionStatement("deploy", List.of(), Map.of("version", 1), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("MISSING_ARG", result.getErrorCode());
    }

    @Test
    void testBuildTargetNotString() {
        ActionStatement action = new ActionStatement("build", List.of(123), Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
    }

    @Test
    void testTestTimeoutNotInteger() {
        ActionStatement action = new ActionStatement("test", List.of("unit"), Map.of("timeout", "slow"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
    }

    @Test
    void testDeployVersionNotInteger() {
        ActionStatement action = new ActionStatement("deploy", List.of("webapp"), Map.of("version", "latest"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
    }

    @Test
    void testMonitorAlertThresholdNotFloat() {
        ActionStatement action = new ActionStatement("monitor", List.of("svc"), Map.of("alert_threshold", "high"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
    }

    @Test
    void testBuildUnknownArg() {
        ActionStatement action = new ActionStatement("build", List.of("proj"), Map.of("unknown", "val"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("INVALID_ARGS", result.getErrorCode());
    }

    @Test
    void testDeployUnknownArg() {
        ActionStatement action = new ActionStatement("deploy", List.of("app"), Map.of("foo", "bar"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("INVALID_ARGS", result.getErrorCode());
    }

    // ---------- Value constraint tests ----------

    @Test
    void testDeployEnvValidValues() {
        for (String env : List.of("dev", "staging", "production")) {
            ActionStatement action = new ActionStatement("deploy", List.of("app"),
                Map.of("env", env), null, null, null, null);
            assertTrue(validator.validate(action).isValid(), "Expected valid for env=" + env);
        }
    }

    @Test
    void testDeployEnvInvalid() {
        ActionStatement action = new ActionStatement("deploy", List.of("app"),
            Map.of("env", "local"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testDeployReplicasInRange() {
        ActionStatement action = new ActionStatement("deploy", List.of("app"),
            Map.of("replicas", 5), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testDeployReplicasOutOfRange() {
        ActionStatement action = new ActionStatement("deploy", List.of("app"),
            Map.of("replicas", 0), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testRollbackEnvValid() {
        ActionStatement action = new ActionStatement("rollback", List.of("app"),
            Map.of("env", "staging"), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testRollbackEnvInvalid() {
        ActionStatement action = new ActionStatement("rollback", List.of("app"),
            Map.of("env", "qa"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testTestTimeoutInRange() {
        ActionStatement action = new ActionStatement("test", List.of("unit"),
            Map.of("timeout", 60), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testTestTimeoutOutOfRange() {
        ActionStatement action = new ActionStatement("test", List.of("unit"),
            Map.of("timeout", 5000), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testMergeStrategyValid() {
        for (String strategy : List.of("merge", "rebase", "squash")) {
            ActionStatement action = new ActionStatement("merge", List.of("f", "m"),
                Map.of("strategy", strategy), null, null, null, null);
            assertTrue(validator.validate(action).isValid(), "Expected valid for strategy=" + strategy);
        }
    }

    @Test
    void testMergeStrategyInvalid() {
        ActionStatement action = new ActionStatement("merge", List.of("f", "m"),
            Map.of("strategy", "fast-forward"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testScanTypeValid() {
        for (String scanType : List.of("sast", "dast", "sca", "container")) {
            ActionStatement action = new ActionStatement("scan", List.of("repo"),
                Map.of("scan_type", scanType), null, null, null, null);
            assertTrue(validator.validate(action).isValid());
        }
    }

    @Test
    void testScanTypeInvalid() {
        ActionStatement action = new ActionStatement("scan", List.of("repo"),
            Map.of("scan_type", "pentest"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testScanSeverityValid() {
        for (String severity : List.of("low", "medium", "high", "critical")) {
            ActionStatement action = new ActionStatement("scan", List.of("repo"),
                Map.of("severity", severity), null, null, null, null);
            assertTrue(validator.validate(action).isValid());
        }
    }

    @Test
    void testScanSeverityInvalid() {
        ActionStatement action = new ActionStatement("scan", List.of("repo"),
            Map.of("severity", "info"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testProvisionProviderValid() {
        for (String provider : List.of("aws", "gcp", "azure")) {
            ActionStatement action = new ActionStatement("provision", List.of("db"),
                Map.of("provider", provider), null, null, null, null);
            assertTrue(validator.validate(action).isValid());
        }
    }

    @Test
    void testProvisionProviderInvalid() {
        ActionStatement action = new ActionStatement("provision", List.of("db"),
            Map.of("provider", "digitalocean"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testProvisionCountInRange() {
        ActionStatement action = new ActionStatement("provision", List.of("db"),
            Map.of("count", 3), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testProvisionCountOutOfRange() {
        ActionStatement action = new ActionStatement("provision", List.of("db"),
            Map.of("count", 200), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testMonitorIntervalInRange() {
        ActionStatement action = new ActionStatement("monitor", List.of("svc"),
            Map.of("interval", 30), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testMonitorIntervalOutOfRange() {
        ActionStatement action = new ActionStatement("monitor", List.of("svc"),
            Map.of("interval", 0), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testMonitorAlertThresholdInRange() {
        ActionStatement action = new ActionStatement("monitor", List.of("svc"),
            Map.of("alert_threshold", 0.95), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testMonitorAlertThresholdOutOfRange() {
        ActionStatement action = new ActionStatement("monitor", List.of("svc"),
            Map.of("alert_threshold", 1.5), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testMigrateDirectionValid() {
        for (String dir : List.of("up", "down")) {
            ActionStatement action = new ActionStatement("migrate", List.of("db"),
                Map.of("direction", dir), null, null, null, null);
            assertTrue(validator.validate(action).isValid());
        }
    }

    @Test
    void testMigrateDirectionInvalid() {
        ActionStatement action = new ActionStatement("migrate", List.of("db"),
            Map.of("direction", "sideways"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testReleaseVersionValidPattern() {
        ActionStatement action = new ActionStatement("release", List.of("1.0.0"),
            Map.of(), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testReleaseVersionInvalidPattern() {
        ActionStatement action = new ActionStatement("release", List.of("v1.0"),
            Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("PATTERN_MISMATCH", result.getErrorCode());
    }

    // ---------- Composition tests ----------

    @Test
    void testRegistryComposesWithUserSchemas() {
        VerbSchema customSchema = new VerbSchema.Builder("custom_verb")
            .addPositionalArg("name", VerbSchema.ArgType.STRING, true, "Custom arg")
            .build();
        registry.register(customSchema);

        assertEquals(13, registry.size());
        assertTrue(registry.hasSchema("custom_verb"));
        assertTrue(registry.hasSchema("build"));

        ActionStatement action = new ActionStatement("custom_verb", List.of("test"), Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertTrue(result.isValid());
    }

    @Test
    void testUserCanOverrideProfileVerb() {
        VerbSchema customBuild = new VerbSchema.Builder("build")
            .addPositionalArg("target", VerbSchema.ArgType.STRING, true, "Build target")
            .addNamedArg("debug", VerbSchema.ArgType.BOOLEAN, false, "Enable debug mode")
            .build();
        registry.register(customBuild);

        assertEquals(12, registry.size());

        // Original 'config' named arg should now be rejected
        ActionStatement action1 = new ActionStatement("build", List.of("proj"), Map.of("config", "release"), null, null, null, null);
        SchemaValidator.ValidationResult result1 = validator.validate(action1);
        assertFalse(result1.isValid());

        // New 'debug' arg should be accepted
        ActionStatement action2 = new ActionStatement("build", List.of("proj"), Map.of("debug", true), null, null, null, null);
        SchemaValidator.ValidationResult result2 = validator.validate(action2);
        assertTrue(result2.isValid());
    }
}
