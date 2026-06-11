# Cortex data plane: namespace, config/secrets, and managed Postgres / Redis /
# Qdrant via Helm (docs/ARCHITECTURE.md §10). The app Deployments/HPA come from
# `kubectl apply -f infra/k8s/` (or a future app chart); this module provisions
# everything they depend on.

resource "random_password" "postgres" {
  count   = var.postgres_password == "" ? 1 : 0
  length  = 32
  special = false
}

locals {
  postgres_password = var.postgres_password != "" ? var.postgres_password : random_password.postgres[0].result
  # The app connects as the least-privilege cortex_app role (Postgres RLS,
  # migration 0006). Migrations run separately as the admin cortex role.
  postgres_dsn = "postgresql+asyncpg://cortex_app:${local.postgres_password}@postgres-postgresql.${var.namespace}.svc:5432/cortex"
}

resource "kubernetes_namespace" "cortex" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_config_map" "cortex" {
  metadata {
    name      = "cortex-config"
    namespace = kubernetes_namespace.cortex.metadata[0].name
  }
  data = {
    CORTEX_ENV           = "production"
    QDRANT_URL           = "http://qdrant.${var.namespace}.svc:6333"
    REDIS_URL            = "redis://redis-master.${var.namespace}.svc:6379/0"
    CORTEX_QDRANT_SHARDS = tostring(var.qdrant_shards)
    CORTEX_RATELIMIT     = "true"
    CORTEX_EMBEDDER      = "bge"
  }
}

resource "kubernetes_secret" "cortex" {
  metadata {
    name      = "cortex-secrets"
    namespace = kubernetes_namespace.cortex.metadata[0].name
  }
  data = {
    POSTGRES_DSN      = local.postgres_dsn
    ANTHROPIC_API_KEY = var.anthropic_api_key
  }
  type = "Opaque"
}

resource "helm_release" "postgres" {
  name       = "postgres"
  namespace  = kubernetes_namespace.cortex.metadata[0].name
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "postgresql"
  version    = "15.5.20"

  set {
    name  = "auth.database"
    value = "cortex"
  }
  set_sensitive {
    name  = "auth.postgresPassword"
    value = local.postgres_password
  }
  set {
    name  = "primary.persistence.size"
    value = var.postgres_storage
  }
}

resource "helm_release" "redis" {
  name       = "redis"
  namespace  = kubernetes_namespace.cortex.metadata[0].name
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "redis"
  version    = "19.6.4"

  set {
    name  = "architecture"
    value = "standalone"
  }
  set {
    name  = "auth.enabled"
    value = "false"
  }
}

resource "helm_release" "qdrant" {
  name       = "qdrant"
  namespace  = kubernetes_namespace.cortex.metadata[0].name
  repository = "https://qdrant.github.io/qdrant-helm"
  chart      = "qdrant"
  version    = "1.13.0"

  set {
    name  = "persistence.size"
    value = var.qdrant_storage
  }
  set {
    name  = "replicaCount"
    value = "3" # sharded; tenant_id is the shard key
  }
}
