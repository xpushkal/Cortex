output "namespace" {
  description = "Namespace Cortex is deployed into."
  value       = kubernetes_namespace.cortex.metadata[0].name
}

output "postgres_dsn" {
  description = "Async DSN for the least-privilege cortex_app role."
  value       = local.postgres_dsn
  sensitive   = true
}

output "qdrant_url" {
  description = "In-cluster Qdrant endpoint."
  value       = "http://qdrant.${var.namespace}.svc:6333"
}

output "redis_url" {
  description = "In-cluster Redis endpoint."
  value       = "redis://redis-master.${var.namespace}.svc:6379/0"
}
