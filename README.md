# Cortex — The Company Brain

Cortex turns a company's scattered, tribal knowledge — Slack threads, email,
support tickets, docs, code, issue trackers — into a **structured, current,
queryable, and executable** knowledge layer for AI agents.

It is **not** a chatbot over documents and **not** another search bar. The core
output is a *living map of how a company actually works* — how refunds are
handled, how incidents are triaged, how pricing exceptions get approved —
extracted as versioned, citeable **process objects** that an agent can read and
act on safely.

Built against the Y Combinator Summer 2026 Request for Startups ("Company Brain"
/ "The AI Operating System for Companies").

---

## Why this exists

The blocker to AI automation of a company is no longer model capability — it's
**domain knowledge** that lives in people's heads and fragmented systems. Cortex
is the connective layer that:

1. **Ingests** knowledge from every source, continuously.
2. **Structures** it into entities, relations, and executable processes.
3. **Keeps it current** — re-ingesting on change, expiring stale facts, flagging
   contradictions.
4. **Serves** it to humans (search/Q&A) and to agents (a generated, citeable
   *skills file*).

---

## What makes it hard (and resume-worthy)

| Axis | What Cortex demonstrates |
|------|--------------------------|
| Retrieval | Hybrid (BM25 + dense) search, cross-encoder reranking, source-aware chunking |
| Core ML | Fine-tuned embeddings (contrastive + hard-negative mining), process-extraction models, LLM-as-judge eval |
| Knowledge structuring | Entity/relation extraction, a knowledge graph, versioned process objects |
| Scale | Async queue-based multi-source ingestion, sharded vector index, horizontal serving |
| Infrastructure | Per-source + per-tenant rate limiting, IaC, observability, load-tested SLOs |
| System design | Three-plane architecture (ingestion / knowledge / serving), multi-tenancy, freshness loop |

---

## Architecture at a glance

```
            ┌──────────────────────────────────────────────────────┐
 SOURCES    │  Slack · Gmail · Notion · GitHub · Linear · Files     │
            └───────────────┬──────────────────────────────────────┘
                            │  (rate-limited connectors)
                   ┌────────▼─────────┐
  INGESTION PLANE  │  Queue + Workers │  chunk → contextualize → embed
                   │  (async, idemp.) │  → extract entities/processes
                   └────────┬─────────┘
                            │
          ┌─────────────────▼──────────────────┐
 KNOWLEDGE │  Vector store (Qdrant)             │
   PLANE   │  Knowledge graph (Postgres)        │
           │  Process registry (versioned)      │
           └─────────────────┬──────────────────┘
                            │
                   ┌────────▼─────────┐
 SERVING PLANE     │  Query API       │  hybrid retrieve → rerank → answer
                   │  Skills export   │  → generate executable skills file
                   │  (rate-limited)  │
                   └──────────────────┘
```

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Tech stack

- **Language / API:** Python 3.12, FastAPI, Pydantic v2
- **Vector store:** Qdrant (sharded, payload-filtered)
- **Relational + graph:** PostgreSQL 16 (graph modeled as edges; Neo4j optional later)
- **Queue / workers:** Redis + `arq`
- **Cache + rate limiting:** Redis (token bucket)
- **Embeddings:** BGE family, fine-tuned via `sentence-transformers`
- **Reranker:** `bge-reranker` cross-encoder
- **LLM:** provider-agnostic (Anthropic / OpenAI) for extraction + generation
- **Observability:** OpenTelemetry → Prometheus + Grafana, structured logs
- **Infra:** Docker / docker-compose → Kubernetes, Terraform
- **Admin UI (optional):** Next.js

---

## Repository layout

```
cortex/
├── pyproject.toml             # uv workspace root + ruff/mypy/pytest config
├── justfile                   # task runner (just up / migrate / dev / test / lint)
├── docs/
│   ├── PRD.md                 # product requirements
│   ├── ARCHITECTURE.md        # system design
│   ├── DATA_MODEL.md          # schemas: vector / graph / process
│   ├── RETRIEVAL_AND_ML.md    # chunking, embeddings, retrieval, eval
│   ├── INGESTION.md           # connectors, pipeline, freshness loop
│   ├── API.md                 # REST surface + rate limiting
│   ├── ROADMAP.md             # phased build plan + done-when gates
│   ├── ENGINEERING-WORKFLOW.md  # VCS, dev loop, releases, DoD
│   ├── TEST-STRATEGY.md       # test tiers + the eval regression gate
│   └── ADR/                   # architecture decision records
├── apps/
│   ├── api/                   # FastAPI serving plane (+ Dockerfile)
│   ├── workers/               # arq ingestion + extraction workers (+ Dockerfile)
│   └── admin/                 # Next.js admin UI (optional)
├── packages/
│   ├── connectors/            # source adapters (slack, gmail, ...)
│   ├── retrieval/             # chunking, embedding, hybrid + rerank
│   ├── knowledge/             # entity/relation/process extraction
│   └── eval/                  # golden sets + metric harness + CI gate
├── infra/
│   ├── docker-compose.yml     # postgres, qdrant, redis, otel, prometheus, grafana
│   ├── terraform/  k8s/       # cloud infra (M4)
│   └── otel/  prometheus/  grafana/
├── migrations/                # alembic
├── tests/                     # unit / integration / eval
├── scripts/
│   ├── train_embeddings.py    # contrastive fine-tune + hard-neg mining
│   └── load_test.py           # k6/locust driver
└── .github/workflows/         # ci · eval · release
```

---

## Quickstart

```bash
# 1. install everything (uv manages Python 3.12 + all workspace deps)
uv sync --all-extras

# 2. spin up infra (postgres, qdrant, redis, otel collector, prometheus, grafana)
just up            # or: docker compose -f infra/docker-compose.yml up -d

# 3. configure + migrate
cp .env.example .env
just migrate       # alembic upgrade head

# 4. run the API and check it's live
just dev           # uvicorn cortex.api.main:app --reload
curl -s localhost:8000/healthz   # -> {"status":"ok"}
```

`/v1/search` (hybrid, tenant-filtered) is live; `/ask` · `/processes` ·
`/skills` land in **M2+** (see [`docs/ROADMAP.md`](docs/ROADMAP.md)). Run `just`
to list all developer tasks.

---

## Contributing

Engineering workflow, branching, and the Definition of Done live in
[`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`docs/ENGINEERING-WORKFLOW.md`](docs/ENGINEERING-WORKFLOW.md); the test approach
and quality gate are in [`docs/TEST-STRATEGY.md`](docs/TEST-STRATEGY.md).

---

## Status

Pre-alpha. **M1 (retrieval quality) complete**: source-aware chunking with
contextual blurbs, hybrid retrieval (BM25 + dense + RRF fusion + cross-encoder
rerank behind the `ml` extra), and a golden-set eval harness wired as a
**blocking CI regression gate** — Recall@10 0.95 / nDCG@10 0.91 on the held-out
split. M0 (skeleton vertical slice) shipped dense-only `/v1/search` with
end-to-end tracing. Build order and acceptance gates:
[`docs/ROADMAP.md`](docs/ROADMAP.md).
