# Architecture Decision Records

Short, immutable records of non-trivial or hard-to-reverse decisions. One file per
decision, numbered sequentially: `NNNN-title.md`. Supersede rather than edit a
decided ADR (link the replacement).

## Template

```markdown
# ADR-NNNN: <title>

- **Status:** Proposed | Accepted | Superseded by ADR-XXXX
- **Date:** YYYY-MM-DD

## Context
What forces are at play? What problem/constraint prompts a decision?

## Decision
What we are doing, stated plainly.

## Consequences
Trade-offs accepted, what gets easier/harder, and what would make us revisit.

## Alternatives considered
Options weighed and why they lost.
```

## Index
- [ADR-0001](0001-postgres-edge-list-graph.md) — Postgres edge-list as the graph store for v1
- [ADR-0002](0002-bge-small-base-embedding.md) — `bge-small-en-v1.5` as the base embedding model
