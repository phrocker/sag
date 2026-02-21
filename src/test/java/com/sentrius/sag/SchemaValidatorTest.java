package com.sentrius.sag;

import com.sentrius.sag.model.ActionStatement;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

class SchemaValidatorTest {
    
    private SchemaRegistry registry;
    private SchemaValidator validator;
    
    @BeforeEach
    void setUp() {
        registry = new SchemaRegistry();
        validator = new SchemaValidator(registry);
        
        // Register a 'reorder' verb schema
        VerbSchema reorderSchema = new VerbSchema.Builder("reorder")
            .addNamedArg("item", VerbSchema.ArgType.STRING, true, "Item to reorder")
            .addNamedArg("qty", VerbSchema.ArgType.INTEGER, true, "Quantity")
            .build();
        registry.register(reorderSchema);
        
        // Register a 'deploy' verb schema with both positional and named args
        VerbSchema deploySchema = new VerbSchema.Builder("deploy")
            .addPositionalArg("app", VerbSchema.ArgType.STRING, true, "Application name")
            .addNamedArg("version", VerbSchema.ArgType.INTEGER, false, "Version number")
            .addNamedArg("env", VerbSchema.ArgType.STRING, false, "Environment")
            .build();
        registry.register(deploySchema);
    }
    
    @Test
    void testValidActionWithCorrectArgs() {
        ActionStatement action = new ActionStatement(
            "reorder",
            Collections.emptyList(),
            Map.of("item", "laptop", "qty", 5),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertTrue(result.isValid());
    }
    
    @Test
    void testInvalidActionWithWrongKeyName() {
        ActionStatement action = new ActionStatement(
            "reorder",
            Collections.emptyList(),
            Map.of("product", "laptop", "qty", 5), // Wrong key 'product' instead of 'item'
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertFalse(result.isValid());
        assertEquals("INVALID_ARGS", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("product"));
    }
    
    @Test
    void testMissingRequiredArg() {
        ActionStatement action = new ActionStatement(
            "reorder",
            Collections.emptyList(),
            Map.of("item", "laptop"), // Missing required 'qty'
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertFalse(result.isValid());
        assertEquals("MISSING_ARG", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("qty"));
    }
    
    @Test
    void testTypeMismatch() {
        ActionStatement action = new ActionStatement(
            "reorder",
            Collections.emptyList(),
            Map.of("item", "laptop", "qty", "five"), // qty should be Integer, not String
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("qty"));
    }
    
    @Test
    void testUnregisteredVerbPassesValidation() {
        ActionStatement action = new ActionStatement(
            "unknownVerb",
            Collections.emptyList(),
            Map.of("any", "value"),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        // No schema registered, so validation passes
        assertTrue(result.isValid());
    }
    
    @Test
    void testPositionalArgsValidation() {
        ActionStatement action = new ActionStatement(
            "deploy",
            List.of("myapp"), // Correct positional arg
            Map.of("version", 2),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertTrue(result.isValid());
    }
    
    @Test
    void testMissingRequiredPositionalArg() {
        ActionStatement action = new ActionStatement(
            "deploy",
            Collections.emptyList(), // Missing required positional arg 'app'
            Map.of("version", 2),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertFalse(result.isValid());
        assertEquals("MISSING_ARG", result.getErrorCode());
    }
    
    @Test
    void testWrongTypeForPositionalArg() {
        ActionStatement action = new ActionStatement(
            "deploy",
            List.of(123), // Should be String, not Integer
            Map.of("version", 2),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertFalse(result.isValid());
        assertEquals("TYPE_MISMATCH", result.getErrorCode());
    }
    
    @Test
    void testOptionalArgNotRequired() {
        ActionStatement action = new ActionStatement(
            "deploy",
            List.of("myapp"),
            Collections.emptyMap(), // Optional args not provided
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertTrue(result.isValid());
    }
    
    @Test
    void testToErrorStatement() {
        SchemaValidator.ValidationResult result = SchemaValidator.ValidationResult.failure(
            "INVALID_ARGS",
            "Test error message"
        );
        
        assertNotNull(result.toErrorStatement());
        assertEquals("INVALID_ARGS", result.toErrorStatement().getErrorCode());
        assertEquals("Test error message", result.toErrorStatement().getMessage());
    }
    
    @Test
    void testSchemaWithAllowExtraArgs() {
        VerbSchema flexibleSchema = new VerbSchema.Builder("flexibleVerb")
            .addNamedArg("required", VerbSchema.ArgType.STRING, true, "Required arg")
            .allowExtraArgs(true)
            .build();
        registry.register(flexibleSchema);
        
        ActionStatement action = new ActionStatement(
            "flexibleVerb",
            Collections.emptyList(),
            Map.of("required", "value", "extra", "allowed"),
            null, null, null, null
        );
        
        SchemaValidator.ValidationResult result = validator.validate(action);
        
        assertTrue(result.isValid());
    }
    
    @Test
    void testRegistryOperations() {
        assertEquals(2, registry.size());
        assertTrue(registry.hasSchema("reorder"));
        assertTrue(registry.hasSchema("deploy"));

        VerbSchema schema = registry.getSchema("reorder");
        assertNotNull(schema);
        assertEquals("reorder", schema.getVerbName());

        registry.unregister("reorder");
        assertFalse(registry.hasSchema("reorder"));
        assertEquals(1, registry.size());

        registry.clear();
        assertEquals(0, registry.size());
    }

    // ---------- Enum constraint tests ----------

    @Test
    void testEnumConstraintAllowedValuePasses() {
        VerbSchema schema = new VerbSchema.Builder("setenv")
            .addNamedArg("env", VerbSchema.ArgType.STRING, true, "Environment",
                List.of("dev", "staging", "production"), null, null, null)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("setenv", List.of(),
            Map.of("env", "dev"), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testEnumConstraintDisallowedValueFails() {
        VerbSchema schema = new VerbSchema.Builder("setenv")
            .addNamedArg("env", VerbSchema.ArgType.STRING, true, "Environment",
                List.of("dev", "staging", "production"), null, null, null)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("setenv", List.of(),
            Map.of("env", "local"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("local"));
    }

    @Test
    void testEnumConstraintNullPasses() {
        VerbSchema schema = new VerbSchema.Builder("setenv")
            .addNamedArg("env", VerbSchema.ArgType.STRING, false, "Environment",
                List.of("dev", "staging"), null, null, null)
            .build();
        registry.register(schema);

        Map<String, Object> namedArgs = new HashMap<>();
        namedArgs.put("env", null);
        ActionStatement action = new ActionStatement("setenv", List.of(),
            namedArgs, null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    // ---------- Pattern constraint tests ----------

    @Test
    void testPatternConstraintMatchingPasses() {
        VerbSchema schema = new VerbSchema.Builder("tag")
            .addPositionalArg("version", VerbSchema.ArgType.STRING, true, "Semver",
                null, "^\\d+\\.\\d+\\.\\d+$", null, null)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("tag", List.of("1.2.3"),
            Map.of(), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testPatternConstraintNonMatchingFails() {
        VerbSchema schema = new VerbSchema.Builder("tag")
            .addPositionalArg("version", VerbSchema.ArgType.STRING, true, "Semver",
                null, "^\\d+\\.\\d+\\.\\d+$", null, null)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("tag", List.of("v1.2"),
            Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("PATTERN_MISMATCH", result.getErrorCode());
    }

    @Test
    void testPatternOnNonStringTypeThrows() {
        assertThrows(IllegalArgumentException.class, () ->
            new VerbSchema.ArgumentSpec("x", VerbSchema.ArgType.INTEGER, true, "", null, "\\d+", null, null));
    }

    // ---------- Range constraint tests ----------

    @Test
    void testRangeConstraintInRangePasses() {
        VerbSchema schema = new VerbSchema.Builder("scale")
            .addNamedArg("replicas", VerbSchema.ArgType.INTEGER, true, "Replicas",
                null, null, 1, 100)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("scale", List.of(),
            Map.of("replicas", 5), null, null, null, null);
        assertTrue(validator.validate(action).isValid());
    }

    @Test
    void testRangeConstraintAtBoundariesPasses() {
        VerbSchema schema = new VerbSchema.Builder("scale")
            .addNamedArg("replicas", VerbSchema.ArgType.INTEGER, true, "Replicas",
                null, null, 1, 100)
            .build();
        registry.register(schema);

        ActionStatement minAction = new ActionStatement("scale", List.of(),
            Map.of("replicas", 1), null, null, null, null);
        assertTrue(validator.validate(minAction).isValid());

        ActionStatement maxAction = new ActionStatement("scale", List.of(),
            Map.of("replicas", 100), null, null, null, null);
        assertTrue(validator.validate(maxAction).isValid());
    }

    @Test
    void testRangeConstraintBelowMinFails() {
        VerbSchema schema = new VerbSchema.Builder("scale")
            .addNamedArg("replicas", VerbSchema.ArgType.INTEGER, true, "Replicas",
                null, null, 1, 100)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("scale", List.of(),
            Map.of("replicas", 0), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("less than minimum"));
    }

    @Test
    void testRangeConstraintAboveMaxFails() {
        VerbSchema schema = new VerbSchema.Builder("scale")
            .addNamedArg("replicas", VerbSchema.ArgType.INTEGER, true, "Replicas",
                null, null, 1, 100)
            .build();
        registry.register(schema);

        ActionStatement action = new ActionStatement("scale", List.of(),
            Map.of("replicas", 101), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
        assertTrue(result.getErrorMessage().contains("greater than maximum"));
    }

    @Test
    void testFloatRangeConstraint() {
        VerbSchema schema = new VerbSchema.Builder("adjust")
            .addNamedArg("threshold", VerbSchema.ArgType.FLOAT, true, "Threshold",
                null, null, 0.0, 1.0)
            .build();
        registry.register(schema);

        ActionStatement goodAction = new ActionStatement("adjust", List.of(),
            Map.of("threshold", 0.5), null, null, null, null);
        assertTrue(validator.validate(goodAction).isValid());

        ActionStatement badAction = new ActionStatement("adjust", List.of(),
            Map.of("threshold", 1.5), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(badAction);
        assertFalse(result.isValid());
        assertEquals("VALUE_OUT_OF_RANGE", result.getErrorCode());
    }

    @Test
    void testRangeOnStringTypeThrows() {
        assertThrows(IllegalArgumentException.class, () ->
            new VerbSchema.ArgumentSpec("x", VerbSchema.ArgType.STRING, true, "", null, null, 1, 10));
    }

    // ---------- Constraint order tests ----------

    @Test
    void testEnumCheckedBeforePattern() {
        VerbSchema schema = new VerbSchema.Builder("combo")
            .addNamedArg("val", VerbSchema.ArgType.STRING, true, "Value",
                List.of("abc", "def"), "^[a-z]+$", null, null)
            .build();
        registry.register(schema);

        // "xyz" matches pattern but not enum — should get VALUE_NOT_ALLOWED
        ActionStatement action = new ActionStatement("combo", List.of(),
            Map.of("val", "xyz"), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(action);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }

    @Test
    void testPositionalEnumConstraint() {
        VerbSchema schema = new VerbSchema.Builder("choose")
            .addPositionalArg("color", VerbSchema.ArgType.STRING, true, "Color",
                List.of("red", "green", "blue"), null, null, null)
            .build();
        registry.register(schema);

        ActionStatement good = new ActionStatement("choose", List.of("red"),
            Map.of(), null, null, null, null);
        assertTrue(validator.validate(good).isValid());

        ActionStatement bad = new ActionStatement("choose", List.of("yellow"),
            Map.of(), null, null, null, null);
        SchemaValidator.ValidationResult result = validator.validate(bad);
        assertFalse(result.isValid());
        assertEquals("VALUE_NOT_ALLOWED", result.getErrorCode());
    }
}
