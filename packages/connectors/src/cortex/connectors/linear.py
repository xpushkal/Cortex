"""Linear connector (docs/INGESTION.md §1) — a real source over the Linear API.

Backfills issues into canonical artifacts via Linear's GraphQL API (cursor
pagination over `issues`). Authenticated with a personal API key (`LINEAR_API_KEY`)
passed in the `Authorization` header (Linear uses the raw key, not a Bearer prefix).
Honors 429 + `Retry-After`. `httpx.Client` is injectable for hermetic unit tests.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec

_API = "https://api.linear.app"
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5

_QUERY = """
query Issues($after: String, $filter: IssueFilter) {
  issues(first: 100, after: $after, filter: $filter,
         orderBy: updatedAt) {
    pageInfo { hasNextPage endCursor }
    nodes { id identifier title description createdAt updatedAt }
  }
}
"""


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)


class LinearConnector:
    """Ingests a Linear workspace's issues (title + description) over GraphQL."""

    kind = "linear"
    rate_limit = TokenBucketSpec(capacity=20, refill_per_second=2.0)

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        max_items: int = 1000,
    ) -> None:
        self._token = token or os.environ.get("LINEAR_API_KEY")
        self._client = client
        self._max_items = max_items
        if client is None and not self._token:
            raise RuntimeError(
                "LinearConnector needs a key: set LINEAR_API_KEY (a personal API key)."
            )

    # --- HTTP -------------------------------------------------------------------

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=_API,
            headers={"Authorization": self._token or "", "Content-Type": "application/json"},
            timeout=30.0,
        )

    def _query(self, client: httpx.Client, variables: dict[str, Any]) -> dict[str, Any]:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = client.post("/graphql", json={"query": _QUERY, "variables": variables})
                if resp.status_code == 429:
                    time.sleep(min(float(resp.headers.get("Retry-After", "1")) + 0.5, 60))
                    continue
                if resp.status_code in _RETRY_STATUS:
                    last_exc = httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    data: dict[str, Any] = resp.json()
                    if data.get("errors"):
                        raise RuntimeError(f"linear graphql error: {data['errors']}")
                    issues: dict[str, Any] = data["data"]["issues"]
                    return issues
            except httpx.TransportError as exc:
                last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(delay)
                delay *= 2
        assert last_exc is not None
        raise last_exc

    # --- Connector protocol -----------------------------------------------------

    def backfill(self, cfg: SourceConfig) -> Iterator[RawItem]:
        client = self._client or self._new_client()
        try:
            yield from self._issues(client, since=None)
        finally:
            if self._client is None:
                client.close()

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        """Incremental delta: issues updated since the cursor (server-side filter)."""
        since = cursor.value.get("since")
        next_since = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        def _items() -> Iterator[RawItem]:
            client = self._client or self._new_client()
            try:
                yield from self._issues(client, since=since)
            finally:
                if self._client is None:
                    client.close()

        return _items(), Cursor(value={"since": next_since})

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind="issue",
            content=str(raw.payload["content"]),
            created_at=_parse_dt(raw.payload.get("created_at")),
        )

    # --- internals --------------------------------------------------------------

    def _issues(self, client: httpx.Client, *, since: str | None) -> Iterator[RawItem]:
        after: str | None = None
        seen = 0
        filt = {"updatedAt": {"gt": since}} if since else None
        while seen < self._max_items:
            page = self._query(client, {"after": after, "filter": filt})
            for node in page.get("nodes", []):
                if seen >= self._max_items:
                    break
                title = node.get("title", "")
                desc = node.get("description") or ""
                content = f"{title}\n\n{desc}".strip()
                if not content:
                    continue
                seen += 1
                yield RawItem(
                    external_id=f"linear:{node.get('identifier', node['id'])}",
                    payload={"content": content, "created_at": node.get("createdAt")},
                )
            info = page.get("pageInfo", {})
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
