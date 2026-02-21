package com.sentrius.sag;

import java.util.*;

/**
 * Defines the schema for a verb's arguments.
 * Like an API specification for SAG verbs.
 */
public class VerbSchema {
    private final String verbName;
    private final List<ArgumentSpec> positionalArgs;
    private final Map<String, ArgumentSpec> namedArgs;
    private final boolean allowExtraArgs;
    
    private VerbSchema(Builder builder) {
        this.verbName = builder.verbName;
        this.positionalArgs = new ArrayList<>(builder.positionalArgs);
        this.namedArgs = new HashMap<>(builder.namedArgs);
        this.allowExtraArgs = builder.allowExtraArgs;
    }
    
    public String getVerbName() {
        return verbName;
    }
    
    public List<ArgumentSpec> getPositionalArgs() {
        return Collections.unmodifiableList(positionalArgs);
    }
    
    public Map<String, ArgumentSpec> getNamedArgs() {
        return Collections.unmodifiableMap(namedArgs);
    }
    
    public boolean isAllowExtraArgs() {
        return allowExtraArgs;
    }
    
    /**
     * Specification for an argument.
     */
    public static class ArgumentSpec {
        private final String name;
        private final ArgType type;
        private final boolean required;
        private final String description;
        private final List<Object> allowedValues;
        private final String pattern;
        private final Number minValue;
        private final Number maxValue;

        public ArgumentSpec(String name, ArgType type, boolean required, String description) {
            this(name, type, required, description, null, null, null, null);
        }

        public ArgumentSpec(String name, ArgType type, boolean required, String description,
                            List<Object> allowedValues, String pattern, Number minValue, Number maxValue) {
            this.name = name;
            this.type = type;
            this.required = required;
            this.description = description;
            this.allowedValues = allowedValues;
            this.pattern = pattern;
            this.minValue = minValue;
            this.maxValue = maxValue;

            if (pattern != null && type != ArgType.STRING) {
                throw new IllegalArgumentException(
                    "pattern constraint only applies to STRING arguments, got " + type);
            }
            if ((minValue != null || maxValue != null) && type != ArgType.INTEGER && type != ArgType.FLOAT) {
                throw new IllegalArgumentException(
                    "range constraints only apply to INTEGER or FLOAT arguments, got " + type);
            }
        }

        public String getName() { return name; }
        public ArgType getType() { return type; }
        public boolean isRequired() { return required; }
        public String getDescription() { return description; }
        public List<Object> getAllowedValues() { return allowedValues; }
        public String getPattern() { return pattern; }
        public Number getMinValue() { return minValue; }
        public Number getMaxValue() { return maxValue; }
    }
    
    /**
     * Supported argument types.
     */
    public enum ArgType {
        STRING, INTEGER, FLOAT, BOOLEAN, LIST, OBJECT, ANY
    }
    
    /**
     * Builder for VerbSchema.
     */
    public static class Builder {
        private final String verbName;
        private final List<ArgumentSpec> positionalArgs = new ArrayList<>();
        private final Map<String, ArgumentSpec> namedArgs = new HashMap<>();
        private boolean allowExtraArgs = false;
        
        public Builder(String verbName) {
            this.verbName = verbName;
        }
        
        public Builder addPositionalArg(String name, ArgType type, boolean required, String description) {
            positionalArgs.add(new ArgumentSpec(name, type, required, description));
            return this;
        }

        public Builder addPositionalArg(String name, ArgType type, boolean required, String description,
                                         List<Object> allowedValues, String pattern, Number minValue, Number maxValue) {
            positionalArgs.add(new ArgumentSpec(name, type, required, description, allowedValues, pattern, minValue, maxValue));
            return this;
        }

        public Builder addNamedArg(String name, ArgType type, boolean required, String description) {
            namedArgs.put(name, new ArgumentSpec(name, type, required, description));
            return this;
        }

        public Builder addNamedArg(String name, ArgType type, boolean required, String description,
                                    List<Object> allowedValues, String pattern, Number minValue, Number maxValue) {
            namedArgs.put(name, new ArgumentSpec(name, type, required, description, allowedValues, pattern, minValue, maxValue));
            return this;
        }
        
        public Builder allowExtraArgs(boolean allow) {
            this.allowExtraArgs = allow;
            return this;
        }
        
        public VerbSchema build() {
            return new VerbSchema(this);
        }
    }
    
    @Override
    public String toString() {
        return "VerbSchema{" +
               "verbName='" + verbName + '\'' +
               ", positionalArgs=" + positionalArgs.size() +
               ", namedArgs=" + namedArgs.size() +
               ", allowExtraArgs=" + allowExtraArgs +
               '}';
    }
}
