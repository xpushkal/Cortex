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


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CORTEX_LLM_BASE_URL", "CORTEX_LLM_API_KEY", "CORTEX_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_openai_compatible_provider_needs_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-anthropic provider with no base URL (and not openrouter) errors clearly.
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "groq")
    with pytest.raises(RuntimeError, match="CORTEX_LLM_BASE_URL"):
        complete(system="s", user="u")


def test_groq_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Groq path: custom base URL + key + model via the generic CORTEX_LLM_* vars.
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "groq")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("CORTEX_LLM_API_KEY", "gsk_test")
    monkeypatch.setenv("CORTEX_LLM_MODEL", "llama-3.3-70b-versatile")
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert complete(system="s", user="u") == "ok"
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer gsk_test"
    assert captured["json"]["model"] == "llama-3.3-70b-versatile"


def test_local_endpoint_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ollama-style local server: base URL, no API key -> no Authorization header.
    _clear_llm_env(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "http://localhost:11434/v1")
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert complete(system="s", user="u") == "ok"
    assert "Authorization" not in captured["headers"]


def test_openrouter_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
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


def test_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    slept: list[float] = []
    monkeypatch.setattr("cortex.obs.llm.time.sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float) -> httpx.Response:
        calls["n"] += 1
        req = httpx.Request("POST", url)
        if calls["n"] == 1:  # rate-limited, told to wait 7s
            return httpx.Response(429, headers={"retry-after": "7"}, json={}, request=req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=req)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert complete(system="s", user="u") == "ok"
    assert slept == [7.0]  # waited exactly the server's Retry-After, not the 0.5s backoff


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
    _clear_llm_env(monkeypatch)
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
