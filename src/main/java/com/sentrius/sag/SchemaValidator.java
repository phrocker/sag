package com.sentrius.sag;

import com.sentrius.sag.model.ActionStatement;
import com.sentrius.sag.model.ErrorStatement;

import java.util.*;
import java.util.regex.Pattern;

/**
 * Validates ActionStatements against registered verb schemas.
 * Catches argument type mismatches and missing required arguments.
 */
public class SchemaValidator {
    private final SchemaRegistry registry;
    
    public SchemaValidator(SchemaRegistry registry) {
        this.registry = registry;
    }
    
    /**
     * Validate an ActionStatement against its registered schema.
     * @param action The action to validate
     * @return A ValidationResult indicating success or failure
     */
    public ValidationResult validate(ActionStatement action) {
        if (action == null) {
            return ValidationResult.failure("INVALID_ACTION", "Action cannot be null");
        }
        
        String verb = action.getVerb();
        VerbSchema schema = registry.getSchema(verb);
        
        // If no schema is registered, pass validation
        if (schema == null) {
            return ValidationResult.success();
        }
        
        // Validate positional arguments
        List<Object> args = action.getArgs();
        List<VerbSchema.ArgumentSpec> positionalSpecs = schema.getPositionalArgs();
        
        for (int i = 0; i < positionalSpecs.size(); i++) {
            VerbSchema.ArgumentSpec spec = positionalSpecs.get(i);
            
            if (i >= args.size()) {
                if (spec.isRequired()) {
                    return ValidationResult.failure("MISSING_ARG",
                        "Missing required positional argument '" + spec.getName() + "' at position " + i);
                }
            } else {
                Object value = args.get(i);
                if (!isTypeCompatible(value, spec.getType())) {
                    return ValidationResult.failure("TYPE_MISMATCH",
                        "Argument '" + spec.getName() + "' at position " + i +
                        " expected type " + spec.getType() + " but got " + getTypeName(value));
                }
                ValidationResult constraintResult = validateValueConstraints(
                    value, spec, "'" + spec.getName() + "' at position " + i);
                if (!constraintResult.isValid()) {
                    return constraintResult;
                }
            }
        }

        // Check for extra positional args
        if (args.size() > positionalSpecs.size() && !schema.isAllowExtraArgs()) {
            return ValidationResult.failure("TOO_MANY_ARGS",
                "Too many positional arguments: expected " + positionalSpecs.size() + 
                " but got " + args.size());
        }
        
        // Validate named arguments
        Map<String, Object> namedArgs = action.getNamedArgs();
        Map<String, VerbSchema.ArgumentSpec> namedSpecs = schema.getNamedArgs();
        
        // Check for invalid named argument keys
        for (String key : namedArgs.keySet()) {
            if (!namedSpecs.containsKey(key)) {
                if (!schema.isAllowExtraArgs()) {
                    return ValidationResult.failure("INVALID_ARGS",
                        "Expected '" + String.join("', '", namedSpecs.keySet()) + 
                        "', got '" + key + "'");
                }
            }
        }
        
        // Check required named arguments and types
        for (Map.Entry<String, VerbSchema.ArgumentSpec> entry : namedSpecs.entrySet()) {
            String key = entry.getKey();
            VerbSchema.ArgumentSpec spec = entry.getValue();
            
            if (!namedArgs.containsKey(key)) {
                if (spec.isRequired()) {
                    return ValidationResult.failure("MISSING_ARG",
                        "Missing required named argument '" + key + "'");
                }
            } else {
                Object value = namedArgs.get(key);
                if (!isTypeCompatible(value, spec.getType())) {
                    return ValidationResult.failure("TYPE_MISMATCH",
                        "Argument '" + key + "' expected type " + spec.getType() +
                        " but got " + getTypeName(value));
                }
                ValidationResult constraintResult = validateValueConstraints(value, spec, "'" + key + "'");
                if (!constraintResult.isValid()) {
                    return constraintResult;
                }
            }
        }

        return ValidationResult.success();
    }
    
