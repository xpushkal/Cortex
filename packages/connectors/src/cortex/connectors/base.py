"""The connector contract (docs/INGESTION.md §1).

Every source adapter implements `Connector`: backfill() for first connect, poll()
for incremental deltas (webhook- or interval-driven), and normalize() to map a raw
payload to the canonical `Artifact`. Each owns a per-source token bucket.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class SourceConfig(BaseModel):
    """Per-source configuration: scopes, workspace ids, credentials reference."""

    kind: str
    config: dict[str, Any] = {}


class Cursor(BaseModel):
    """Opaque incremental-sync state persisted per source (docs/DATA_MODEL.md)."""

    value: dict[str, Any] = {}


class RawItem(BaseModel):
    """An un-normalized payload as returned by a source API."""

    external_id: str
    payload: dict[str, Any]


class Artifact(BaseModel):
    """Canonical normalized unit fed into the ingestion pipeline."""

    source_kind: str
    external_id: str
    kind: str  # message | email | page | pr | issue | doc
    content: str
    created_at: datetime
    participants: list[str] = []


class TokenBucketSpec(BaseModel):
    """Per-source rate-limit spec sized to the source's documented API quota."""

    capacity: int
    refill_per_second: float


@runtime_checkable
class Connector(Protocol):
    """The interface every source adapter must satisfy."""

    kind: str
    rate_limit: TokenBucketSpec

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        """One-time full history pull on first connect (paginated)."""
        ...

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        """Incremental delta since `cursor`; returns new items and the next cursor."""
        ...

    def normalize(self, raw: RawItem) -> Artifact:
        """Map a source payload to the canonical `Artifact`."""
        ...
