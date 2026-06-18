"""Build a connector from a source kind + config (docs/INGESTION.md §1).

The source-management plane stores `(kind, config)` per source; sync looks the
connector up here. `file` sources have no external backfill — their content is
pushed in via the upload endpoint — so they are not buildable here.
"""

from __future__ import annotations

from typing import Any

from cortex.connectors.base import Connector
from cortex.connectors.github import GitHubConnector
from cortex.connectors.sample import SampleConnector

# Kinds whose history can be pulled by `sync`. `file` and the external OAuth
# sources (slack/gmail/notion/linear) are added as their connectors land.
SYNCABLE_KINDS = ("sample", "github")


def build_connector(kind: str, config: dict[str, Any] | None = None) -> Connector:
    """Return a connector for `kind`, configured from `config`. Raises ValueError
    for kinds that have no backfill connector."""
    config = config or {}
    if kind == "sample":
        return SampleConnector()
    if kind == "github":
        repo = config.get("repo")
        if not repo:
            raise ValueError("github source needs config.repo (owner/name)")
        caps = {k: config[k] for k in ("max_files", "max_items") if k in config}
        return GitHubConnector(repo=repo, **caps)
    raise ValueError(f"no backfill connector for source kind {kind!r}")
