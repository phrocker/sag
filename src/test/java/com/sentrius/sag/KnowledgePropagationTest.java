package com.sentrius.sag;

import com.sentrius.sag.model.*;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class KnowledgePropagationTest {

    @Test
    void testParseSubWildcard() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.*";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        assertInstanceOf(SubscribeStatement.class, message.getStatements().get(0));
        SubscribeStatement sub = (SubscribeStatement) message.getStatements().get(0);
        assertEquals("system.*", sub.getTopic());
        assertNull(sub.getFilterExpr());
    }

    @Test
    void testParseSubMultiLevelWildcard() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.**";

        Message message = SAGMessageParser.parse(input);

        SubscribeStatement sub = (SubscribeStatement) message.getStatements().get(0);
        assertEquals("system.**", sub.getTopic());
    }

    @Test
    void testParseSubExactTopic() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.cpu";

        Message message = SAGMessageParser.parse(input);

        SubscribeStatement sub = (SubscribeStatement) message.getStatements().get(0);
        assertEquals("system.cpu", sub.getTopic());
        assertNull(sub.getFilterExpr());
    }

    @Test
    void testParseSubWithFilter() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.** WHERE cpu>80";

        Message message = SAGMessageParser.parse(input);

        SubscribeStatement sub = (SubscribeStatement) message.getStatements().get(0);
        assertEquals("system.**", sub.getTopic());
        assertNotNull(sub.getFilterExpr());
        assertTrue(sub.getFilterExpr().contains("cpu"));
    }

    @Test
    void testParseUnsub() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "UNSUB system.*";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        assertInstanceOf(UnsubscribeStatement.class, message.getStatements().get(0));
        UnsubscribeStatement unsub = (UnsubscribeStatement) message.getStatements().get(0);
        assertEquals("system.*", unsub.getTopic());
    }

    @Test
    void testParseKnowInt() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "KNOW system.cpu = 85 v 3";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        assertInstanceOf(KnowledgeStatement.class, message.getStatements().get(0));
        KnowledgeStatement know = (KnowledgeStatement) message.getStatements().get(0);
        assertEquals("system.cpu", know.getTopic());
        assertEquals(85, know.getValue());
        assertEquals(3, know.getVersion());
    }

    @Test
    void testParseKnowFloat() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "KNOW system.cpu = 85.2 v 3";

        Message message = SAGMessageParser.parse(input);

        KnowledgeStatement know = (KnowledgeStatement) message.getStatements().get(0);
        assertEquals(85.2, know.getValue());
        assertEquals(3, know.getVersion());
    }

    @Test
    void testParseKnowString() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "KNOW deployment.status = \"healthy\" v 1";

        Message message = SAGMessageParser.parse(input);

        KnowledgeStatement know = (KnowledgeStatement) message.getStatements().get(0);
        assertEquals("deployment.status", know.getTopic());
        assertEquals("healthy", know.getValue());
        assertEquals(1, know.getVersion());
    }

    @Test
    void testParseKnowBool() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "KNOW system.healthy = true v 5";

        Message message = SAGMessageParser.parse(input);

        KnowledgeStatement know = (KnowledgeStatement) message.getStatements().get(0);
        assertEquals(true, know.getValue());
        assertEquals(5, know.getVersion());
    }

    @Test
    void testSubRoundTrip() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.*";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("SUB system.*"));

        Message reparsed = SAGMessageParser.parse(minified);
        assertNotNull(reparsed);
        assertEquals(1, reparsed.getStatements().size());
        assertInstanceOf(SubscribeStatement.class, reparsed.getStatements().get(0));
        assertEquals("system.*", ((SubscribeStatement) reparsed.getStatements().get(0)).getTopic());
    }

    @Test
    void testSubWithFilterRoundTrip() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "SUB system.** WHERE cpu>80";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("SUB system.**"));
        assertTrue(minified.contains("WHERE"));

        Message reparsed = SAGMessageParser.parse(minified);
        SubscribeStatement sub = (SubscribeStatement) reparsed.getStatements().get(0);
        assertEquals("system.**", sub.getTopic());
        assertNotNull(sub.getFilterExpr());
    }

    @Test
    void testUnsubRoundTrip() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "UNSUB system.*";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("UNSUB system.*"));

        Message reparsed = SAGMessageParser.parse(minified);
        assertInstanceOf(UnsubscribeStatement.class, reparsed.getStatements().get(0));
    }

    @Test
    void testKnowRoundTrip() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "KNOW deployment.status = \"healthy\" v 1";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("KNOW deployment.status"));
        assertTrue(minified.contains("v 1"));

        Message reparsed = SAGMessageParser.parse(minified);
        KnowledgeStatement know = (KnowledgeStatement) reparsed.getStatements().get(0);
        assertEquals("deployment.status", know.getTopic());
        assertEquals("healthy", know.getValue());
        assertEquals(1, know.getVersion());
    }

    @Test
    void testMixedStatementsWithKnowledge() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "DO start(); SUB system.*; KNOW system.cpu = 85 v 3";

        Message message = SAGMessageParser.parse(input);

        assertEquals(3, message.getStatements().size());
        assertInstanceOf(ActionStatement.class, message.getStatements().get(0));
        assertInstanceOf(SubscribeStatement.class, message.getStatements().get(1));
        assertInstanceOf(KnowledgeStatement.class, message.getStatements().get(2));
    }
}
