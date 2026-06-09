"""Cortex source connectors. One adapter per source; see docs/INGESTION.md §1.

Every connector implements the `Connector` protocol (backfill/poll/normalize)
and owns a per-source token bucket. The `sample` connector seeds a deterministic
synthetic corpus for tests and the eval golden set.
"""

from cortex.connectors.base import (
    Artifact,
    Connector,
    Cursor,
    RawItem,
    SourceConfig,
    TokenBucketSpec,
)

__all__ = ["Artifact", "Connector", "Cursor", "RawItem", "SourceConfig", "TokenBucketSpec"]
