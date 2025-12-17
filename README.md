# SAG - Semantic Action Grammar Library

A Java library for parsing and processing Semantic Action Grammar (SAG) messages using ANTLR4.

## Features

- **Full SAG message parsing** - Complete support for all SAG statement types
- **Comprehensive data model** - Type-safe representation of headers, actions, queries, assertions, control flow, events, and errors
- **Semantic Guardrail Evaluator** - Validate action preconditions before execution
- **Auto-Minifier & Token Counter** - Optimize message size and track token usage
- **Causality Tracking** - Automatic correlation management for multi-agent conversations
- **Verb Schema Enforcement** - Define and validate argument schemas for actions

## Building

```bash
mvn clean install
```

## Usage

### Basic Parsing

```java
import com.sentrius.sag.SAGMessageParser;
import com.sentrius.sag.model.*;

// Parse a SAG message
String sagMessage = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                    "DO deploy(\"app1\", version=2)";

Message message = SAGMessageParser.parse(sagMessage);

// Access header information
Header header = message.getHeader();
System.out.println("Message ID: " + header.getMessageId());
System.out.println("Source: " + header.getSource());
System.out.println("Destination: " + header.getDestination());

// Process statements
for (Statement stmt : message.getStatements()) {
    if (stmt instanceof ActionStatement) {
        ActionStatement action = (ActionStatement) stmt;
        System.out.println("Action: " + action.getVerb());
        System.out.println("Args: " + action.getArgs());
        System.out.println("Named Args: " + action.getNamedArgs());
    }
}
```

### Semantic Guardrail Evaluator

Validate action preconditions before execution:

```java
import com.sentrius.sag.*;

// Create a context with your data
MapContext context = new MapContext();
context.set("balance", 1500);

// Parse an action with a BECAUSE clause
String sagMessage = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n" +
                    "DO transfer(amt=500) BECAUSE balance>1000";
Message message = SAGMessageParser.parse(sagMessage);

// Validate the action against the context
ActionStatement action = (ActionStatement) message.getStatements().get(0);
GuardrailValidator.ValidationResult result = GuardrailValidator.validate(action, context);

if (!result.isValid()) {
    // Precondition failed! Don't execute the action
    System.err.println("Validation failed: " + result.getErrorMessage());
    ErrorStatement error = result.toErrorStatement();
}
```

### Auto-Minifier & Token Counter

Reduce message size and track token usage:

```java
import com.sentrius.sag.*;

Message message = SAGMessageParser.parse(sagMessage);

// Minify the message for efficient transmission
String minified = MessageMinifier.toMinifiedString(message);

// Count tokens
int tokens = MessageMinifier.countTokens(minified);
System.out.println("Message uses " + tokens + " tokens");

// Compare with JSON
MessageMinifier.TokenComparison comparison = MessageMinifier.compareWithJSON(message);
System.out.println(comparison); // Shows tokens saved vs JSON
```

### Causality Tracking

Automatically manage correlation IDs for multi-agent conversations:

```java
import com.sentrius.sag.*;

CorrelationEngine engine = new CorrelationEngine("agent1");

// Record incoming message
Message incoming = SAGMessageParser.parse(incomingMessage);
engine.recordIncoming(incoming);

// Create response with automatic correlation
Header responseHeader = engine.createResponseHeader("agent1", "agent2");
// responseHeader.getCorrelation() will be set to incoming message ID

// Build conversation tree
Map<String, List<String>> tree = CorrelationEngine.buildConversationTree(allMessages);

// Trace a thread of conversation
List<Message> thread = CorrelationEngine.traceThread(allMessages, startMessageId);
```

### Verb Schema Enforcement

Define and validate argument schemas for verbs:

```java
import com.sentrius.sag.*;

// Create a schema registry
SchemaRegistry registry = new SchemaRegistry();

// Define a schema for the 'reorder' verb
VerbSchema reorderSchema = new VerbSchema.Builder("reorder")
    .addNamedArg("item", VerbSchema.ArgType.STRING, true, "Item to reorder")
    .addNamedArg("qty", VerbSchema.ArgType.INTEGER, true, "Quantity")
    .build();
registry.register(reorderSchema);

// Validate actions against schemas
SchemaValidator validator = new SchemaValidator(registry);
ActionStatement action = (ActionStatement) message.getStatements().get(0);
SchemaValidator.ValidationResult result = validator.validate(action);

if (!result.isValid()) {
    System.err.println("Schema validation failed: " + result.getErrorMessage());
    // e.g., "Expected 'item', got 'product'"
}
```

## Statement Types

The library supports all SAG statement types:

- **ActionStatement**: DO commands with optional policy, priority, and reason
- **QueryStatement**: Q statements with optional constraints
- **AssertStatement**: A statements for setting values
- **ControlStatement**: IF-THEN-ELSE conditional execution
- **EventStatement**: EVT event declarations
- **ErrorStatement**: ERR error reporting

## Testing

```bash
mvn test
```

## CI/CD

This project uses GitHub Actions for continuous integration. The pipeline runs on every push and pull request to the main branch.
