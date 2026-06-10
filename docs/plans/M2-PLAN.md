# M2 Plan — Knowledge Structuring

**Status:** Complete (2026-06-11) — citation-validity 1.00 (blocking gate green); process recall 0.89 / precision 0.78, actor-resolution 0.88 on the golden set (deterministic path; advisory). Graph + processes served via /processes and /ask.
**Branch:** `M2`
**Roadmap gate (done-when):** process-extraction precision ≥ 0.80 / recall ≥ 0.70
vs the process golden set, with **100% of shipped steps carrying valid
citations**.

M1 made retrieval good and measured. M2 turns retrieved chunks into *structured
knowledge*: an entity/relation graph with provenance, and the product's core
unit — versioned, every-step-cited **process objects** — served via `/processes`
and grounded `/ask`.

---

## Scope (from ROADMAP.md §M2)

1. Entity + relation extraction → Postgres graph, with provenance.
2. Entity resolution (alias merging).
3. Process extraction → versioned process objects, every step cited.
4. Pydantic validation + faithfulness gate on process steps.
5. `/processes` + `/ask` (grounded in processes when available).

Out of scope: freshness/staleness loop and contradiction→review (M3, though the
versioning seam is built here), skills export + agent demo (M6), embedding
fine-tune (M5).

---

## Current state (what M2 builds on)

| Piece | State | File |
|---|---|---|
| Process/Step/Citation Pydantic models | **Done** (citation invariant enforced) | `packages/knowledge/src/cortex/knowledge/models.py` |
| `extract_processes` | Stub (`NotImplementedError`) | `packages/knowledge/.../extraction.py` |
| Graph + process **DB tables** | Missing (only sources/artifacts/chunks exist) | — |
| Hybrid retrieval (used by `/ask`) | Done (M1) | `packages/retrieval/.../hybrid.py` |
| Eval gate `process_citation_validity` threshold | Defined (0.95), never fed a value | `packages/eval/.../gate.py` |
| `/processes`, `/ask` | Missing | — |
| LLM client pattern (flag + injectable) | Established by blurbs (M1) | `packages/retrieval/.../blurb.py` |

---

## The hermetic-CI tension (the central design decision)

Extraction and generation are genuinely LLM tasks, but CI must stay
deterministic, offline, and key-free — the stance M0/M1 took with the hashing
embedder and template blurbs. M2 applies the same pattern to every LLM-shaped
stage:

