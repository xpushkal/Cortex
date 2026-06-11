# Kubernetes manifests (M4)

Deploys Cortex as stateless, autoscaled workloads (docs/ARCHITECTURE.md §8, §10).

| File | Contents |
|------|----------|
| `namespace.yaml` | the `cortex` namespace |
| `config.yaml` | `ConfigMap` (non-secret env) + `Secret` template (DSN/API keys — populate from a real secret manager; the app runs as the least-privilege `cortex_app` role) |
| `api.yaml` | API `Deployment` (3+) + `Service` + `HPA` on CPU (65%), `/readyz` `/healthz` probes |
| `worker.yaml` | ingestion-worker `Deployment` + `HPA` on **queue depth** (custom metric) with CPU fallback, and the freshness-sweep `CronJob` (every 15 min) |

Apply in order (managed Postgres/Qdrant/Redis come from Terraform — see
`infra/terraform/`):

```sh
kubectl apply -f namespace.yaml
kubectl apply -f config.yaml      # after substituting real secret values
kubectl apply -f api.yaml -f worker.yaml
```

Validate without a cluster:

```sh
kubectl apply --dry-run=client -f infra/k8s/
```

**Queue-depth autoscaling** needs the `prometheus-adapter` exposing
`cortex_ingest_queue_depth` as a custom metric; the worker HPA then scales on
backlog so live updates aren't starved by large backfills.
