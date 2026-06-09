# PRD — Cortex (Company Brain)

**Status:** Draft v1
**Owner:** xRyuk
**Last updated:** 2026-06-09

---

## 1. Problem

Companies run on knowledge that is undocumented and fragmented. Critical know-how
("how do we issue a refund over $500", "who approves a pricing exception", "what's
our incident escalation path") lives in people's heads and is scattered across
Slack, email, tickets, wikis, and code. Humans cope by vaguely remembering where
things are. **AI agents cannot.** Until that knowledge is extracted, structured,
and kept current, agentic automation of real work is blocked.

## 2. Solution

Cortex is a system that:
- connects to a company's tools,
- continuously extracts and **structures** their knowledge into entities,
  relations, and **executable process objects**,
- keeps that knowledge current and self-consistent,
- and exposes it to (a) humans via search/Q&A and (b) agents via a generated,
  citeable **skills file**.

The unit of value is the **process object** — a validated, versioned, source-cited
description of how a recurring task is done. This is what distinguishes Cortex from
RAG-over-docs.

## 3. Goals / Non-goals

**Goals**
- G1. Ingest ≥5 source types with continuous, incremental sync.
- G2. Produce structured process objects with source citations, not just chunks.
- G3. High-quality retrieval (measured, with a regression gate).
- G4. Keep knowledge current: detect changes, expire stale facts, flag contradictions.
- G5. Multi-tenant isolation + per-tenant/per-source rate limiting.
- G6. Export an agent-consumable skills file.

**Non-goals (v1)**
- N1. Letting agents *execute* actions against source systems (read-only; skills
  file is consumed by an external agent runtime).
- N2. Fine-grained per-document ACL mirroring of every source's permission model
  (v1 does tenant-level isolation + source-level scoping).
- N3. A polished end-user UI (admin UI is minimal; API-first).
- N4. On-prem / air-gapped deployment.

## 4. Target users

| Persona | Need |
|---------|------|
| **Agent builder / platform eng** | A reliable knowledge + skills API to ground agents |
| **Ops / support lead** | Codify tribal processes; reduce "ask the one person who knows" |
| **New employee** | Ask how things work and get cited, current answers |

## 5. User stories

- As an agent builder, I can pull a **skills file** for tenant X so my agent knows
  how refunds are handled, with citations back to the source of truth.
- As an ops lead, I connect Slack + Notion + Zendesk and within an hour Cortex has
  extracted our top 20 recurring processes for review.
- As an employee, I ask "what's our on-call escalation for a Sev1?" and get an
  answer grounded in the current runbook, with a freshness timestamp.
- As an admin, I see when a process object's sources have changed and the object
  is flagged **stale** for re-validation.
- As a security reviewer, every answer and every process step links to the exact
  source artifact it came from.

## 6. Functional requirements

### 6.1 Ingestion
- FR1. Connectors for Slack, Gmail, Notion, GitHub, Linear, and generic file upload.
- FR2. Incremental sync via source cursors/webhooks; full backfill on first connect.
- FR3. Idempotent ingestion (re-running yields no duplicates).
- FR4. Per-source rate limiting with backoff; respect source API quotas.
- FR5. Dead-letter handling for poison documents.

### 6.2 Knowledge structuring
- FR6. Source-type-aware chunking (a Slack thread ≠ a PR ≠ a wiki page).
- FR7. Contextual embedding (prepend an LLM-generated context blurb per chunk).
- FR8. Entity + relation extraction into the knowledge graph.
- FR9. Process extraction into validated, versioned process objects with citations.
- FR10. Contradiction detection across sources for the same fact/process.

### 6.3 Freshness
- FR11. Re-ingest on source change; recompute affected chunks/objects only.
- FR12. TTL / staleness policy per knowledge type; mark stale, never silently serve.
- FR13. Version history for every process object (diff between versions).

### 6.4 Serving
- FR14. `/ask` — grounded Q&A (hybrid retrieve → rerank → generate, with citations).
- FR15. `/search` — ranked retrieval without generation.
- FR16. `/processes` — list/read/version process objects.
- FR17. `/skills` — export the agent-consumable skills file for a tenant/scope.
- FR18. Per-tenant rate limiting + quotas on all serving endpoints.

### 6.5 Multi-tenancy
- FR19. Hard tenant isolation in vector store (namespace/shard) and graph (tenant key).
- FR20. No cross-tenant retrieval, ever (enforced + tested).

## 7. Non-functional requirements

- NFR1. **Retrieval quality:** Recall@10 ≥ 0.85 and nDCG@10 ≥ 0.70 on the golden set.
- NFR2. **Serving latency:** p95 `/search` < 200 ms; p95 `/ask` < 2.5 s (incl. LLM).
- NFR3. **Ingestion throughput:** ≥ 500 docs/min/worker sustained.
- NFR4. **Freshness:** source change → retrievable in < 60 s for webhook sources.
- NFR5. **Availability:** serving plane stateless + horizontally scalable.
- NFR6. **Isolation:** zero cross-tenant leakage (assertion in CI).
- NFR7. **Observability:** every request traced; ingestion + eval metrics dashboards.

## 8. Success metrics

| Metric | Target |
|--------|--------|
| Retrieval Recall@10 / nDCG@10 | ≥ 0.85 / ≥ 0.70 |
| Fine-tuned vs base embedding lift | ≥ +5% Recall@10 on golden set |
| Process-extraction precision / recall | ≥ 0.80 / ≥ 0.70 vs golden processes |
| Answer faithfulness (LLM-judge, calibrated) | ≥ 4.0 / 5.0 |
| p95 search latency @ 600 QPS | < 200 ms |
| Ingestion throughput | ≥ 500 docs/min/worker |

## 9. Milestones (summary)

See [`ROADMAP.md`](ROADMAP.md) for done-when gates.

- **M0** Skeleton: infra, one connector, basic chunk→embed→search.
- **M1** Retrieval quality: hybrid + rerank + eval harness + CI gate.
- **M2** Knowledge: entity/relation + process extraction + graph.
- **M3** Freshness: incremental sync, staleness, contradiction detection.
- **M4** Scale: multi-tenancy, rate limiting, sharding, load test to SLO.
- **M5** ML depth: fine-tuned embeddings beating baseline on golden set.
- **M6** Skills export + agent consumption demo.

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Process extraction hallucinates steps | Require source citations per step; LLM-judge faithfulness gate; human review queue |
| Source API rate limits throttle ingestion | Per-source token buckets, backoff, prioritized queues |
| Stale knowledge served as current | Freshness TTL + staleness flag; never serve unmarked stale data |
| Cross-tenant leakage | Namespace isolation + mandatory tenant filter + CI leakage test |
| Eval set overfit | Hold-out split; periodic golden-set refresh; track train/test gap |
| Cost of LLM extraction at scale | Compute context blurbs/extraction only on changed chunks; batch; cache |

## 11. Open questions

- Graph store: stay in Postgres edges or move to Neo4j at what scale?
- Skills file format: custom schema vs. an emerging agent-skills standard?
- Contradiction resolution: auto-pick newest source vs. always human-in-loop?
