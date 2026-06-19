"""Slack connector (docs/INGESTION.md §1) — a real source over the Slack Web API.

Backfills public channel messages into canonical artifacts: `conversations.list`
enumerates channels, then `conversations.history` pulls each channel's messages.
Authenticated with a bot token (`SLACK_TOKEN`, `xoxb-…`) with `channels:read` +
`channels:history`. Honors Slack's 429 + `Retry-After`. `httpx.Client` is injectable
so the connector is unit-tested hermetically.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from cortex.connectors.base import Artifact, Cursor, RawItem, SourceConfig, TokenBucketSpec

_API = "https://slack.com/api"
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5


def _ts_to_dt(ts: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC) if ts else datetime.now(tz=UTC)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)


class SlackConnector:
    """Ingests public-channel messages from a Slack workspace over the Web API."""

    kind = "slack"
    rate_limit = TokenBucketSpec(capacity=20, refill_per_second=1.0)  # Slack tier-3 ~1 req/s

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        channels: list[str] | None = None,
        max_items: int = 1000,
    ) -> None:
        self._token = token or os.environ.get("SLACK_TOKEN")
        self._client = client
        self._channels = channels  # optional allowlist of channel ids
        self._max_items = max_items
        if client is None and not self._token:
            raise RuntimeError(
                "SlackConnector needs a token: set SLACK_TOKEN (a bot token with "
                "channels:read + channels:history)."
            )

    # --- HTTP -------------------------------------------------------------------

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=_API,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )

    def _get(self, client: httpx.Client, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET a Web API method with backoff; raises on a Slack `ok: false`."""
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
                    if not data.get("ok", False):
                        raise RuntimeError(f"slack api error: {data.get('error', 'unknown')}")
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
            yield from self._messages(client, oldest=None)
        finally:
            if self._client is None:
                client.close()

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        """Incremental delta: messages newer than the cursor's `oldest` ts."""
        oldest = cursor.value.get("oldest")
        next_oldest = f"{datetime.now(tz=UTC).timestamp():.6f}"

        def _items() -> Iterator[RawItem]:
            client = self._client or self._new_client()
            try:
                yield from self._messages(client, oldest=oldest)
            finally:
                if self._client is None:
                    client.close()

        return _items(), Cursor(value={"oldest": next_oldest})

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind="message",
            content=str(raw.payload["content"]),
            created_at=_ts_to_dt(raw.payload.get("ts")),
        )

    # --- internals --------------------------------------------------------------

    def _channel_ids(self, client: httpx.Client) -> Iterator[str]:
        if self._channels:
            yield from self._channels
            return
        cursor = ""
        while True:
            params: dict[str, Any] = {"types": "public_channel", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get(client, "/conversations.list", params)
            for ch in data.get("channels", []):
                cid = ch.get("id")
                if cid:
                    yield cid
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

    def _messages(self, client: httpx.Client, *, oldest: str | None) -> Iterator[RawItem]:
        seen = 0
        for channel in self._channel_ids(client):
            cursor = ""
            while seen < self._max_items:
                params: dict[str, Any] = {"channel": channel, "limit": 200}
                if oldest:
                    params["oldest"] = oldest
                if cursor:
                    params["cursor"] = cursor
                data = self._get(client, "/conversations.history", params)
                for msg in data.get("messages", []):
                    if msg.get("subtype") or not msg.get("text"):
                        continue  # skip joins/leaves/system messages
                    if seen >= self._max_items:
                        break
                    seen += 1
                    ts = msg.get("ts")
                    yield RawItem(
                        external_id=f"slack:{channel}:{ts}",
                        payload={"content": str(msg["text"]), "ts": ts},
                    )
                cursor = data.get("response_metadata", {}).get("next_cursor", "")
                if not cursor:
                    break
