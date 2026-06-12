"""Pluggable LLM gateway — provider switch + OpenRouter wire format (mocked)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from cortex.obs import complete
from cortex.obs.llm import loads_json


def test_loads_json_tolerates_messy_replies() -> None:
    assert loads_json('{"a": 1}') == {"a": 1}
    # fenced + prose around the JSON (common with weak models)
    assert loads_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert loads_json('Sure! Here:\n{"a": 1}\nHope that helps') == {"a": 1}
    # empty / null / unparseable -> {} (skip, never raise)
    assert loads_json("") == {}
    assert loads_json("   ") == {}
    assert loads_json("not json at all") == {}


def test_unknown_provider_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "ollama")
    with pytest.raises(ValueError, match="unknown CORTEX_LLM_PROVIDER"):
        complete(system="s", user="u")


def test_openrouter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        complete(system="s", user="u")


def test_openrouter_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        req = httpx.Request("POST", url)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}, request=req
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    out = complete(
        system="extract entities",
        user="Refunds over $500 go to finance.",
        max_tokens=512,
        json_schema={"type": "object", "required": ["entities"]},
    )
    assert out == '{"ok": true}'
    assert "openrouter.ai" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer or-test-key"
    body = captured["json"]
    assert body["model"] == "openai/gpt-4o-mini"  # env override honored
    assert body["max_tokens"] == 512
    assert body["messages"][1]["content"].startswith("Refunds over")
    # JSON mode: response_format set + the schema instructed into the system turn.
    assert body["response_format"] == {"type": "json_object"}
    assert "entities" in body["messages"][0]["content"]


def test_openrouter_retries_transient_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("cortex.obs.llm.time.sleep", lambda _s: None)  # no real backoff
    calls = {"n": 0}

    def flaky_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("peer closed connection")  # transient
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", flaky_post)
    assert complete(system="s", user="u") == "ok"
    assert calls["n"] == 2  # retried past the drop


def test_openrouter_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("cortex.obs.llm.time.sleep", lambda _s: None)

    def always_drops(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", always_drops)
    with pytest.raises(httpx.TransportError):
        complete(system="s", user="u")


def test_openrouter_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        captured["json"] = json
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hi"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    complete(system="s", user="u")
    assert captured["json"]["model"] == "anthropic/claude-3.5-sonnet"
