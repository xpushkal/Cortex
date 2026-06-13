"""Pluggable LLM gateway — Anthropic SDK or ANY OpenAI-compatible API.

The LLM-gated paths (entity/relation extraction, process synthesis, blurbs,
`/ask` prose, ...) call `complete()` so the provider is a **config flip, not a
code change**:

    CORTEX_LLM_PROVIDER=anthropic    # default; needs ANTHROPIC_API_KEY (+ the `llm` extra)
    CORTEX_LLM_PROVIDER=openrouter   # OpenAI-compatible @ OpenRouter; OPENROUTER_API_KEY
    CORTEX_LLM_PROVIDER=openai       # any OpenAI-compatible endpoint via CORTEX_LLM_BASE_URL

Any non-`anthropic` provider is treated as OpenAI-compatible (plain httpx, no
extra SDK). Point `CORTEX_LLM_BASE_URL` at an `/v1` endpoint and it serves
Groq, Ollama (local, free), GitHub Models, Gemini, vLLM, etc. behind one key:

    # Groq (free):   CORTEX_LLM_BASE_URL=https://api.groq.com/openai/v1
    # Ollama (local):CORTEX_LLM_BASE_URL=http://localhost:11434/v1   (no key)
    # model via CORTEX_LLM_MODEL (or legacy OPENROUTER_MODEL); key via CORTEX_LLM_API_KEY.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
OPENROUTER_DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 4


def loads_json(text: str) -> Any:
    """Best-effort parse of an LLM JSON reply — `{}` on failure, never raises.

    JSON mode isn't enforced, so weak models wrap output in ``` fences, add prose,
    or return empty/null. Try a clean parse, then the widest `{...}` span, then
    give up with an empty dict so one bad reply skips rather than aborts ingest.
    """
    if not text or not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def complete(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 1024,
    json_schema: dict[str, Any] | None = None,
) -> str:
    """Return the model's text for a (system, user) prompt via the configured provider.

    When `json_schema` is given the model is constrained/instructed to emit JSON
    matching it (provider-specific: Anthropic structured outputs vs OpenAI
    response_format) — the caller still `json.loads` the result.
    """
    provider = os.environ.get("CORTEX_LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return _anthropic(system, user, model, max_tokens, json_schema)
    # Everything else is OpenAI-compatible (openrouter, openai, groq, ollama, ...).
    return _openai_compatible(provider, system, user, model, max_tokens, json_schema)


def _anthropic(
    system: str, user: str, model: str | None, max_tokens: int, json_schema: dict[str, Any] | None
) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise RuntimeError(
            "CORTEX_LLM_PROVIDER=anthropic needs the anthropic SDK: uv sync --extra llm"
        ) from exc
    kwargs: dict[str, Any] = {
        "model": model or ANTHROPIC_DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if json_schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
    response = anthropic.Anthropic().messages.create(**kwargs)
    text: str = next(b.text for b in response.content if b.type == "text")
    return text


def _resolve_endpoint(provider: str) -> tuple[str, str | None]:
    """(chat-completions URL, api_key) for an OpenAI-compatible provider."""
    base = os.environ.get("CORTEX_LLM_BASE_URL")
    if not base and provider == "openrouter":
        base = _OPENROUTER_BASE  # back-compat: openrouter has a known default
    if not base:
        raise RuntimeError(
            f"CORTEX_LLM_PROVIDER={provider!r} needs CORTEX_LLM_BASE_URL — an "
            "OpenAI-compatible /v1 endpoint (e.g. https://api.groq.com/openai/v1)"
        )
    key = os.environ.get("CORTEX_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    return base.rstrip("/") + "/chat/completions", key


def _openai_compatible(
    provider: str,
    system: str,
    user: str,
    model: str | None,
    max_tokens: int,
    json_schema: dict[str, Any] | None,
) -> str:
    url, key = _resolve_endpoint(provider)
    if json_schema is not None:
        system = (
            f"{system}\n\nRespond ONLY with JSON matching this schema:\n{json.dumps(json_schema)}"
        )
    body: dict[str, Any] = {
        "model": model
        or os.environ.get("CORTEX_LLM_MODEL")
        or os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_schema is not None:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if key:  # local servers (Ollama) need no key
        headers["Authorization"] = f"Bearer {key}"
    data = _post_with_retry(url, headers, body)
    choices = data.get("choices")
    if not choices:
        # Some gateways wrap upstream failures as HTTP 200 + {"error": {...}}.
        raise RuntimeError(f"{provider} returned no choices: {str(data.get('error', data))[:200]}")
    message = choices[0]["message"]
    # Reasoning models sometimes leave `content` null and put text in `reasoning`.
    content = message.get("content") or message.get("reasoning") or ""
    return str(content)


def _post_with_retry(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """POST and return the parsed JSON, with backoff over transient failures.

    A long ingest fans out hundreds of calls; one transient drop, rate-limit, or
    5xx must not abort it. Retries cover transport errors, HTTP 429/5xx, AND
    200-wrapped `{"error": {"code": 429|5xx}}` envelopes some gateways return.
    """
    import httpx

    delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=120.0)
            if response.status_code in _RETRY_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            else:
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                error = data.get("error")
                if error and _retryable_error_code(error):
                    last_exc = RuntimeError(f"provider transient error: {error}")
                else:
                    return data
        except httpx.TransportError as exc:  # RemoteProtocolError, timeouts, conn resets
            last_exc = exc
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _retryable_error_code(error: dict[str, Any]) -> bool:
    try:
        return int(error.get("code", 0)) in _RETRY_STATUS
    except (TypeError, ValueError):
        return False
