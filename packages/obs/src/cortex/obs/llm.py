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

Free tiers rate-limit hard. Two optional client-side gates keep a burst (an
ingest fans out hundreds of calls) under the limit instead of 429-skipping:
`CORTEX_LLM_RPM` (requests/min) and `CORTEX_LLM_TPM` (tokens/min) — e.g. 30 / 6000
for Groq's free Llama tier. Both off by default and process-local.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
OPENROUTER_DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 6
_MAX_BACKOFF = 60.0  # cap a single Retry-After / backoff wait (seconds)

# Proactive pacing: a process-global gate so a burst (an ingest fans out hundreds
# of calls) stays under the provider's requests-per-minute limit instead of
# tripping 429s and burning the reactive Retry-After budget. Off unless
# CORTEX_LLM_RPM is set (e.g. 30 for Groq's free tier). Process-local — across
# multiple worker processes, set each process's RPM to a fair share of the quota.
_rate_lock = threading.Lock()
_last_call_monotonic = 0.0


def _min_interval() -> float:
    """Seconds to space consecutive calls, derived from CORTEX_LLM_RPM (0 = off)."""
    raw = os.environ.get("CORTEX_LLM_RPM")
    if not raw:
        return 0.0
    try:
        rpm = float(raw)
    except ValueError:
        return 0.0
    return 60.0 / rpm if rpm > 0 else 0.0


def _pace() -> None:
    """Block until at least `_min_interval()` has elapsed since the last call."""
    interval = _min_interval()
    if interval <= 0:
        return
    global _last_call_monotonic
    with _rate_lock:
        wait = _last_call_monotonic + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_monotonic = time.monotonic()


# Token-per-minute gate: RPM pacing alone won't keep a burst under a provider's
# *token* budget (Groq's free tier is TPM-bound — a few requests of large prompts
# trips 429 even at a low RPM). A sliding 60s window of recently-spent tokens lets
# enrichment *complete* (slower) instead of 429-skipping. Off unless CORTEX_LLM_TPM
# is set. Process-local, same caveat as the RPM gate.
_TPM_WINDOW = 60.0
_token_lock = threading.Lock()
_token_window: deque[tuple[float, int]] = deque()  # (monotonic_ts, tokens)


def _max_tpm() -> float:
    """Token-per-minute budget from CORTEX_LLM_TPM (0 = off)."""
    raw = os.environ.get("CORTEX_LLM_TPM")
    if not raw:
        return 0.0
    try:
        tpm = float(raw)
    except ValueError:
        return 0.0
    return tpm if tpm > 0 else 0.0


def _estimate_tokens(body: dict[str, Any]) -> int:
    """Rough token cost of a request: ~4 chars/token of prompt + the output cap."""
    chars = sum(len(str(m.get("content", ""))) for m in body.get("messages", []))
    out = int(body.get("max_tokens", 0) or 0)
    return chars // 4 + out


def _pace_tokens(estimated: int) -> None:
    """Block until the 60s token window has room for `estimated` more tokens."""
    cap = _max_tpm()
    if cap <= 0:
        return
    with _token_lock:
        while True:
            now = time.monotonic()
            while _token_window and now - _token_window[0][0] >= _TPM_WINDOW:
                _token_window.popleft()
            used = sum(tok for _, tok in _token_window)
            # Admit if there's room, or if the window is empty (a single call larger
            # than the whole budget can't be split — let it through rather than hang).
            if not _token_window or used + estimated <= cap:
                _token_window.append((now, estimated))
                return
            # Wait for the oldest entry to age out of the window, then re-check.
            time.sleep(max(_TPM_WINDOW - (now - _token_window[0][0]), 0.0))


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
    est_tokens = _estimate_tokens(body)
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        wait = delay
        try:
            _pace()  # proactively stay under the provider's RPM (retries count too)
            _pace_tokens(est_tokens)  # ...and under its tokens-per-minute budget
            response = httpx.post(url, headers=headers, json=body, timeout=120.0)
            if response.status_code in _RETRY_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
                # Honor the server's Retry-After (free tiers send it on 429) so a
                # rate-limited call waits the right amount instead of burning retries.
                wait = _retry_after(response.headers, fallback=delay)
                # An exhausted *daily* quota returns 429 with a Retry-After of many
                # minutes/hours. Retrying (even capped at _MAX_BACKOFF) just 429s
                # again — so across hundreds of chunks the ingest sleeps for hours.
                # Bail now so the caller skips this chunk fast and ingest continues.
                if wait > _MAX_BACKOFF:
                    break
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
            time.sleep(min(wait, _MAX_BACKOFF))
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _retry_after(headers: Any, *, fallback: float) -> float:
    """Seconds to wait from a `Retry-After` header (delta-seconds), else fallback."""
    value = headers.get("retry-after")
    if value is None:
        return fallback
    try:
        return max(float(value), fallback)
    except (TypeError, ValueError):
        return fallback


def _retryable_error_code(error: dict[str, Any]) -> bool:
    try:
        return int(error.get("code", 0)) in _RETRY_STATUS
    except (TypeError, ValueError):
        return False
