"""GitHub connector (docs/INGESTION.md §1) — a real source over the REST API.

Backfills a repository's markdown docs, issues, and pull requests into canonical
artifacts. Authenticated with a fine-grained or classic PAT (`GITHUB_TOKEN`),
read-only on Contents / Issues / Pull requests. Honors GitHub's rate limit
(sleeps on a `403` + exhausted quota) on top of the ingest-level per-source token
bucket. `httpx.Client` is injectable so the connector is unit-tested hermetically.
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

_API = "https://api.github.com"
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)


class GitHubConnector:
    """Ingests one repo's markdown docs, issues, and PRs over the GitHub REST API."""

    kind = "github"
    # Coarse per-source safety bucket; GitHub's real 5000/hr limit is enforced by
    # the 403-backoff in `_get`. Sized generously since pages return many items.
    rate_limit = TokenBucketSpec(capacity=100, refill_per_second=5.0)

    def __init__(
        self,
        repo: str,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        max_files: int = 200,
        max_items: int = 500,
    ) -> None:
        self.repo = repo  # "owner/name"
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._client = client
        self._max_files = max_files
        self._max_items = max_items
        if client is None and not self._token:
            raise RuntimeError(
                "GitHubConnector needs a token: set GITHUB_TOKEN in your environment "
                "or pass token= (a fine-grained PAT with read access)."
            )

    # --- HTTP -------------------------------------------------------------------

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=_API,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def _get(
        self, client: httpx.Client, path: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """GET with backoff over transient network errors / 5xx / rate limits.

        A full backfill fans out hundreds of calls; one transient ReadTimeout or
        502 must not abort it. The 403 + exhausted-quota case waits for the reset.
        """
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = client.get(path, params=params)
                if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                    reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                    time.sleep(min(max(0, reset - int(time.time())) + 1, 60))
                    continue
                if resp.status_code in _RETRY_STATUS:
                    last_exc = httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    return resp
            except httpx.TransportError as exc:  # ReadTimeout, ConnectError, RemoteProtocolError
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
            repo_info = self._get(client, f"/repos/{self.repo}").json()
            branch = repo_info.get("default_branch", "main")
            repo_created = repo_info.get("created_at")
            yield from self._markdown(client, branch, repo_created)
            yield from self._issues(client)
            yield from self._pulls(client)
        finally:
            if self._client is None:
                client.close()

    def poll(self, cfg: SourceConfig, cursor: Cursor) -> tuple[Iterator[RawItem], Cursor]:
        # Incremental sync (issues/PRs `since` the cursor) is a follow-up; backfill
        # + the idempotent content_hash skip keeps re-ingest cheap for now.
        return iter(()), cursor

    def normalize(self, raw: RawItem) -> Artifact:
        return Artifact(
            source_kind=self.kind,
            external_id=raw.external_id,
            kind=str(raw.payload["kind"]),
            content=str(raw.payload["content"]),
            created_at=_parse_dt(raw.payload.get("created_at")),
        )

    # --- backfill sources -------------------------------------------------------

    def _markdown(
        self, client: httpx.Client, branch: str, repo_created: str | None
    ) -> Iterator[RawItem]:
        tree = self._get(
            client, f"/repos/{self.repo}/git/trees/{branch}", params={"recursive": "1"}
        ).json()
        seen = 0
        for node in tree.get("tree", []):
            if seen >= self._max_files:
                break
            path = node.get("path", "")
            if node.get("type") != "blob" or not path.lower().endswith((".md", ".markdown")):
                continue
            blob = self._get(
                client, f"/repos/{self.repo}/contents/{path}", params={"ref": branch}
            ).json()
            content = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace").strip()
            if not content:
                continue
            seen += 1
            yield RawItem(
                external_id=f"file:{path}",
                payload={"kind": "doc", "content": content, "created_at": repo_created},
            )

    def _issues(self, client: httpx.Client) -> Iterator[RawItem]:
        for issue in self._paginate(
            client, f"/repos/{self.repo}/issues", {"state": "all", "per_page": 100}
        ):
            if "pull_request" in issue:  # the issues endpoint also returns PRs
                continue
            content = f"{issue.get('title', '')}\n\n{issue.get('body') or ''}".strip()
            yield RawItem(
                external_id=f"issue:{issue['number']}",
                payload={
                    "kind": "issue",
                    "content": content,
                    "created_at": issue.get("created_at"),
                },
            )

    def _pulls(self, client: httpx.Client) -> Iterator[RawItem]:
        for pr in self._paginate(
            client, f"/repos/{self.repo}/pulls", {"state": "all", "per_page": 100}
        ):
            content = f"{pr.get('title', '')}\n\n{pr.get('body') or ''}".strip()
            yield RawItem(
                external_id=f"pr:{pr['number']}",
                payload={"kind": "pr", "content": content, "created_at": pr.get("created_at")},
            )

    def _paginate(
        self, client: httpx.Client, path: str, params: dict[str, Any]
    ) -> Iterator[dict[str, Any]]:
        page, seen = 1, 0
        while seen < self._max_items:
            batch = self._get(client, path, params={**params, "page": page}).json()
            if not batch:
                break
            for item in batch:
                if seen >= self._max_items:
                    break
                seen += 1
                yield item
            page += 1
