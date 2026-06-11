# M6 Plan — Skills Export + Agent Demo

**Status:** Active
**Branch:** `M6`
**Roadmap gate (done-when):** an external agent, given **only** the skills file,
completes the scripted task (correctly routes a **$750 refund**) with **every
action traceable to a cited process step**.

The YC-thesis close: project Cortex's versioned, cited, freshness-tracked process
objects into an agent-consumable **skills file** (`GET /v1/skills`), then prove a
reference agent grounded *entirely* in that file completes a real task.

---

## The honesty split

Unlike M2–M5, M6's done-when is **fully verifiable hermetically** — it's a
correctness claim, not a throughput/training number. So M6 gates on it directly:

- **`/skills` export + the grounded agent demo → BLOCKING, CI-verified.** The
  export is real (projects active, non-expired processes with citations +
  freshness manifest); the reference agent runs deterministically and the demo
  test asserts the $750 refund is routed to finance with every action carrying a
  citation. No external dependency required.
- The only flag-gated piece is the **LLM agent variant** (`claude` consuming the
  skills file) — the "real" demo flavor — behind `CORTEX_AGENT=llm`, mocked in
  tests; the deterministic reference agent is the CI path and the thing the gate
  proves.

---

## Scope (from ROADMAP.md §M6 / API.md `/skills` / DATA_MODEL.md §6)

1. `GET /v1/skills` — export active, non-stale processes as the skills file
   (freshness manifest + citations).
2. A reference agent that consumes the skills file and completes the scripted
   task, grounded entirely in cited process steps.
3. The done-when demo as a blocking test.

Out of scope: action execution / write-back to source systems (stretch,
approval-gated), per-document ACLs (stretch).

---

## Current state (what M6 builds on)

| Piece | State | File |
|---|---|---|
| Process registry (cited, versioned bodies) | Done (M2) | `packages/knowledge/.../repository.py` |
| Freshness state (fresh/stale/expired) | Done (M3) | `packages/knowledge/.../freshness.py` |
| `list_processes` / `get_process_body` (carry freshness) | Done (M3) | `packages/knowledge/.../repository.py` |
| `/v1/processes`, `/v1/ask` serving | Done (M2/M3) | `apps/api/.../` |
| `/v1/skills` | Missing | — |
| Reference agent | Missing | — |

---

## Design decisions

### D1 — Skills-file schema owned by the consumer (`cortex-agent`)
A new `cortex-agent` package defines the **wire contract** an external consumer
codes against: `SkillsFile` (tenant, scope, generated_at, freshness_manifest,
skills[]) with `Skill` (name, trigger, steps, freshness, version) and `SkillStep`
(action, actor, decision, citations). It depends on **pydantic only** — it knows
nothing about Cortex internals, embodying "given only the skills file". The API
builds a dict that validates against this schema (a test asserts it), keeping the
producer/consumer decoupled.

### D2 — `/skills` exports active, non-expired processes (API.md)
`build_skills_file(session, tenant_id, scope, include_stale)` reuses
`list_processes` + `get_process_body` + freshness: include `active` processes
that are not `expired`; `stale` excluded unless `include_stale=true` (labeled,
never silently served). The `freshness_manifest` counts fresh/stale/expired over
the tenant's processes. Every step keeps its citations — the consuming agent can
verify provenance. `GET /v1/skills?scope=&include_stale=&format=json`.

### D3 — Reference agent grounded only in cited steps
`ReferenceAgent.run(skills_file, task)` takes the skills file + a task (e.g.
`{"type": "refund", "amount_usd": 750}`), finds the matching skill (refund),
evaluates its steps against the task — parsing the `$` threshold and direction
("over/above" vs "up to/under") from each step's action — and returns the
applicable step's action + actor + **its citations**. An action is emitted only
from a step that carries a citation (the M2 invariant guarantees one), so every
action is traceable. Deterministic; the `claude` variant (`CORTEX_AGENT=llm`,
injectable client) is the flag-gated flavor.

### D4 — The done-when demo as a blocking test
A test seeds a tenant, ingests the sample corpus (which yields the refund
process with cited threshold steps), calls `GET /v1/skills`, validates the
output against the `cortex-agent` schema, hands it to the reference agent with
`amount_usd=750`, and asserts: the decision routes to **finance** (not the
support-agent auto-issue path), and **every action in the result carries a
citation** resolving to a process step. A `$300` case asserts the auto-issue
path — proving the agent reasons over the cited steps, not a hardcode.

---

## Workstreams & feature commits

Order: agent package (schema + reference agent) → `/skills` export → done-when
demo → docs. One commit per feature.

### 1. `feat(agent): skills-file schema + reference agent`
- `cortex-agent` package: `schema.py` (SkillsFile/Skill/SkillStep/...) +
  `reference.py` (`ReferenceAgent` deterministic + `LlmAgent` behind the flag).
  Unit tests: refund routing at $750 / $300, citation-traceability, no-match.

### 2. `feat(api): GET /v1/skills export`
- `knowledge.skills.build_skills_file` (active, non-expired, freshness manifest,
  citations) + the endpoint (`scope`, `include_stale`). Integration tests:
  export shape, freshness filtering, tenant isolation, schema validity.

### 3. `feat(eval): agent demo — $750 refund grounded in cited steps (done-when)`
- Eval-marked end-to-end: seed → `/skills` → schema-validate → agent routes
  $750 to finance with cited actions; $300 auto-issues. The blocking M6 gate.

### 4. `docs: mark M6 complete + milestones done`
- README, CHANGELOG, ROADMAP; the resume bullets filled; project M0–M6 complete.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Heuristic processes lack structured decision branches | D3: the agent parses the `$` threshold + direction from step *action text* (which the sample refund steps contain), not a `decision` dict — grounded in the real cited steps. |
| "External agent" coupled to Cortex internals | D1: the agent package depends on pydantic only and consumes the skills file; a test asserts the API output validates against its schema. |
| Stale/expired knowledge leaking into skills | D2: export is active + non-expired by default; stale only with `include_stale`, always labeled. |
| LLM agent flaky/cost in CI | Deterministic reference agent is the gate; LLM variant behind `CORTEX_AGENT=llm`, mocked. |

## Verification (milestone exit)

1. `GET /v1/skills` returns the skills file — active, non-expired processes with
   citations + a freshness manifest; stale excluded unless requested; tenant-
   isolated; validates against the `cortex-agent` schema.
2. The reference agent, **given only the skills file**, routes a $750 refund to
   finance with every action traceable to a cited process step; $300 auto-issues.
3. The done-when demo passes as a blocking eval test.
4. Full suite green with `EVAL_GATE=blocking`. Project M0–M6 complete.
