# ADR-0001: Postgres edge-list as the graph store for v1

- **Status:** Accepted
- **Date:** 2026-06-09

## Context
Cortex needs a knowledge graph (entities + relations) with provenance and
temporal validity. A dedicated graph database (Neo4j) is the obvious candidate,
but it adds a datastore to operate, back up, and secure. The PRD lists "Postgres
edges vs. Neo4j" as an open question. Observed access patterns are shallow: most
queries are 1–2 hops ("who approves refunds", "what escalates to whom"), not deep
multi-hop traversal.

## Decision
Model the graph as an **edge list in PostgreSQL** for v1: `entities` +
`relations(subject_id, predicate, object_id, confidence, source_chunk_id,
valid_from, valid_to)`, all tenant-scoped with row-level security. Reuse the same
Postgres instance that holds the process registry and metadata.

## Consequences
- **Easier:** one fewer datastore; transactional consistency with processes and
  metadata; RLS gives tenant isolation for free; temporal columns support
  contradiction detection.
- **Harder:** deep/variable-length traversals are awkward and slower than in a
  native graph engine; recursive CTEs only go so far.
- **Revisit when:** traversal depth or volume grows enough that recursive queries
  dominate latency — then migrate the graph plane to Neo4j (a stretch item),
  keeping processes/metadata in Postgres.

## Alternatives considered
- **Neo4j now:** best traversal ergonomics, but premature operational cost for
  1–2-hop queries and a solo maintainer.
- **A graph extension (e.g. AGE):** keeps one server but adds an immature
  dependency and Cypher surface we don't yet need.
