package com.sentrius.sag;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ExpressionEvaluatorTest {
    
    @Test
    void testEvaluateSimpleComparison() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("balance", 1500);
        
        Object result = ExpressionEvaluator.evaluate("balance > 1000", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateFailedComparison() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("balance", 400);
        
        Object result = ExpressionEvaluator.evaluate("balance > 1000", context);
        
        assertTrue(result instanceof Boolean);
        assertFalse((Boolean) result);
    }
    
    @Test
    void testEvaluateEquality() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("status", "active");
        
        Object result = ExpressionEvaluator.evaluate("status == \"active\"", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateLogicalAnd() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("balance", 1500);
        context.set("verified", true);
        
        Object result = ExpressionEvaluator.evaluate("(balance > 1000) && (verified == true)", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateLogicalOr() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("balance", 400);
        context.set("verified", true);
        
        Object result = ExpressionEvaluator.evaluate("(balance > 1000) || (verified == true)", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateArithmetic() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("price", 100);
        context.set("quantity", 5);
        
        Object result = ExpressionEvaluator.evaluate("price * quantity", context);
        
        assertTrue(result instanceof Double);
        assertEquals(500.0, (Double) result);
    }
    
    @Test
    void testEvaluateNestedPath() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("user.balance", 1500);
        
        Object result = ExpressionEvaluator.evaluate("user.balance > 1000", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateBooleanValue() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("active", true);
        
        Object result = ExpressionEvaluator.evaluate("active", context);
        
        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }
    
    @Test
    void testEvaluateNullValue() throws SAGParseException {
        MapContext context = new MapContext();
        context.set("value", null);

        Object result = ExpressionEvaluator.evaluate("value == null", context);

        assertTrue(result instanceof Boolean);
        assertTrue((Boolean) result);
    }

    /**
     * Phase 7 / SAG 1.2: path segments can carry an optional `:suffix`,
     * so vertex ids like `memory:abc` or `rationale:hex123` parse as
     * the head of a path. The Context's dot-split lookup interprets
     * `memory:abc.confidence` as `_data["memory:abc"]["confidence"]`.
     */
    @Test
    void testPathWithColonPrefix() throws SAGParseException {
        MapContext context = new MapContext();
        java.util.Map<String, Object> vertexProps = new java.util.HashMap<>();
        vertexProps.put("confidence", 0.9);
        context.set("memory:abc", vertexProps);

        Object greater = ExpressionEvaluator.evaluate("memory:abc.confidence > 0.5", context);
        assertTrue(greater instanceof Boolean);
        assertTrue((Boolean) greater);

        Object less = ExpressionEvaluator.evaluate("memory:abc.confidence < 0.5", context);
        assertTrue(less instanceof Boolean);
        assertFalse((Boolean) less);
    }

    @Test
    void testPathWithRationaleColonPrefix() throws SAGParseException {
        MapContext context = new MapContext();
        java.util.Map<String, Object> rationaleProps = new java.util.HashMap<>();
        rationaleProps.put("trust", 0.95);
        context.set("rationale:hexabc", rationaleProps);

        Object result = ExpressionEvaluator.evaluate(
            "rationale:hexabc.trust >= 0.9", context);
        assertTrue((Boolean) result);
    }

    @Test
    void testPathWithIntegerSuffix() throws SAGParseException {
        // pathSeg accepts INT after `:` so positional refs like `e0`/`e1`
        // ALSO still parse if anyone wants that style.
        MapContext context = new MapContext();
        java.util.Map<String, Object> v = new java.util.HashMap<>();
        v.put("score", 0.8);
        context.set("slot:0", v);

        Object result = ExpressionEvaluator.evaluate("slot:0.score > 0.5", context);
        assertTrue((Boolean) result);
    }
}
