"""Groq LLM adapter — OpenAI-compatible API with ~200ms first-token latency.

Groq runs Llama 3.3 70B on custom LPU hardware at ~800 tokens/sec,
roughly 5-8x faster than Gemini 2.5 Flash. The API is OpenAI-compatible
so the adapter is simpler than the Gemini one.

Used as a drop-in replacement for gemini_llm when GROQ_API_KEY is set.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TIMEOUT_SECONDS = 30.0

# max_tokens kept tight: a real cold-call agent never monologues. ~120 tokens
# is 1-2 punchy Hinglish/Tanglish sentences — enough to answer, short enough to
# stay human. (Slot-extraction calls override this via generation_config.)
DEFAULT_GENERATION_CONFIG: dict[str, Any] = {
    "max_tokens": 120,
    "temperature": 0.7,
    "top_p": 0.9,
}


class GroqError(RuntimeError):
    pass


@dataclass
class GroqResponse:
    text: str
    model: str
    prompt_tokens: int
    output_tokens: int


async def generate(
    *,
    system_message: str,
    user_message: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    generation_config: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> GroqResponse:
    if not api_key:
        raise GroqError("missing GROQ_API_KEY")

    cfg = {**DEFAULT_GENERATION_CONFIG, **(generation_config or {})}
    url = f"{GROQ_BASE}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        **cfg,
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise GroqError(f"Groq {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})
    return GroqResponse(
        text=choice["message"]["content"],
        model=data.get("model", model),
        prompt_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )


async def stream_generate(
    *,
    system_message: str,
    user_message: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    generation_config: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AsyncIterator[str]:
    if not api_key:
        raise GroqError("missing GROQ_API_KEY")

    cfg = {**DEFAULT_GENERATION_CONFIG, **(generation_config or {})}
    url = f"{GROQ_BASE}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        **cfg,
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        async with http.stream(
            "POST",
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        ) as resp:
            if resp.status_code >= 400:
                detail = await resp.aread()
                raise GroqError(f"Groq stream {resp.status_code}: {detail[:300]!r}")
            async for line in resp.aiter_lines():
                chunk = _parse_sse_line(line)
                if chunk:
                    yield chunk
    finally:
        if owns_client:
            await http.aclose()


def _parse_sse_line(line: str) -> str | None:
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload_str = line[len("data:"):].strip()
    if payload_str == "[DONE]":
        return None
    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        return None
    choices = data.get("choices", [])
    if not choices:
        return None
    delta = choices[0].get("delta", {})
    return delta.get("content")
