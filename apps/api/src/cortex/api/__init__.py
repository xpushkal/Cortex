"""Cortex serving plane (FastAPI). Stateless; horizontal scale = add pods.

Endpoints (docs/API.md): /ask /search /processes /skills /sources. All
tenant-scoped; retrieval is always tenant-filtered server-side.
"""
