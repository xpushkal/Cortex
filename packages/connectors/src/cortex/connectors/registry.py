"""Build a connector from a source kind + config (docs/INGESTION.md §1).

The source-management plane stores `(kind, config)` per source; sync looks the
connector up here. `file` sources have no external backfill — their content is
pushed in via the upload endpoint — so they are not buildable here.
"""

from __future__ import annotations

from typing import Any

from cortex.connectors.base import Connector
from cortex.connectors.github import GitHubConnector
from cortex.connectors.gmail import GmailConnector
from cortex.connectors.linear import LinearConnector
from cortex.connectors.notion import NotionConnector
from cortex.connectors.sample import SampleConnector
from cortex.connectors.slack import SlackConnector

# Kinds whose history can be pulled by `sync`. Token-based connectors read their
# credential from the environment (NOTION_TOKEN / SLACK_TOKEN / LINEAR_API_KEY /
# GMAIL_TOKEN, like GITHUB_TOKEN); `file` sources take content via upload instead.
SYNCABLE_KINDS = ("sample", "github", "notion", "slack", "linear", "gmail")


def build_connector(kind: str, config: dict[str, Any] | None = None) -> Connector:
    """Return a connector for `kind`, configured from `config`. Raises ValueError
    for kinds that have no backfill connector or are missing required config."""
    config = config or {}
    if kind == "sample":
        return SampleConnector()
    if kind == "github":
        repo = config.get("repo")
        if not repo:
            raise ValueError("github source needs config.repo (owner/name)")
        caps = {k: config[k] for k in ("max_files", "max_items") if k in config}
        return GitHubConnector(repo=repo, **caps)
    if kind == "notion":
        caps = {k: config[k] for k in ("max_items",) if k in config}
        return NotionConnector(**caps)
    if kind == "slack":
        caps = {k: config[k] for k in ("channels", "max_items") if k in config}
        return SlackConnector(**caps)
    if kind == "linear":
        caps = {k: config[k] for k in ("max_items",) if k in config}
        return LinearConnector(**caps)
    if kind == "gmail":
        caps = {k: config[k] for k in ("query", "max_items") if k in config}
        return GmailConnector(**caps)
    raise ValueError(f"no backfill connector for source kind {kind!r}")
