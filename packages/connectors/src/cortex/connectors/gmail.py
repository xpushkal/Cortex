"""Gmail connector (docs/INGESTION.md §1) — a real source over the Gmail API.

Backfills a mailbox's messages into canonical artifacts: `users.messages.list`
enumerates ids, then each message is fetched and its subject + plain-text body
flattened. Consumes an OAuth2 access token (`GMAIL_TOKEN`) with the read-only
`gmail.readonly` scope — minting/refreshing that token is the deployment's OAuth
concern; the connector just uses it (like the PAT-based connectors). Honors 429 +
`Retry-After`. `httpx.Client` is injectable for hermetic unit tests.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec

_API = "https://gmail.googleapis.com"
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5


def _header(headers: list[dict[str, Any]], name: str) -> str:
    lower = name.lower()
    for h in headers:
        if str(h.get("name", "")).lower() == lower:
            return str(h.get("value", ""))
    return ""


def _decode(data: str | None) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _text_of_type(payload: dict[str, Any], mime_type: str) -> str:
    """Depth-first walk of the MIME tree, collecting bodies of one mime type."""
    if payload.get("mimeType", "") == mime_type:
        return _decode(payload.get("body", {}).get("data"))
    parts = payload.get("parts")
    if parts:
        return "\n".join(filter(None, (_text_of_type(p, mime_type) for p in parts)))
    return ""


def _body_text(payload: dict[str, Any]) -> str:
    """Prefer text/plain; fall back to text/html only when there's no plain part."""
    return _text_of_type(payload, "text/plain") or _text_of_type(payload, "text/html")


def _internal_dt(ms: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC) if ms else datetime.now(tz=UTC)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)


class GmailConnector:
    """Ingests a Gmail mailbox's messages (subject + plain-text body) over the API."""

    kind = "gmail"
    rate_limit = TokenBucketSpec(capacity=20, refill_per_second=5.0)

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        query: str | None = None,
        max_items: int = 1000,
    ) -> None:
        self._token = token or os.environ.get("GMAIL_TOKEN")
        self._client = client
        self._query = query  # optional Gmail search filter (e.g. "label:inbox")
        self._max_items = max_items
        if client is None and not self._token:
            raise RuntimeError(
                "GmailConnector needs a token: set GMAIL_TOKEN (an OAuth2 access "
                "token with the gmail.readonly scope)."
            )

    # --- HTTP -------------------------------------------------------------------

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=_API,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )

    def _get(
        self, client: httpx.Client, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = client.get(path, params=params)
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
                    return data
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
            yield from self._messages(client, query=self._query)
        finally:
            if self._client is None:
                client.close()

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        """Incremental delta: messages newer than the cursor (Gmail `after:` filter)."""
        after = cursor.value.get("after")
        next_after = str(int(datetime.now(tz=UTC).timestamp()))
        query = f"after:{after}" if after else None
        if self._query:
            query = f"{self._query} {query}".strip() if query else self._query

        def _items() -> Iterator[RawItem]:
            client = self._client or self._new_client()
            try:
                yield from self._messages(client, query=query)
            finally:
                if self._client is None:
                    client.close()

        return _items(), Cursor(value={"after": next_after})

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind="email",
            content=str(raw.payload["content"]),
            created_at=_internal_dt(raw.payload.get("internal_date")),
        )

    # --- internals --------------------------------------------------------------

    def _messages(self, client: httpx.Client, *, query: str | None) -> Iterator[RawItem]:
        page_token: str | None = None
        seen = 0
        while seen < self._max_items:
            params: dict[str, Any] = {"maxResults": 100}
            if query:
                params["q"] = query
            if page_token:
                params["pageToken"] = page_token
            listing = self._get(client, "/gmail/v1/users/me/messages", params)
            for ref in listing.get("messages", []):
                if seen >= self._max_items:
                    break
                item = self._message_item(client, ref["id"])
                if item is not None:
                    seen += 1
                    yield item
            page_token = listing.get("nextPageToken")
            if not page_token:
                break

    def _message_item(self, client: httpx.Client, msg_id: str) -> RawItem | None:
        msg = self._get(client, f"/gmail/v1/users/me/messages/{msg_id}", params={"format": "full"})
        payload = msg.get("payload", {})
        subject = _header(payload.get("headers", []), "Subject")
        body = _body_text(payload)
        content = f"{subject}\n\n{body}".strip()
        if not content:
            return None
        return RawItem(
            external_id=f"gmail:{msg_id}",
            payload={"content": content, "internal_date": msg.get("internalDate")},
        )
