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
├── README.md
├── docs/
│   ├── PRD.md                 # product requirements
│   ├── ARCHITECTURE.md        # system design
│   ├── DATA_MODEL.md          # schemas: vector / graph / process
│   ├── RETRIEVAL_AND_ML.md    # chunking, embeddings, retrieval, eval
│   ├── INGESTION.md           # connectors, pipeline, freshness loop
│   ├── API.md                 # REST surface + rate limiting
│   └── ROADMAP.md             # phased build plan + done-when gates
├── apps/
│   ├── api/                   # FastAPI serving plane
│   ├── workers/               # arq ingestion + extraction workers
│   └── admin/                 # Next.js admin UI (optional)
├── packages/
│   ├── connectors/            # source adapters (slack, gmail, ...)
│   ├── retrieval/             # chunking, embedding, hybrid + rerank
│   ├── knowledge/             # entity/relation/process extraction
│   └── eval/                  # golden sets + metric harness
├── infra/
│   ├── docker-compose.yml
│   ├── terraform/
│   └── k8s/
└── scripts/
    ├── train_embeddings.py    # contrastive fine-tune + hard-neg mining
    └── load_test.py           # k6/locust driver
```

---

## Quickstart

```bash
# 1. spin up infra (postgres, qdrant, redis, otel collector, grafana)
docker compose -f infra/docker-compose.yml up -d

# 2. install
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. migrate
alembic upgrade head

# 4. run a source ingest (sandbox connector)
python -m cortex.cli ingest --source sample --tenant demo

# 5. run the API
uvicorn cortex.api.main:app --reload

# 6. query
curl -s localhost:8000/v1/ask \
  -H "X-Tenant: demo" \
  -d '{"q": "how do we handle a refund over $500?"}'
```

---

## Status

Pre-alpha. Build order and acceptance gates: [`docs/ROADMAP.md`](docs/ROADMAP.md).