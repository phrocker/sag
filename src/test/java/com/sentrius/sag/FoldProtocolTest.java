package com.sentrius.sag;

import com.sentrius.sag.model.*;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FoldProtocolTest {

    @Test
    void testParseFoldStatement() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "FOLD fold123 \"Summary of conversation\"";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        assertInstanceOf(FoldStatement.class, message.getStatements().get(0));
        FoldStatement fold = (FoldStatement) message.getStatements().get(0);
        assertEquals("fold123", fold.getFoldId());
        assertEquals("Summary of conversation", fold.getSummary());
        assertNull(fold.getState());
    }

    @Test
    void testParseFoldStatementWithState() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "FOLD fold123 \"Summary\" STATE {\"key\": \"value\", \"count\": 42}";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        FoldStatement fold = (FoldStatement) message.getStatements().get(0);
        assertEquals("fold123", fold.getFoldId());
        assertEquals("Summary", fold.getSummary());
        assertNotNull(fold.getState());
        assertEquals("value", fold.getState().get("key"));
        assertEquals(42, fold.getState().get("count"));
    }

    @Test
    void testParseRecallStatement() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "RECALL fold123";

        Message message = SAGMessageParser.parse(input);

        assertEquals(1, message.getStatements().size());
        assertInstanceOf(RecallStatement.class, message.getStatements().get(0));
        RecallStatement recall = (RecallStatement) message.getStatements().get(0);
        assertEquals("fold123", recall.getFoldId());
    }

    @Test
    void testFoldRoundTripMinify() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "FOLD fold123 \"Summary of conversation\"";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("FOLD fold123 \"Summary of conversation\""));

        // Reparse
        Message reparsed = SAGMessageParser.parse(minified);
        assertNotNull(reparsed);
        assertEquals(1, reparsed.getStatements().size());
        assertInstanceOf(FoldStatement.class, reparsed.getStatements().get(0));
    }

    @Test
    void testRecallRoundTripMinify() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "RECALL fold123";

        Message message = SAGMessageParser.parse(input);
        String minified = MessageMinifier.toMinifiedString(message);

        assertTrue(minified.contains("RECALL fold123"));

        // Reparse
        Message reparsed = SAGMessageParser.parse(minified);
        assertNotNull(reparsed);
        assertEquals(1, reparsed.getStatements().size());
        assertInstanceOf(RecallStatement.class, reparsed.getStatements().get(0));
    }

    @Test
    void testMixedStatementsWithFold() throws SAGParseException {
        String input = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                       "DO start(); FOLD fold1 \"Previous work done\"; Q status";

        Message message = SAGMessageParser.parse(input);

        assertEquals(3, message.getStatements().size());
        assertInstanceOf(ActionStatement.class, message.getStatements().get(0));
        assertInstanceOf(FoldStatement.class, message.getStatements().get(1));
        assertInstanceOf(QueryStatement.class, message.getStatements().get(2));
    }
}