    private ValidationResult validateValueConstraints(Object value, VerbSchema.ArgumentSpec spec, String label) {
        if (value == null) {
            return ValidationResult.success();
        }

        // Enum constraint
        List<Object> allowed = spec.getAllowedValues();
        if (allowed != null && !allowed.contains(value)) {
            return ValidationResult.failure("VALUE_NOT_ALLOWED",
                "Argument " + label + " value '" + value + "' is not in allowed values " + allowed);
        }

        // Pattern constraint (STRING only)
        String pattern = spec.getPattern();
        if (pattern != null && value instanceof String) {
            if (!Pattern.matches(pattern, (String) value)) {
                return ValidationResult.failure("PATTERN_MISMATCH",
                    "Argument " + label + " value '" + value + "' does not match pattern '" + pattern + "'");
            }
        }

        // Range constraint (INTEGER / FLOAT)
        if (value instanceof Number) {
            double numValue = ((Number) value).doubleValue();
            Number minValue = spec.getMinValue();
            if (minValue != null && numValue < minValue.doubleValue()) {
                return ValidationResult.failure("VALUE_OUT_OF_RANGE",
                    "Argument " + label + " value " + value + " is less than minimum " + minValue);
            }
            Number maxValue = spec.getMaxValue();
            if (maxValue != null && numValue > maxValue.doubleValue()) {
                return ValidationResult.failure("VALUE_OUT_OF_RANGE",
                    "Argument " + label + " value " + value + " is greater than maximum " + maxValue);
            }
        }

        return ValidationResult.success();
    }

    private boolean isTypeCompatible(Object value, VerbSchema.ArgType expectedType) {
        if (value == null) {
            return true; // null is compatible with any type
        }
        
        if (expectedType == VerbSchema.ArgType.ANY) {
            return true;
        }
        
        switch (expectedType) {
            case STRING:
                return value instanceof String;
            case INTEGER:
                return value instanceof Integer || value instanceof Long;
            case FLOAT:
                return value instanceof Double || value instanceof Float;
            case BOOLEAN:
                return value instanceof Boolean;
            case LIST:
                return value instanceof List;
            case OBJECT:
                return value instanceof Map;
            default:
                return false;
        }
    }
    
    private String getTypeName(Object value) {
        if (value == null) {
            return "null";
        } else if (value instanceof String) {
            return "String";
        } else if (value instanceof Integer || value instanceof Long) {
            return "Integer";
        } else if (value instanceof Double || value instanceof Float) {
            return "Float";
        } else if (value instanceof Boolean) {
            return "Boolean";
        } else if (value instanceof List) {
            return "List";
        } else if (value instanceof Map) {
            return "Object";
        }
        return value.getClass().getSimpleName();
    }
    
    /**
     * Result of a schema validation check.
     */
    public static class ValidationResult {
        private final boolean valid;
        private final String errorCode;
        private final String errorMessage;
        
        private ValidationResult(boolean valid, String errorCode, String errorMessage) {
            this.valid = valid;
            this.errorCode = errorCode;
            this.errorMessage = errorMessage;
        }
        
        public static ValidationResult success() {
            return new ValidationResult(true, null, null);
        }
        
        public static ValidationResult failure(String errorCode, String errorMessage) {
            return new ValidationResult(false, errorCode, errorMessage);
        }
        
        public boolean isValid() {
            return valid;
        }
        
        public String getErrorCode() {
            return errorCode;
        }
        
        public String getErrorMessage() {
            return errorMessage;
        }
        
        /**
         * Convert validation failure to an ErrorStatement.
         * @return An ErrorStatement if validation failed, null otherwise
         */
        public ErrorStatement toErrorStatement() {
            if (valid) {
                return null;
            }
            return new ErrorStatement(errorCode, errorMessage);
        }
        
        @Override
        public String toString() {
            if (valid) {
                return "ValidationResult{valid=true}";
            }
            return "ValidationResult{valid=false, errorCode='" + errorCode + 
                   "', errorMessage='" + errorMessage + "'}";
        }
    }
}
