"""GitHub connector over a mocked REST API (hermetic — no network)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from cortex.connectors import GitHubConnector
from cortex.connectors.base import Connector, Cursor, SourceConfig

CFG = SourceConfig(kind="github")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    page = request.url.params.get("page", "1")
    if path == "/repos/acme/widgets":
        return httpx.Response(
            200, json={"default_branch": "main", "created_at": "2026-01-01T00:00:00Z"}
        )
    if path == "/repos/acme/widgets/git/trees/main":
        return httpx.Response(
            200,
            json={
                "tree": [
                    {"type": "blob", "path": "README.md"},
                    {"type": "blob", "path": "src/app.py"},  # not markdown -> skipped
                    {"type": "blob", "path": "docs/guide.markdown"},
                ]
            },
        )
    if path == "/repos/acme/widgets/contents/README.md":
        return httpx.Response(200, json={"content": _b64("# Widgets\nRefund policy lives here.")})
    if path == "/repos/acme/widgets/contents/docs/guide.markdown":
        return httpx.Response(200, json={"content": _b64("## Guide\nHow to deploy.")})
    if path == "/repos/acme/widgets/issues":
        if page != "1":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "number": 7,
                    "title": "Login bug",
                    "body": "Steps to repro",
                    "created_at": "2026-02-01T00:00:00Z",
                },
                # The issues endpoint also returns PRs — must be filtered out.
                {
                    "number": 8,
                    "title": "A PR",
                    "body": "x",
                    "pull_request": {"url": "..."},
                    "created_at": "2026-02-02T00:00:00Z",
                },
            ],
        )
    if path == "/repos/acme/widgets/pulls":
        if page != "1":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "number": 8,
                    "title": "Add caching",
                    "body": "Speeds it up",
                    "created_at": "2026-02-02T00:00:00Z",
                }
            ],
        )
    return httpx.Response(404, json={"message": f"unhandled {path}"})


def _connector() -> GitHubConnector:
    client = httpx.Client(
        transport=httpx.MockTransport(_handler), base_url="https://api.github.com"
    )
    return GitHubConnector("acme/widgets", client=client)


def test_implements_connector_protocol() -> None:
    assert isinstance(_connector(), Connector)


def test_backfill_yields_docs_issues_and_prs() -> None:
    items = list(_connector().backfill(CFG))
    by_id = {i.external_id: i for i in items}

    # Two markdown docs (app.py skipped), one issue (the PR-as-issue filtered), one PR.
    assert "file:README.md" in by_id
    assert "file:docs/guide.markdown" in by_id
    assert "file:src/app.py" not in by_id
    assert "issue:7" in by_id
    assert "issue:8" not in by_id  # that "issue" was a PR
    assert "pr:8" in by_id

    assert by_id["file:README.md"].payload["kind"] == "doc"
    assert "Refund policy" in by_id["file:README.md"].payload["content"]
    assert by_id["issue:7"].payload["kind"] == "issue"
    assert by_id["pr:8"].payload["kind"] == "pr"


def test_normalize_maps_to_artifact() -> None:
    conn = _connector()
    items = {i.external_id: i for i in conn.backfill(CFG)}
    art = conn.normalize(items["issue:7"])
    assert art.source_kind == "github"
    assert art.kind == "issue"
    assert art.created_at.year == 2026
    assert "Login bug" in art.content


def test_poll_returns_updated_issues_and_prs_and_advances_cursor() -> None:
    # A poll with no prior cursor returns touched issues/PRs and sets a `since`.
    conn = _connector()
    items, cursor = conn.poll(CFG, Cursor())
    by_id = {i.external_id: i for i in items}
    assert "issue:7" in by_id  # the real issue
    assert "issue:8" not in by_id  # the PR-as-issue is filtered out
    assert "pr:8" in by_id
    assert "file:README.md" not in by_id  # docs aren't polled
    assert cursor.value.get("since")  # cursor advanced to a timestamp


def test_poll_passes_since_and_stops_prs_past_cursor() -> None:
    # With a cursor, `since` is sent to the issues endpoint and PR iteration stops
    # once it crosses the cursor timestamp (pulls are sorted updated-desc).
    seen_since: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/widgets/issues":
            seen_since["issues"] = request.url.params.get("since", "")
            if request.url.params.get("page", "1") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 7,
                        "title": "fresh",
                        "body": "x",
                        "updated_at": "2026-06-10T00:00:00Z",
                    }
                ],
            )
        if path == "/repos/acme/widgets/pulls":
            assert request.url.params.get("direction") == "desc"
            if request.url.params.get("page", "1") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 9,
                        "title": "newer",
                        "body": "x",
                        "updated_at": "2026-06-09T00:00:00Z",
                    },
                    {
                        "number": 5,
                        "title": "older",
                        "body": "x",
                        "updated_at": "2026-05-01T00:00:00Z",
                    },
                ],
            )
        return httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    conn = GitHubConnector("acme/widgets", client=client)
    items, _ = conn.poll(CFG, Cursor(value={"since": "2026-06-01T00:00:00Z"}))
    ids = [i.external_id for i in items]
    assert seen_since["issues"] == "2026-06-01T00:00:00Z"  # since forwarded to the API
    assert ids == ["issue:7", "pr:9"]  # pr:5 (older than cursor) stopped early


def test_requires_token_without_injected_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="needs a token"):
        GitHubConnector("acme/widgets")


def test_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_test")
    conn = GitHubConnector("acme/widgets")
    assert conn.repo == "acme/widgets"
    # Sanity: the token is wired into the auth header of a real client.
    client = conn._new_client()
    assert "github_pat_test" in client.headers["Authorization"]
    client.close()


def test_json_payload_is_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    # RawItem payloads must be JSON-serializable (they flow through the pipeline).
    items = list(_connector().backfill(CFG))
    json.dumps([i.payload for i in items])


def test_get_retries_transient_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # A backfill fans out hundreds of calls; one transient ReadTimeout must not abort it.
    monkeypatch.setattr("cortex.connectors.github.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets":
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("timed out", request=request)
        return _handler(request)

    client = httpx.Client(transport=httpx.MockTransport(flaky), base_url="https://api.github.com")
    items = list(GitHubConnector("acme/widgets", client=client).backfill(CFG))
    assert calls["n"] == 2  # retried past the timeout
    assert any(i.external_id == "file:README.md" for i in items)
