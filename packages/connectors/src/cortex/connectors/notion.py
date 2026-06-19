"""Notion connector (docs/INGESTION.md §1) — a real source over the Notion API.

Backfills a workspace's pages into canonical artifacts: the `/v1/search` endpoint
lists pages, then each page's top-level blocks are flattened to text. Authenticated
with an internal integration token (`NOTION_TOKEN`) shared with the pages it should
read. Honors Notion's 429 + `Retry-After`. `httpx.Client` is injectable so the
connector is unit-tested hermetically.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec

_API = "https://api.notion.com"
_VERSION = "2022-06-28"
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5
# Block types whose rich_text is worth ingesting (skip dividers, images, etc.).
_TEXT_BLOCKS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
        "code",
    }
)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)


def _rich_text(parts: list[dict[str, Any]]) -> str:
    return "".join(p.get("plain_text", "") for p in parts)


def _page_title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _rich_text(prop.get("title", [])) or "Untitled"
    return "Untitled"


class NotionConnector:
    """Ingests a Notion workspace's pages (title + flattened blocks) over the API."""

    kind = "notion"
    rate_limit = TokenBucketSpec(capacity=10, refill_per_second=3.0)  # Notion ~3 req/s

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        max_items: int = 500,
    ) -> None:
        self._token = token or os.environ.get("NOTION_TOKEN")
        self._client = client
        self._max_items = max_items
        if client is None and not self._token:
            raise RuntimeError(
                "NotionConnector needs a token: set NOTION_TOKEN (an internal "
                "integration token shared with the pages to read)."
            )

    # --- HTTP -------------------------------------------------------------------

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=_API,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": _VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _request(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = client.request(method, path, json=json)
                if resp.status_code == 429:
                    time.sleep(min(float(resp.headers.get("Retry-After", "1")) + 0.5, 60))
                    continue
                if resp.status_code in _RETRY_STATUS:
                    last_exc = httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    return resp
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
            yield from self._pages(client, since=None)
        finally:
            if self._client is None:
                client.close()

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        """Incremental delta: pages edited since the cursor's `last_edited_time`.

        Search is sorted by `last_edited_time` descending; we stop once we cross the
        cursor. The next cursor is captured before fetching so a page edited mid-poll
        isn't missed next time.
        """
        since = cursor.value.get("since")
        next_since = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        def _items() -> Iterator[RawItem]:
            client = self._client or self._new_client()
            try:
                yield from self._pages(client, since=since)
            finally:
                if self._client is None:
                    client.close()

        return _items(), Cursor(value={"since": next_since})

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind="page",
            content=str(raw.payload["content"]),
            created_at=_parse_dt(raw.payload.get("created_at")),
        )

    # --- internals --------------------------------------------------------------

    def _pages(self, client: httpx.Client, *, since: str | None) -> Iterator[RawItem]:
        cursor: str | None = None
        seen = 0
        while seen < self._max_items:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            data = self._request(client, "POST", "/v1/search", json=body).json()
            for page in data.get("results", []):
                if seen >= self._max_items:
                    break
                edited = str(page.get("last_edited_time", ""))
                if since and edited < since:
                    return  # sorted desc: everything below is older than the cursor
                item = self._page_item(client, page)
                if item is not None:
                    seen += 1
                    yield item
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def _page_item(self, client: httpx.Client, page: dict[str, Any]) -> RawItem | None:
        page_id = page["id"]
        title = _page_title(page)
        body = self._page_text(client, page_id)
        content = f"{title}\n\n{body}".strip()
        if not content:
            return None
        return RawItem(
            external_id=f"page:{page_id}",
            payload={"content": content, "created_at": page.get("created_time")},
        )

    def _page_text(self, client: httpx.Client, page_id: str) -> str:
        lines: list[str] = []
        cursor: str | None = None
        while True:
            path = f"/v1/blocks/{page_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._request(client, "GET", path).json()
            for block in data.get("results", []):
                btype = block.get("type")
                if btype in _TEXT_BLOCKS:
                    text = _rich_text(block.get(btype, {}).get("rich_text", []))
                    if text:
                        lines.append(text)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(lines)
