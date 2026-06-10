"""Tenant identity helpers, shared by the API and the ingestion CLI."""

from __future__ import annotations

import uuid

_TENANT_NAMESPACE = "cortex-tenant:"


def resolve_tenant(value: str) -> uuid.UUID:
    """Accept a tenant UUID or a friendly name; names map to a stable uuid5.

    Using a deterministic namespace UUID means `--tenant demo` always resolves to
    the same id across ingest and query, so seeded data is queryable by name.
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"{_TENANT_NAMESPACE}{value}")
