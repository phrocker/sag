# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAG (Sentrius Agent Grammar) is a DSL for structured inter-agent communication. It provides parsing libraries in both Java and Python, a sanitization/firewall layer, fold/unfold protocol for context compression, benchmarks, and a live chatbot demo.

The canonical grammar lives at `src/main/antlr4/SAG.g4` and is the single source of truth for both Java and Python implementations. ANTLR generates `SAGLexer`, `SAGParser`, and `SAGBaseVisitor` at build time. These files are not in source control.

## Build Commands

### Java
```bash
mvn clean install          # Full build: compile + test + package
mvn compile                # Compile only (includes ANTLR code generation)
mvn test                   # Run all tests
mvn test -Dtest=SAGMessageParserTest                    # Run single test class
mvn test -Dtest=SAGMessageParserTest#testParseSimpleAction  # Run single test method
```
Java 17 is required.

### Python
```bash
cd python-sag
make generate              # Copy grammar + generate ANTLR Python files
make test                  # Run all tests
make lint                  # Run ruff linter
make build                 # Build pip-installable package
```
Python 3.10+ required. Uses venv at `python-sag/.venv/`.

### Benchmarks
```bash
source python-sag/.venv/bin/activate
python bench/benchmarks/token_efficiency.py    # SAG vs JSON vs NL token counts
python bench/benchmarks/fold_compression.py    # Compression ratios at various fold sizes
python bench/benchmarks/context_budget.py      # Linear vs SAG+folding context simulation
python bench/benchmarks/roundtrip_fidelity.py  # Fold -> unfold -> diff
```

### Demo
```bash
cd demo
python demo.py --no-api                        # Chatbot echo mode (no API key needed)
python demo.py --api-key <key>                 # Chatbot with Claude API
python demo.py --budget 5000 --threshold 0.5   # Custom memory settings
python tree_demo.py --no-api "Build a REST API"                  # Grove echo mode
python tree_demo.py --api-key <key> "Build a REST API"           # Grove with Claude
```

## Architecture

### Parsing Pipeline

Raw SAG text flows through: `SAGMessageParser.parse()` → ANTLR4 lexer/parser (auto-generated from `src/main/antlr4/SAG.g4`) → `SAGModelVisitor` (visitor over parse tree) → `Message` object containing a `Header` and `List<Statement>`.

### Feature Subsystems

- **Parser** (`SAGMessageParser`, `SAGModelVisitor`, `SAG.g4`): Core parsing from string to typed model objects.
- **Guardrail Validator** (`GuardrailValidator`, `ExpressionEvaluator`, `Context`/`MapContext`): Validates `BECAUSE` clauses on `ActionStatement`. Expression-style reasons are re-parsed through ANTLR and evaluated against a `Context`.
- **Message Minifier** (`MessageMinifier`): Serializes `Message` back to compact wire format. Provides token counting (chars/4 heuristic) and SAG-vs-JSON comparison.
- **Correlation Engine** (`CorrelationEngine`): Per-agent instance managing `corr=` header threading, monotonic message IDs, conversation thread tracing, and tree building.
- **Schema Enforcement** (`VerbSchema`, `SchemaRegistry`, `SchemaValidator`): Registry mapping verb names to schemas. Validates positional/named arguments with optional constraints (enum, pattern, range).
- **Sanitizer** (Python only: `SAGSanitizer`, `AgentRegistry`): Four-layer validation pipeline: Grammar Parse → Routing Guard → Schema Validate → Guardrail Check.
- **Fold Protocol** (`FoldStatement`, `RecallStatement`, `FoldEngine`): Grammar-level fold/unfold for context compression. `FOLD <id> "summary" [STATE {...}]` and `RECALL <id>`. 100% roundtrip fidelity.
- **Prompt Builder** (`PromptBuilder`, `SAGGenerator`): Generates LLM system prompts from embedded EBNF grammar + schema docs. `SAGGenerator` wraps any `LLMClient` with a parse-validate-retry loop.
- **Schema Profiles** (`SoftwareDevProfile`): Pre-built `SchemaRegistry` with 12 CI/CD verbs (build, test, deploy, rollback, review, merge, lint, scan, release, provision, monitor, migrate).
- **Knowledge Engine** (`KnowledgeEngine`, `topic_matches`): Per-agent versioned fact store with topic-based subscriptions, wildcard matching (`*`, `**`), delta propagation via version vectors, and auto-fold when exceeding knowledge budget.
- **Tree Engine** (`AgentNode`, `TreeEngine`): Agent tree topology management. Each node has its own `KnowledgeEngine` + `CorrelationEngine`. Supports bottom-up traversal, parent-child knowledge propagation, and ASCII rendering.
- **Grove** (`Grove`, `AgentRunner`, `LLMAgentRunner`, `EchoAgentRunner`, `GroveResult`): Multi-agent tree orchestrator. Executes agents bottom-up, propagates knowledge via SAG messages (with proper headers and KNOW statements), and aggregates results. `AgentRunner` protocol allows swapping LLM/echo/custom backends. Callback hooks for UI observation.

### Data Model

`Statement` has eleven implementations: `ActionStatement`, `QueryStatement`, `AssertStatement`, `ControlStatement`, `EventStatement`, `ErrorStatement`, `FoldStatement`, `RecallStatement`, `SubscribeStatement`, `UnsubscribeStatement`, `KnowledgeStatement`. `Message` owns a `Header` and `List<Statement>`. Java uses immutable POJOs; Python uses frozen dataclasses.

### Package Layout

#### Java
- `com.sentrius.sag` — all main classes
- `com.sentrius.sag.model` — immutable data model POJOs
- `com.sentrius.sag.profiles` — schema profiles

#### Python (`python-sag/src/sag/`)
- `parser.py`, `visitor.py` — core parsing
- `model.py` — frozen dataclasses
- `expression.py`, `context.py` — expression evaluation
- `guardrail.py`, `schema.py` — validation subsystems
- `minifier.py`, `correlation.py` — serialization + threading
- `sanitizer.py` — four-layer firewall
- `fold.py` — fold/unfold engine
- `knowledge.py` — knowledge propagation engine
- `tree.py` — agent tree topology (`AgentNode`, `TreeEngine`)
- `grove.py` — multi-agent orchestrator (`Grove`, runners, `GroveResult`)
- `prompt.py` — LLM prompt builder + validate-retry generator
- `profiles/software_dev.py` — pre-built verb schemas

### Directory Structure
- `/` — Java library (Maven)
- `python-sag/` — Python library (pip-installable)
- `bench/` — Benchmarking harness (reads from `bench/fixtures/conversations.py`)
- `demo/` — Live chatbot demo + grove multi-agent demo with TUI
- `.github/workflows/` — CI for Java + Python