- **Deterministic default** — a real (if naive) heuristic method, never a
  lookup table: entity/relation extraction by typed noun-phrase + relation-cue
  patterns; process synthesis by clustering chunks on entity/topic overlap and
  detecting sequential/imperative cues; faithfulness by lexical entailment
  (cited chunk must contain the step's salient tokens). These run in CI.
- **LLM path behind a flag** — `CORTEX_EXTRACTOR=llm` / `CORTEX_ASK=llm`:
  `claude-opus-4-8` with structured outputs (`output_config.format`) for
  extraction quality; `claude-haiku-4-5` is too weak for multi-chunk process
  synthesis. Lazy-imported `anthropic` (the `llm` extra), injectable client for
  tests, never runs in CI.

### Gate honesty (D-gate)
The done-when has two halves with different enforceability:

- **`process_citation_validity` → BLOCKING.** Every shipped step cites a chunk
  that (a) exists in the tenant and (b) lexically supports the step. This is a
  hard structural invariant — correct code yields 1.0 — so it blocks CI. This
  is the "100% of shipped steps carrying valid citations" half, and it is the
  real anti-hallucination guarantee.
- **process precision / recall → ADVISORY.** Reported every run, but not
  blocking: a blocking precision/recall gate would require either the LLM in CI
  (non-hermetic) or a rule-based extractor tuned to the golden set (the exact
  dishonesty `docs/RETRIEVAL_AND_ML.md` §5 warns against). The deterministic
  extractor's numbers are reported as-is; the LLM extractor is the path that
  targets 0.80/0.70 and is demonstrated out-of-band. This mirrors M1, where the
  gate flipped to blocking only once the metric was genuinely earned.

---

## Design decisions

### D1 — ORM in storage, domain logic in knowledge
Graph + process **tables** (ORM, migration) live in `cortex.storage` next to
Source/Artifact/Chunk (persistence plane). Extraction/resolution/synthesis
logic and the Pydantic domain models stay in `cortex.knowledge`. Repositories
(persist/query a `Process` aggregate) live in storage.

### D2 — Graph schema (DATA_MODEL.md §3)
`entities` (type, name, aliases[], attributes), `entity_mentions`
(entity→chunk provenance + confidence), `relations` (subject→predicate→object,
`source_chunk_id` provenance, `valid_from/valid_to` for M3 temporal queries).
Confidence-thresholded: low-confidence rows are dropped (M2) rather than queued
(the review queue is M3).

### D3 — Process schema (DATA_MODEL.md §5)
`processes` (name, trigger, current_version, status, confidence),
`process_versions` (version, `body` jsonb = canonical process JSON,
created_by), `process_steps` (ordinal, action, actor_entity_id, decision),
`citations` (owner_type/owner_id → chunk_id, quote). The `body` jsonb is the
source of truth served to clients; the step/citation rows exist for querying
and the citation-validity check.

### D4 — Entity resolution by normalized-key + alias merge
Canonicalize on a normalized name key (lowercased, stop-role-words stripped);
exact/substring alias matches merge into the existing entity (surface form
appended to `aliases`). Embedding-similarity merge is available behind the `ml`
extra but off by default. Deterministic and idempotent so re-ingest is stable.

### D5 — Faithfulness as lexical entailment (default), NLI behind flag
A step is faithful if its cited chunk(s) contain the step's salient content
tokens above a coverage threshold (default 0.5 of non-stopword step tokens).
Steps failing the gate are dropped before persistence (never shipped). The
NLI/LLM-judge faithfulness check is `CORTEX_FAITHFULNESS=llm`. Citation
validity (the blocking metric) = fraction of shipped steps whose citations
resolve to a real tenant chunk AND pass faithfulness.

### D6 — Versioning + contradiction seam (M3-ready)
Re-extracting a process with the same name: if the synthesized body differs
from the active version, write a **new version** (don't mutate) and set status
`draft` with a `supersedes` note; identical body is a no-op (idempotent). Full
contradiction detection + review routing is M3; M2 builds the version chain and
the no-silent-overwrite guarantee.

### D7 — `/ask` grounded in processes, extractive default
`/ask` hybrid-retrieves, then checks for a relevant active process (name/trigger
match against the query over the tenant's processes). If found, the answer is
grounded in that process (steps + citations, listed in `used_processes`);
otherwise it falls back to raw chunk retrieval. Default generation is
**extractive** (stitch the cited step actions / top chunk texts with their
citations) — honest and offline; `CORTEX_ASK=llm` produces fluent prose grounded
in the same context. Every answer carries `citations` and `freshness`
(`fresh` in M2; the real freshness loop is M3).

---

## Workstreams & feature commits

Order: tables → graph extraction+resolution → process extraction+faithfulness →
repositories → wire into ingest → `/processes` → `/ask` → eval → docs. One
commit per feature (repo convention, no co-author trailers).

### 1. `feat(storage): knowledge graph + process tables`
- Migration `0004`: entities, entity_mentions, relations, processes,
  process_versions, process_steps, citations (all tenant-scoped, FKs, indexes).
- ORM models in `storage/models.py`. Integration test: migration round-trips,
  cascade deletes, tenant column present on every table.

### 2. `feat(knowledge): entity + relation extraction with provenance`
- `Extractor` protocol; `HeuristicExtractor` (typed noun-phrase entities +
  relation-cue patterns: "route to", "approval from", "escalate to", "owns");
  `LlmExtractor` (`claude-opus-4-8`, structured outputs, `llm` extra, injectable
  client). Every entity mention + relation carries its `source_chunk_id` and a
  confidence; sub-threshold dropped.
- Unit tests: heuristic extraction over sample-shaped text; LLM path with a fake
  client; provenance + confidence asserted.

### 3. `feat(knowledge): entity resolution (alias merging)`
- `resolve_entities(candidates, existing)` → merged set with `aliases`
  populated; normalized-key + alias-match (D4); deterministic + idempotent.
- Unit tests: aliases merge ("finance team" / "Finance"), distinct entities stay
  distinct, idempotent on re-run.

### 4. `feat(knowledge): process extraction + faithfulness gate`
- Replace the `extract_processes` stub: cluster chunks (entity/topic overlap) →
  synthesize `Process` (canonical schema, citation per step from the source
  chunk) → Pydantic validation (exists) → faithfulness gate (D5, drop unfaithful
  steps) → emit only fully-cited, faithful processes. `HeuristicProcessSynth`
  default; `LlmProcessSynth` behind the flag.
- Unit tests: synthesis over a known cluster yields cited steps; an unfaithful
  step is dropped; the citation invariant holds end-to-end.

### 5. `feat(storage): process + graph repositories`
- `save_process` (process + version + steps + citations, version-aware per D6),
  `list_processes` / `get_process` / `get_process_versions`, `save_graph`
  (entities/mentions/relations upsert). All tenant-filtered.
- Integration tests: save→list→get round-trip; re-save identical body is a
  no-op; changed body bumps version; tenant isolation.

### 6. `feat(workers): wire extraction into the ingestion pipeline`
- After chunk/embed/upsert per artifact: entity+relation extraction → graph.
  After a source backfill completes: process extraction over the tenant's chunks
  → process registry. Idempotent (re-ingest unchanged corpus = no new versions).
- Integration test: seed sample corpus → graph + processes populated; re-seed →
  no duplicate entities / no version churn.

### 7. `feat(api): GET /v1/processes (+ detail + versions)`
- List (status/q filters), detail (canonical body), version history — all
  tenant-scoped via `X-Tenant`. Integration tests over the seeded tenant +
  isolation.

### 8. `feat(api): POST /v1/ask (process-grounded, extractive default)`
- Hybrid retrieve → process match → grounded extractive answer with
  `citations`, `freshness`, `used_processes`; LLM prose behind `CORTEX_ASK=llm`.
  Integration tests: refund-over-500 query grounds in the process; a query with
  no process falls back to chunks; tenant isolation; every answer cites.

### 9. `feat(eval): process golden set + extraction metrics + citation gate`
- Hand-authored process golden set for the sample corpus
  (`packages/eval/.../data/golden_processes.jsonl`).
- Metrics: step precision/recall vs golden, actor-resolution accuracy,
  **citation-validity rate**. Harness runs extraction → metrics → report.
- Gate: feed `process_citation_validity` (BLOCKING per D-gate); precision/recall
  ADVISORY. Canary: a process with a dangling/​unfaithful citation fails the
  blocking gate.

### 10. `docs: mark M2 complete`
- README, CHANGELOG, ROADMAP resume bullet, plan status with measured numbers.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Heuristic extraction too weak for 0.80/0.70 on the sample corpus | Precision/recall is ADVISORY (D-gate); the LLM path is what targets the bar. Citation-validity (blocking) is independent of extractor quality. |
| Golden labels drift when chunking changes | Reuse M1's stable `(external_id, ordinal)` chunk-label resolution for citations; author the process golden set against the current corpus. |
| LLM extraction cost/flakiness in CI | Deterministic default; LLM never runs in CI (flag-gated, mocked in tests). |
| Process synthesis emits an uncited step | Pydantic rejects it at construction (existing invariant); faithfulness gate drops unfaithful-but-cited steps before persistence. |
| `/ask` extractive answers are not fluent prose | Honest + offline by default; fluent prose is the documented `CORTEX_ASK=llm` path. |

## Verification (milestone exit)

1. `just seed` populates the graph (entities/relations with provenance) and the
   process registry (versioned, every step cited).
2. Eval harness: `process_citation_validity` = 1.0 (blocking gate green);
   precision/recall reported on the golden set; canary proves a bad-citation
   process fails the blocking gate.
3. `GET /v1/processes` lists active processes; `GET /v1/processes/{id}` returns
   the canonical cited body; `POST /v1/ask` grounds a refund query in the
   process with citations + `used_processes`, and falls back to chunks otherwise.
4. Cross-tenant isolation holds on `/processes`, `/ask`, and the graph queries.
5. Re-seeding the unchanged corpus produces no duplicate entities and no process
   version churn (idempotent).
