# SAG - Semantic Action Grammar Library

A Java library for parsing and processing Semantic Action Grammar (SAG) messages using ANTLR4.

## Features

- Full SAG message parsing
- Comprehensive data model for all statement types
- Visitor pattern implementation for AST traversal
- Type-safe representation of headers, actions, queries, assertions, control flow, events, and errors

## Building

```bash
mvn clean install
```

## Usage

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
