# Scale & load — Cortex

**Target (docs/ARCHITECTURE.md §8):** sustain **600 QPS on `/v1/search` at p95 < 200 ms
over a 2M-chunk index**, scaling horizontally.

This doc records what is *measured* vs *projected*, honestly. CI does not gate on
the throughput target (no scale environment); it gates on a latency-regression
smoke (`-m load`).

## How to reproduce

```bash
just up                              # Postgres, Qdrant, Redis
just migrate
uv run python -m cortex.workers.ingest --source sample --tenant demo   # or a large corpus
uv run uvicorn cortex.api.main:app --port 8000
# drive load (search), optionally gating on a budget:
uv run python scripts/load_test.py --url http://localhost:8000 --tenant demo \
    --endpoint search --concurrency 32 --duration 30 --max-p95-ms 200 --min-rps 600
```

`scripts/load_test.py` flags: `--endpoint search|ask`, `--concurrency`, `--duration`,
`--json` (machine-readable), `--max-p95-ms` / `--min-rps` (exit non-zero if unmet, so a
real deployment can gate in CI/CD).

## Measured — single dev process (this is a smoke, not the proof)

One `uvicorn` worker, local Docker Postgres/Qdrant/Redis, sample corpus, default
embedder (`hashing`) + reranker (`passthrough`). MacBook-class host.

| Endpoint | Concurrency | Throughput | p50 | p95 | p99 |
|----------|------------:|-----------:|----:|----:|----:|
| `/v1/search` | 32 | 216 req/s | 138 ms | 283 ms | 369 ms |
| `/v1/search` | 64 | 214 req/s | 292 ms | 657 ms | 923 ms |
| `/v1/ask` | 16 | 174 req/s | 84 ms | 132 ms | 207 ms |

**Reading it:** a single process saturates at **~215 req/s** — past concurrency 32,
throughput is flat and only latency grows (the process is the bottleneck, not the
datastores; zero errors throughout). This matches the M4 smoke (~244 req/s).

## Path to 600 QPS @ p95 < 200 ms / 2M chunks

The architecture is built to scale horizontally; the gap is a real deployment, not
code:

- **API replicas** — the serving plane is stateless. ~215 req/s/process means
  **3–4 replicas** clear 600 QPS aggregate. (Production also flips
  `CORTEX_EMBEDDER=bge` / `CORTEX_RERANKER=bge`, which raises per-request cost — size
  replicas against a `bge` run, not this `hashing` smoke.)
- **Vector store** — Qdrant collection is already shard-by-tenant
  (`ensure_collection(shard_number=...)`); a 2M-chunk index spreads across shards/nodes.
- **Postgres (BM25 leg)** — read replicas for the hybrid search FTS query.
- **Ingestion** — decoupled from serving via the arq lanes (docs/INGESTION.md);
  backfills drain on the backfill lane without touching serving latency.

## CI guardrail

`tests/integration/test_search_load.py` (marked `load`, run via `just loadtest-smoke`)
fires 200 concurrent in-process searches over the seeded corpus and asserts **zero
errors + p95 under a generous budget** — a latency-regression gate that runs anywhere
the stack is up, without a scale environment. It is *not* the 600-QPS proof; that
requires the multi-replica deployment above.
