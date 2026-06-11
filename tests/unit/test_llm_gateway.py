"""Pluggable LLM gateway — provider switch + OpenRouter wire format (mocked)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from cortex.obs import complete


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
