variable "kubeconfig_path" {
  description = "Path to the kubeconfig for the target cluster."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "kubeconfig context to deploy into."
  type        = string
  default     = null
}

variable "namespace" {
  description = "Namespace for Cortex workloads and data stores."
  type        = string
  default     = "cortex"
}

variable "postgres_password" {
  description = "Password for the cortex_app least-privilege role (generated if empty)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for LLM extraction / generation."
  type        = string
  default     = ""
  sensitive   = true
}

variable "qdrant_shards" {
  description = "Shard count for the chunks collection (load distribution)."
  type        = number
  default     = 6
}

variable "postgres_storage" {
  description = "Persistent volume size for managed Postgres."
  type        = string
  default     = "50Gi"
}

variable "qdrant_storage" {
  description = "Persistent volume size for the Qdrant cluster."
  type        = string
  default     = "100Gi"
}
