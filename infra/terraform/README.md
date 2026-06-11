# Terraform (M4)

Provisions the Cortex **data plane** — namespace, config/secrets, and managed
Postgres / Redis / Qdrant (via Helm) — that the workloads depend on
(docs/ARCHITECTURE.md §10). App `Deployment`/`HPA`/`CronJob` come from
`infra/k8s/` (or a future app chart).

| File | Contents |
|------|----------|
| `versions.tf` | provider pins (kubernetes, helm, random) + provider config |
| `variables.tf` | kubeconfig/context, namespace, passwords, storage sizes, shard count |
| `main.tf` | namespace, `ConfigMap`, `Secret`, and Helm releases for Postgres, Redis, Qdrant (sharded) |
| `outputs.tf` | the in-cluster DSN/URLs (DSN sensitive) |

The app connects as the least-privilege `cortex_app` role (RLS enforced,
migration 0006); the password is generated when not supplied.

```sh
terraform init
terraform plan  -var "anthropic_api_key=…" -var "kube_context=…"
terraform apply -var "anthropic_api_key=…" -var "kube_context=…"
```

Validated offline (`terraform fmt -check` + `terraform validate`). No cloud
apply is performed in CI/sandbox — point it at a real cluster to provision.
