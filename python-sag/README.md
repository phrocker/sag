# semantic-action-grammar

Semantic Action Grammar (SAG) — a typed, parseable DSL for structured
inter-agent communication.

SAG is what JSON would look like if it were designed for agent-to-agent
messaging instead of REST. It carries actions, queries, asserts, events,
errors, control flow, knowledge facts, and a fold/unfold protocol for
context compression — all in a wire format that's ~59% smaller than the
equivalent JSON envelope and validatable without an LLM in the loop.

This package is the Python implementation. The canonical ANTLR4 grammar
and the Java implementation live in the
[main repository](https://github.com/phrocker/sag).

## Install

```bash
pip install semantic-action-grammar
```

Python 3.10+ required. The only runtime dependency is
`antlr4-python3-runtime`. The import name is `sag`:

```python
from sag import SAGMessageParser
```

## Wire format at a glance

A SAG message is one header line followed by one or more typed
statements:

```
H v 1 id=msg1 src=agentA dst=agentB ts=1700000000 corr=parent1 ttl=30
DO deploy("app1", version=42) P:security PRIO=HIGH BECAUSE balance>1000;
Q health.status WHERE cpu>80;
A state.ready = true;
IF ready==true THEN DO start() ELSE DO wait();
EVT deployComplete("app1");
ERR TIMEOUT "Connection timed out";
KNOW system.cpu = 85 v 3;
FOLD f1 "Completed onboarding" STATE {"users":42};
RECALL f1
```

| Statement | Syntax | Purpose |
|-----------|--------|---------|
| Action | `DO verb(args) [P:policy] [PRIO=...] [BECAUSE expr]` | Execute commands |
| Query | `Q expr [WHERE constraint]` | Query state |
| Assert | `A path = value` | Set state |
| Control | `IF expr THEN stmt [ELSE stmt]` | Conditional |
| Event | `EVT name(args)` | Emit events |
| Error | `ERR code "message"` | Report errors |
| Fold | `FOLD id "summary" [STATE {...}]` | Compress context |
| Recall | `RECALL id` | Restore context |
| Subscribe | `SUB pattern [WHERE filter]` | Subscribe to topics |
| Unsubscribe | `UNSUB pattern` | Unsubscribe |
| Knowledge | `KNOW topic = value v N` | Share versioned facts |

## Quick start

```python
from sag import SAGMessageParser, MessageMinifier, ActionStatement

text = (
    'H v 1 id=msg1 src=agentA dst=agentB ts=1700000000\n'
    'DO deploy("app1", version=42) BECAUSE balance>1000'
)

message = SAGMessageParser.parse(text)

# Header fields
print(message.header.message_id)  # "msg1"
print(message.header.source)      # "agentA"
print(message.header.destination) # "agentB"

# Typed statements
for stmt in message.statements:
    if isinstance(stmt, ActionStatement):
        print(stmt.verb)        # "deploy"
        print(stmt.args)        # ["app1"]
        print(stmt.named_args)  # {"version": 42}
        print(stmt.reason)      # "balance>1000"

# Re-serialize to the compact wire format
print(MessageMinifier.to_minified_string(message))
```

## Validating without an LLM

### Guardrails — `BECAUSE` clauses as preconditions

```python
from sag import GuardrailValidator, MapContext, ActionStatement

context = MapContext({"balance": 1500})

action = ActionStatement(
    verb="transfer",
    args=[],
    named_args={"amt": 500},
    reason="balance > 1000",
)

result = GuardrailValidator.validate(action, context)
assert result.is_valid is True

# Same action, insufficient balance:
context = MapContext({"balance": 400})
result = GuardrailValidator.validate(action, context)
assert result.is_valid is False
assert result.error_code == "PRECONDITION_FAILED"
```

### Schema validation — typed argument contracts

```python
from sag import (
    ActionStatement,
    ArgType,
    SchemaRegistry,
    SchemaValidator,
    VerbSchema,
)

registry = SchemaRegistry()
registry.register(
    VerbSchema.Builder("deploy")
    .add_positional_arg("app", ArgType.STRING, True, "Application name")
    .add_named_arg("env", ArgType.STRING, False, "Environment",
                   allowed_values=["dev", "staging", "production"])
    .add_named_arg("replicas", ArgType.INTEGER, False, "Replica count",
                   min_value=1, max_value=100)
    .build()
)
validator = SchemaValidator(registry)

ok = ActionStatement(verb="deploy", args=["webapp"],
                     named_args={"env": "production", "replicas": 3})
assert validator.validate(ok).is_valid

bad = ActionStatement(verb="deploy", args=["webapp"],
                      named_args={"env": "qa"})  # not in enum
assert not validator.validate(bad).is_valid
```

### Pre-built schema profile (CI/CD)

`SoftwareDevProfile` ships with 12 verbs configured for build, test,
deploy, rollback, review, merge, lint, scan, release, provision,
monitor, and migrate workflows — including value constraints (enums
for environments, regex for SemVer, ranges for replicas/timeouts).

```python
from sag import SoftwareDevProfile, SchemaValidator, ActionStatement

registry = SoftwareDevProfile.create_registry()
validator = SchemaValidator(registry)

action = ActionStatement(
    verb="deploy",
    args=["webapp"],
    named_args={"env": "production", "replicas": 3},
)
assert validator.validate(action).is_valid
```

### Sanitizer — the four-layer firewall

The sanitizer chains grammar parse → routing guard → schema validation
→ guardrail check into one call. Anything that fails any layer is
rejected before reaching your agents.

```python
from sag import (
    AgentRegistry,
    MapContext,
    SAGSanitizer,
    SchemaRegistry,
    VerbSchema,
    ArgType,
)

schemas = SchemaRegistry()
schemas.register(
    VerbSchema.Builder("deploy")
    .add_positional_arg("app", ArgType.STRING, True, "Application name")
    .build()
)

agents = AgentRegistry()
agents.register("svc1")
agents.register("svc2")

sanitizer = SAGSanitizer(
    schema_registry=schemas,
    agent_registry=agents,
    default_context=MapContext({"balance": 1500}),
)

ok = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1700000000\nDO deploy("app1")'
assert sanitizer.sanitize(ok).valid

# Unknown source — caught at the routing layer
bad = 'H v 1 id=msg1 src=ghost dst=svc2 ts=1700000000\nDO deploy("app1")'
result = sanitizer.sanitize(bad)
assert not result.valid
assert result.errors[0].error_type.name == "ROUTING"
```

## Compressing context — fold / unfold

The fold protocol collapses completed conversation segments into a
single statement with optional preserved state. `unfold` recovers the
original messages exactly — 100% roundtrip fidelity in the test suite.

```python
from sag import FoldEngine, SAGMessageParser

engine = FoldEngine()

m1 = SAGMessageParser.parse(
    "H v 1 id=m1 src=a dst=b ts=1700000000\nDO start()"
)
m2 = SAGMessageParser.parse(
    "H v 1 id=m2 src=b dst=a ts=1700000001\nA status.ready = true"
)

fold = engine.fold([m1, m2], "Completed startup", state={"phase": "running"})
print(fold.fold_id, fold.summary, fold.state)

restored = engine.unfold(fold.fold_id)
assert restored == [m1, m2]   # exact equality

# Detect when context pressure should trigger a fold
big = [m1, m2] * 100
assert engine.detect_pressure(big, budget=200, threshold=0.5) is True
```

## Token efficiency — SAG vs JSON

```python
from sag import SAGMessageParser, MessageMinifier

msg = SAGMessageParser.parse(
    'H v 1 id=msg1 src=agentA dst=agentB ts=1700000000\n'
    'DO deploy("app1", version=42)'
)

cmp = MessageMinifier.compare_with_json(msg)
print(cmp)
# SAG: 78 chars (20 tokens) vs JSON: 209 chars (53 tokens) - Saved: 33 tokens (62.3%)
```

## Threading conversations — `CorrelationEngine`

Each agent owns one engine, which mints monotonic message IDs and
threads `corr=` headers through replies automatically.

```python
from sag import CorrelationEngine, SAGMessageParser

agent_a = CorrelationEngine("agent-a")

# Build an outbound header
header = agent_a.create_response_header("agent-a", "agent-b")
print(header.message_id)  # "agent-a-1"

# When a reply comes in, build the response with corr= threaded through
incoming = SAGMessageParser.parse(
    "H v 1 id=msg42 src=agent-b dst=agent-a ts=1700000000\nQ status"
)
reply = agent_a.create_header_in_response_to("agent-a", "agent-b", incoming)
assert reply.correlation == "msg42"
```

`CorrelationEngine.trace_thread`, `find_responses`, and
`build_conversation_tree` reconstruct cross-agent causal chains from
collected message logs.

## Sharing knowledge across agents

`KnowledgeEngine` is a per-agent, versioned fact store with topic-based
subscriptions and delta propagation. Subscribers only receive facts
that match their pattern and that have advanced past the version they
last saw.

```python
from sag import KnowledgeEngine

agent_a = KnowledgeEngine("agent-a")
agent_b = KnowledgeEngine("agent-b")

# Agent B subscribes to all of agent A's `system.*` facts
agent_a.add_subscriber("agent-b", "system.*")

agent_a.assert_fact("system.cpu", 85)
agent_a.assert_fact("system.mem", 70)
agent_a.assert_fact("app.errors", 3)   # not in subscription

delta = agent_a.compute_delta("agent-b")  # only system.* facts
agent_b.apply_incoming(delta, "agent-a")
# agent_b now knows system.cpu=85, system.mem=70 — nothing else
```

Topic patterns: `system.*` (single level), `system.**` (multi-level),
`**` (everything).

## Multi-agent orchestration — Grove

Grove organizes agents into a tree and runs them bottom-up. Every
inter-agent hop produces a real SAG message on the wire (proper
header, KNOW statements). Plug in any backend via the `AgentRunner`
protocol — `EchoAgentRunner` for tests, `LLMAgentRunner` for
Claude/OpenAI, or a custom implementation.

```python
from sag import TreeEngine, Grove, EchoAgentRunner

tree = TreeEngine()
tree.add_root("pm", "Project Manager",
              prompt="Synthesize reports", topics=["project.plan"])
tree.add_child("pm", "eng", "Engineer",
               prompt="Design architecture", topics=["eng.design"])
tree.add_child("pm", "qa", "QA Lead",
               prompt="Plan testing", topics=["qa.strategy"])

grove = Grove(tree, EchoAgentRunner())
result = grove.execute("Build a REST API")

print(f"Agents run: {result.agents_run}")
print(f"SAG messages exchanged: {len(result.messages)}")
for topic, (value, version) in result.facts.items():
    print(f"  {topic} (v{version}): {value}")
```

`InteractiveGrove` adds step-through execution, fact editing, and
checkpoint/rollback. `ChatSession` opens a conversational loop with
the root after the grove completes. Both are exported from the
top-level `sag` package — see the main repository for full demos.

## What's in the package

| Module | Exports |
|--------|---------|
| `sag.parser` | `SAGMessageParser` |
| `sag.model` | `Message`, `Header`, all statement types |
| `sag.minifier` | `MessageMinifier`, `TokenComparison` |
| `sag.expression`, `sag.context` | `ExpressionEvaluator`, `Context`, `MapContext` |
| `sag.guardrail` | `GuardrailValidator` |
| `sag.schema` | `VerbSchema`, `SchemaRegistry`, `SchemaValidator`, `ArgType` |
| `sag.sanitizer` | `SAGSanitizer`, `AgentRegistry` |
| `sag.fold` | `FoldEngine` |
| `sag.correlation` | `CorrelationEngine` |
| `sag.knowledge` | `KnowledgeEngine`, `topic_matches` |
| `sag.tree`, `sag.grove` | `TreeEngine`, `Grove`, `InteractiveGrove`, `ChatSession`, runners |
| `sag.checkpoint` | `CheckpointManager` |
| `sag.profiles` | `SoftwareDevProfile` |
| `sag.prompt` | `PromptBuilder`, `SAGGenerator` (LLM prompt + retry loop) |

## Benchmark headlines

(Numbers from the benchmark harness in the main repository.)

- SAG wire format is **59% smaller than JSON** for the same payload.
- Fold protocol achieves **82–98% lossless compression** at typical
  conversation sizes.
- With a 10K-token budget, SAG + folding sustains **~8.8× more
  conversation turns** than linear NL before context exhaustion.
- Fold → unfold round-trips with **100% fidelity** across the test
  suite.

See [the main repository](https://github.com/phrocker/sag) for the
benchmarking harness, Java implementation, the live chatbot/grove
demos, and the canonical `SAG.g4` grammar.

## License

MIT — see `LICENSE`.
