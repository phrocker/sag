package com.sentrius.sag;

import com.sentrius.sag.model.Message;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class SAGSanitizerTest {

    private static final String HDR_AB =
        "H v 1 id=msg1 src=agent-a dst=agent-b ts=1234567890\n";

    private SchemaRegistry schemaRegistry;
    private AgentRegistry agentRegistry;
    private SAGSanitizer sanitizer;

    @BeforeEach
    void setUp() {
        schemaRegistry = new SchemaRegistry();
        agentRegistry = new AgentRegistry();
        agentRegistry.register("agent-a");
        agentRegistry.register("agent-b");

        VerbSchema reorder = new VerbSchema.Builder("reorder")
            .addNamedArg("item", VerbSchema.ArgType.STRING, true, "Item")
            .addNamedArg("qty", VerbSchema.ArgType.INTEGER, true, "Quantity")
            .build();
        schemaRegistry.register(reorder);

        sanitizer = new SAGSanitizer(schemaRegistry, agentRegistry);
    }

    @Test
    void parseFailureShortCircuitsAndReturnsParseError() {
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize("not a valid sag message");
        assertFalse(r.valid());
        assertEquals(1, r.errors().size());
        assertEquals(SAGSanitizer.ErrorType.PARSE, r.errors().get(0).errorType());
        assertEquals("PARSE_ERROR", r.errors().get(0).code());
        assertNull(r.message());
    }

    @Test
    void unknownSourceAgentTripsRoutingGuard() {
        // agent-c is not registered
        String raw = "H v 1 id=m src=agent-c dst=agent-b ts=1\n" +
                     "DO reorder(item=\"x\", qty=1)";
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize(raw);
        assertFalse(r.valid(), "errors=" + r.errors());
        assertNotNull(r.message(), "parse should have succeeded; routing should fail");
        assertEquals(1, r.errors().size());
        assertEquals(SAGSanitizer.ErrorType.ROUTING, r.errors().get(0).errorType());
        assertEquals("UNKNOWN_SOURCE", r.errors().get(0).code());
    }

    @Test
    void unknownDestinationAgentTripsRoutingGuard() {
        String raw = "H v 1 id=m src=agent-a dst=agent-z ts=1\n" +
                     "DO reorder(item=\"x\", qty=1)";
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize(raw);
        assertFalse(r.valid(), "errors=" + r.errors());
        assertEquals("UNKNOWN_DESTINATION", r.errors().get(0).code());
    }

    @Test
    void schemaViolationTripsSchemaLayer() {
        // Missing required 'qty' arg
        String raw = HDR_AB + "DO reorder(item=\"x\")";
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize(raw);
        assertFalse(r.valid(), "errors=" + r.errors());
        assertEquals(SAGSanitizer.ErrorType.SCHEMA, r.errors().get(0).errorType());
        assertEquals("MISSING_ARG", r.errors().get(0).code());
    }

    @Test
    void allLayersPassYieldsValidWithMessage() {
        String raw = HDR_AB + "DO reorder(item=\"laptop\", qty=5)";
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize(raw);
        assertTrue(r.valid(), "expected valid; errors=" + r.errors());
        assertNotNull(r.message());
        assertTrue(r.errors().isEmpty());
    }

    @Test
    void sanitizeOutputSkipsParseLayer() throws SAGParseException {
        String raw = HDR_AB + "DO reorder(item=\"x\", qty=1)";
        Message m = SAGMessageParser.parse(raw);
        SAGSanitizer.SanitizeResult r = sanitizer.sanitizeOutput(m);
        assertTrue(r.valid(), "errors=" + r.errors());
    }

    @Test
    void nonStrictModeAccumulatesErrorsWithoutShortCircuiting() {
        SAGSanitizer lax = new SAGSanitizer(schemaRegistry, agentRegistry, new MapContext(), false);
        // Routing error AND schema error in one message
        String raw = "H v 1 id=m src=ghost-agent dst=agent-b ts=1\n" +
                     "DO reorder(item=\"x\")";
        SAGSanitizer.SanitizeResult r = lax.sanitize(raw);
        assertEquals(2, r.errors().size(),
            "expected routing + schema errors both reported in non-strict mode; got " + r.errors());
    }

    @Test
    void unregisteredVerbBypassesSchemaLayer() {
        String raw = HDR_AB + "DO unknown_verb(arg=\"x\")";
        SAGSanitizer.SanitizeResult r = sanitizer.sanitize(raw);
        assertTrue(r.valid(), "errors=" + r.errors());
    }
}
