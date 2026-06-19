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
from cortex.connectors.github import GitHubConnector
from cortex.connectors.linear import LinearConnector
from cortex.connectors.notion import NotionConnector
from cortex.connectors.registry import SYNCABLE_KINDS, build_connector
from cortex.connectors.sample import SAMPLE_CORPUS, SampleConnector
from cortex.connectors.slack import SlackConnector

__all__ = [
    "SAMPLE_CORPUS",
    "SYNCABLE_KINDS",
    "Artifact",
    "Connector",
    "Cursor",
    "GitHubConnector",
    "LinearConnector",
    "NotionConnector",
    "RawItem",
    "SampleConnector",
    "SlackConnector",
    "SourceConfig",
    "TokenBucketSpec",
    "build_connector",
]
