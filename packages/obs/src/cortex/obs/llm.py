"""Pluggable LLM gateway — Anthropic SDK or any OpenAI-compatible API (OpenRouter).

The LLM-gated paths (entity/relation extraction, process synthesis, blurbs,
`/ask` prose, ...) call `complete()` so the provider is a **config flip, not a
code change**:

    CORTEX_LLM_PROVIDER=anthropic   # default; needs ANTHROPIC_API_KEY (+ the `llm` extra)
    CORTEX_LLM_PROVIDER=openrouter  # needs OPENROUTER_API_KEY; model via OPENROUTER_MODEL

OpenRouter is OpenAI-compatible, so its path is plain HTTP (httpx) — no extra SDK
install — and can serve Claude, GPT, Gemini, etc. behind one key.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
OPENROUTER_DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
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
    if provider == "openrouter":
        return _openrouter(system, user, model, max_tokens, json_schema)
    raise ValueError(f"unknown CORTEX_LLM_PROVIDER: {provider!r} (anthropic|openrouter)")


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


def _openrouter(
    system: str, user: str, model: str | None, max_tokens: int, json_schema: dict[str, Any] | None
) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("CORTEX_LLM_PROVIDER=openrouter needs OPENROUTER_API_KEY")
    if json_schema is not None:
        system = (
            f"{system}\n\nRespond ONLY with JSON matching this schema:\n{json.dumps(json_schema)}"
        )
    body: dict[str, Any] = {
        "model": model or os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_schema is not None:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response = _post_with_retry(headers, body)
    message = response.json()["choices"][0]["message"]
    # Reasoning models sometimes leave `content` null and put text in `reasoning`.
    content = message.get("content") or message.get("reasoning") or ""
    return str(content)


def _post_with_retry(headers: dict[str, str], body: dict[str, Any]) -> Any:
    """POST with exponential backoff over transient drops / 429 / 5xx.

    A single long-running ingest fans out hundreds of calls; without this one
    transient `RemoteProtocolError` or rate-limit would abort the whole run.
    """
    import httpx

    delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = httpx.post(_OPENROUTER_URL, headers=headers, json=body, timeout=120.0)
            if response.status_code in _RETRY_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            else:
                response.raise_for_status()
                return response
        except httpx.TransportError as exc:  # RemoteProtocolError, timeouts, conn resets
            last_exc = exc
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc
