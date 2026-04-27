# semantic-action-grammar

Semantic Action Grammar (SAG) — a DSL for structured inter-agent communication.

SAG provides parsing, schema validation, correlation, sanitization, and a
grammar-level fold/unfold protocol for context compression. This package is
the Python implementation; the canonical grammar lives in the
[main repository](https://github.com/phrocker/sag).

## Install

```bash
pip install semantic-action-grammar
```

The Python import name is `sag`:

```python
from sag import SAGMessageParser
```

## Quick start

```python
from sag import SAGMessageParser, MessageMinifier

parser = SAGMessageParser()
message = parser.parse('[id=1 src=A dst=B] DO deploy("app1", version=42) BECAUSE balance>1000;')

print(message.header.id)          # "1"
print(message.statements[0].verb) # "deploy"

# Re-serialize to the compact wire format
print(MessageMinifier().minify(message))
```

## What's in the box

- **Parser** — `SAGMessageParser`, ANTLR4-backed
- **Schema validation** — `SchemaRegistry`, `VerbSchema`, `SchemaValidator`
- **Guardrails** — `BECAUSE`-clause expressions evaluated against a `Context`
- **Sanitizer** — four-layer firewall (parse → routing → schema → guardrail)
- **Fold protocol** — `FoldEngine` for lossless conversation compression
- **Knowledge engine** — versioned topic-based fact propagation
- **Tree / Grove** — multi-agent topology and bottom-up orchestration
- **Accounting** — token and cost tracking for grove executions

See the main repository for benchmarks, the chatbot demo, and the full
specification.

## License

MIT — see `LICENSE`.
