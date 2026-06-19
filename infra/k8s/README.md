# Kubernetes manifests

Deploys Cortex as stateless, autoscaled workloads (docs/ARCHITECTURE.md §8, §10).

| File | Contents |
|------|----------|
| `namespace.yaml` | the `cortex` namespace |
| `config.yaml` | `ConfigMap` (production env: `bge` embedder/reranker, auth required, RLS enforced, async worker) + `Secret` template (admin & app DSNs, Anthropic key, connector tokens — populate from a real secret manager) |
| `migrate.yaml` | one-shot `alembic upgrade head` `Job` (runs as the owner DSN; DDL needs more than `cortex_app`) |
| `api.yaml` | API `Deployment` (3+) + `Service` + `HPA` on CPU (65%), `/readyz` `/healthz` probes |
| `worker.yaml` | ingestion-worker `Deployment` **per priority lane** (`realtime`, `backfill`) each with its own `HPA`, plus the freshness-sweep `CronJob` (every 15 min) |

## Production profile (`config.yaml`)

The ConfigMap flips the demo-safe defaults to production:
`CORTEX_EMBEDDER=bge`, `CORTEX_RERANKER=bge`, `CORTEX_AUTH_REQUIRED=true`,
`CORTEX_RLS_ENFORCE=true`, `CORTEX_WORKER_ASYNC=true`, `CORTEX_RATELIMIT=true`,
`CORTEX_QDRANT_SHARDS=6`. Mint per-tenant API keys with
`python -m cortex.api.auth mint --tenant <name>`.

## Apply order

Managed Postgres/Qdrant/Redis come from Terraform (`infra/terraform/`). Run the
migration to completion before rolling out the app:

```sh
kubectl apply -f namespace.yaml
kubectl apply -f config.yaml      # after substituting real secret values
kubectl apply -f migrate.yaml
kubectl wait --for=condition=complete job/cortex-migrate -n cortex --timeout=300s
kubectl apply -f api.yaml -f worker.yaml
```

Validate offline (no cluster):

```sh
kubectl apply --dry-run=client --validate=false -f infra/k8s/
```

## Priority lanes

`worker.yaml` runs one Deployment per lane (`CORTEX_WORKER_QUEUE`): `cortex:realtime`
(webhook deltas, more replicas) and `cortex:backfill` (history pulls). The
`reprocess` lane is run on demand to drain the DLQ
(`python -m cortex.workers.deadletter requeue`). The realtime HPA scales on
`cortex_ingest_queue_depth` (a custom metric via `prometheus-adapter`) so live
updates aren't starved by large backfills; CPU is the fallback signal.
