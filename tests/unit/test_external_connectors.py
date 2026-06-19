"""Notion / Slack / Linear / Gmail connectors over mocked APIs (hermetic)."""

from __future__ import annotations

import base64

import httpx
import pytest

from cortex.connectors import (
    Connector,
    GmailConnector,
    LinearConnector,
    NotionConnector,
    SlackConnector,
    build_connector,
)
from cortex.connectors.base import Cursor, SourceConfig

CFG = SourceConfig(kind="x")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


# --- Notion -----------------------------------------------------------------


def _notion_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/search":
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "p1",
                        "created_time": "2026-01-01T00:00:00.000Z",
                        "last_edited_time": "2026-03-01T00:00:00.000Z",
                        "properties": {
                            "Name": {"type": "title", "title": [{"plain_text": "Refund Policy"}]}
                        },
                    }
                ],
                "has_more": False,
            },
        )
    if request.url.path == "/v1/blocks/p1/children":
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"plain_text": "Refunds over $500 need finance."}]
                        },
                    },
                    {"type": "divider", "divider": {}},
                ],
                "has_more": False,
            },
        )
    return httpx.Response(404, json={})


def test_notion_backfill_and_normalize() -> None:
    conn = NotionConnector(client=_client(_notion_handler))
    arts = [conn.normalize(r) for r in conn.backfill(CFG)]
    assert len(arts) == 1
    art = arts[0]
    assert art.source_kind == "notion" and art.kind == "page"
    assert art.external_id == "page:p1"
    assert "Refund Policy" in art.content and "finance" in art.content


def test_notion_poll_filters_by_cursor() -> None:
    conn = NotionConnector(client=_client(_notion_handler))
    items, cursor = conn.poll(CFG, Cursor(value={"since": "2026-06-01T00:00:00.000Z"}))
    assert list(items) == []  # page edited 2026-03 is older than the cursor
    assert "since" in cursor.value


# --- Slack ------------------------------------------------------------------


def _slack_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/conversations.list":
        return httpx.Response(
            200, json={"ok": True, "channels": [{"id": "C1"}], "response_metadata": {}}
        )
    if request.url.path == "/conversations.history":
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"ts": "1700000000.000100", "text": "Refund approved by finance."},
                    {"ts": "1700000001.000200", "subtype": "channel_join", "text": "joined"},
                ],
                "response_metadata": {},
            },
        )
    return httpx.Response(404, json={"ok": False, "error": "not_found"})


def test_slack_backfill_skips_system_messages() -> None:
    conn = SlackConnector(client=_client(_slack_handler))
    arts = [conn.normalize(r) for r in conn.backfill(CFG)]
    assert len(arts) == 1  # the channel_join subtype is skipped
    art = arts[0]
    assert art.source_kind == "slack" and art.kind == "message"
    assert art.external_id == "slack:C1:1700000000.000100"
    assert "Refund approved" in art.content


def test_slack_api_error_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    conn = SlackConnector(client=_client(handler))
    with pytest.raises(RuntimeError, match="invalid_auth"):
        list(conn.backfill(CFG))


# --- Linear -----------------------------------------------------------------


def _linear_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/graphql":
        return httpx.Response(
            200,
            json={
                "data": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "uuid-1",
                                "identifier": "ENG-7",
                                "title": "Escalate sev1",
                                "description": "Page the on-call.",
                                "createdAt": "2026-02-01T00:00:00.000Z",
                                "updatedAt": "2026-02-02T00:00:00.000Z",
                            }
                        ],
                    }
                }
            },
        )
    return httpx.Response(404, json={})


def test_linear_backfill_and_normalize() -> None:
    conn = LinearConnector(client=_client(_linear_handler))
    arts = [conn.normalize(r) for r in conn.backfill(CFG)]
    assert len(arts) == 1
    art = arts[0]
    assert art.source_kind == "linear" and art.kind == "issue"
    assert art.external_id == "linear:ENG-7"
    assert "Escalate sev1" in art.content and "on-call" in art.content


def test_linear_graphql_error_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "bad auth"}]})

    conn = LinearConnector(client=_client(handler))
    with pytest.raises(RuntimeError, match="linear graphql error"):
        list(conn.backfill(CFG))


# --- Gmail ------------------------------------------------------------------


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _gmail_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/gmail/v1/users/me/messages":
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    if request.url.path == "/gmail/v1/users/me/messages/m1":
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "internalDate": "1700000000000",
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [{"name": "Subject", "value": "Refund escalation"}],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64url("Route over $500 to finance.")},
                        },
                        {"mimeType": "text/html", "body": {"data": _b64url("<p>ignored</p>")}},
                    ],
                },
            },
        )
    return httpx.Response(404, json={})


def test_gmail_backfill_extracts_subject_and_plaintext() -> None:
    conn = GmailConnector(client=_client(_gmail_handler))
    arts = [conn.normalize(r) for r in conn.backfill(CFG)]
    assert len(arts) == 1
    art = arts[0]
    assert art.source_kind == "gmail" and art.kind == "email"
    assert art.external_id == "gmail:m1"
    assert "Refund escalation" in art.content and "finance" in art.content
    assert "ignored" not in art.content  # html part not used when text/plain exists


# --- protocol + registry ----------------------------------------------------


@pytest.mark.parametrize(
    ("conn", "handler"),
    [
        (NotionConnector, _notion_handler),
        (SlackConnector, _slack_handler),
        (LinearConnector, _linear_handler),
        (GmailConnector, _gmail_handler),
    ],
)
def test_connectors_satisfy_protocol(conn, handler) -> None:
    assert isinstance(conn(client=_client(handler)), Connector)


def test_registry_builds_new_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setenv("SLACK_TOKEN", "t")
    monkeypatch.setenv("LINEAR_API_KEY", "t")
    monkeypatch.setenv("GMAIL_TOKEN", "t")
    for kind in ("notion", "slack", "linear", "gmail"):
        assert build_connector(kind).kind == kind


def test_registry_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="no backfill connector"):
        build_connector("dropbox")
