package com.sentrius.sag;

import com.sentrius.sag.model.ActionStatement;
import com.sentrius.sag.model.Header;
import com.sentrius.sag.model.Message;
import com.sentrius.sag.model.Statement;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Four-layer validation pipeline for SAG messages: Grammar Parse →
 * Routing Guard → Schema Validate → Guardrail Check.
 *
 * <p>Java port of the Python {@code sag.sanitizer.SAGSanitizer}. Keep
 * behavior identical so cross-runtime messages validate the same way.
 *
 * <p>Use {@link #sanitize(String)} on inbound text (parses + validates);
 * use {@link #sanitizeOutput(Message)} on a pre-parsed {@link Message}
 * (e.g., one we generated locally) to apply layers 2–4 only.
 */
public class SAGSanitizer {

    public enum ErrorType {
        PARSE,
        ROUTING,
        SCHEMA,
        GUARDRAIL
    }

    /**
     * Single validation failure. {@code errorType} disambiguates which
     * layer rejected the message; {@code code} matches the underlying
     * validator's error code (e.g., {@code MISSING_ARG}, {@code
     * UNKNOWN_SOURCE}).
     */
    public record ValidationError(ErrorType errorType, String code, String message) {
    }

    /**
     * Outcome of a sanitize call. {@code valid} is true iff every layer
     * passed (or, with {@code strict=false}, was non-fatal). The
     * {@code message} is populated whenever parse succeeded -- it may be
     * non-null even when {@code valid} is false.
     */
    public record SanitizeResult(boolean valid, Message message, List<ValidationError> errors) {
        public SanitizeResult {
            errors = errors == null ? List.of() : List.copyOf(errors);
        }

        public static SanitizeResult ok(Message message) {
            return new SanitizeResult(true, message, List.of());
        }

        public static SanitizeResult fail(Message message, List<ValidationError> errors) {
            return new SanitizeResult(false, message, errors);
        }
    }

    private final SchemaRegistry schemaRegistry;
    private final AgentRegistry agentRegistry;
    private final SchemaValidator schemaValidator;
    private final Context defaultContext;
    private final boolean strict;

    public SAGSanitizer(SchemaRegistry schemaRegistry, AgentRegistry agentRegistry) {
        this(schemaRegistry, agentRegistry, new MapContext(), true);
    }

    public SAGSanitizer(SchemaRegistry schemaRegistry,
                        AgentRegistry agentRegistry,
                        Context defaultContext,
                        boolean strict) {
        this.schemaRegistry = schemaRegistry;
        this.agentRegistry = agentRegistry;
        this.schemaValidator = new SchemaValidator(schemaRegistry);
        this.defaultContext = defaultContext != null ? defaultContext : new MapContext();
        this.strict = strict;
    }

    /**
     * Run all four layers on raw input text. Layer 1 (Grammar Parse) is
     * fatal: a parse failure short-circuits the pipeline (the later
     * layers need a {@link Message}). Layers 2–4 each contribute
     * {@link ValidationError}s; in strict mode, the first failing layer
     * short-circuits.
     */
    public SanitizeResult sanitize(String rawInput) {
        // Layer 1: Grammar Parse
        Message message;
        try {
            message = SAGMessageParser.parse(rawInput);
        } catch (SAGParseException e) {
            return SanitizeResult.fail(null, List.of(
                new ValidationError(ErrorType.PARSE, "PARSE_ERROR", e.getMessage())));
        }
        return runLayers234(message);
    }

    /**
     * Apply layers 2–4 to an already-parsed message. Used for outbound
     * messages we generated locally (so we don't re-serialize and
     * re-parse them just to validate).
     */
    public SanitizeResult sanitizeOutput(Message message) {
        return runLayers234(message);
    }

    private SanitizeResult runLayers234(Message message) {
        List<ValidationError> errors = new ArrayList<>();

        // Layer 2: Routing Guard
        List<ValidationError> routingErrors = validateRouting(message);
        errors.addAll(routingErrors);
        if (strict && !routingErrors.isEmpty()) {
            return SanitizeResult.fail(message, errors);
        }

        // Layer 3: Schema Validate
        List<ValidationError> schemaErrors = validateSchemas(message);
        errors.addAll(schemaErrors);
        if (strict && !schemaErrors.isEmpty()) {
            return SanitizeResult.fail(message, errors);
        }

        // Layer 4: Guardrail Check
        List<ValidationError> guardrailErrors = validateGuardrails(message);
        errors.addAll(guardrailErrors);
        if (strict && !guardrailErrors.isEmpty()) {
            return SanitizeResult.fail(message, errors);
        }

        if (!errors.isEmpty() && strict) {
            return SanitizeResult.fail(message, errors);
        }
        return new SanitizeResult(true, message, errors);
    }

    private List<ValidationError> validateRouting(Message message) {
        Header header = message.getHeader();
        if (header == null) {
            return Collections.emptyList();
        }
        List<ValidationError> errors = new ArrayList<>();
        String source = header.getSource();
        String destination = header.getDestination();
        if (source != null && !source.isEmpty() && !agentRegistry.isKnown(source)) {
            errors.add(new ValidationError(ErrorType.ROUTING, "UNKNOWN_SOURCE",
                "Unknown source agent: " + source));
        }
        if (destination != null && !destination.isEmpty() && !agentRegistry.isKnown(destination)) {
            errors.add(new ValidationError(ErrorType.ROUTING, "UNKNOWN_DESTINATION",
                "Unknown destination agent: " + destination));
        }
        return errors;
    }

    private List<ValidationError> validateSchemas(Message message) {
        List<ValidationError> errors = new ArrayList<>();
        for (Statement stmt : message.getStatements()) {
            if (stmt instanceof ActionStatement action) {
                SchemaValidator.ValidationResult result = schemaValidator.validate(action);
                if (!result.isValid()) {
                    errors.add(new ValidationError(ErrorType.SCHEMA,
                        result.getErrorCode(), result.getErrorMessage()));
                }
            }
        }
        return errors;
    }

    private List<ValidationError> validateGuardrails(Message message) {
        List<ValidationError> errors = new ArrayList<>();
        for (Statement stmt : message.getStatements()) {
            if (stmt instanceof ActionStatement action) {
                GuardrailValidator.ValidationResult result =
                    GuardrailValidator.validate(action, defaultContext);
                if (!result.isValid()) {
                    errors.add(new ValidationError(ErrorType.GUARDRAIL,
                        result.getErrorCode(), result.getErrorMessage()));
                }
            }
        }
        return errors;
    }
}
