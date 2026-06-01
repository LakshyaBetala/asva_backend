"""Google Gemini 2.5 Flash adapter.

Two uses inside the pipeline:

  1. Conversational response — Priya's next sentence given the running
     transcript + system prompt. Streamed token-by-token so TTS can
     start before generation finishes (cuts ~400ms off perceived latency).
  2. Slot extractor — non-streaming, JSON-only output, runs in parallel
     with the response call (see qualification.extract_slots). The
     extractor is a single-shot call so we await it after the turn.

We talk to the REST API via httpx instead of google-generativeai's SDK
because the SDK pulls in a heavy gRPC dependency tree that breaks the
Pipecat dev container. The REST surface is also easier to mock.

Endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent
       ?key=<GEMINI_API_KEY>

Streaming variant:
  POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:streamGenerateContent
       ?key=<GEMINI_API_KEY>&alt=sse
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Telephony tuning: short, conversational replies. We do NOT want
# essays here — Priya speaks in 1-2 sentence beats. 500 tokens fits
# ~2-3 Hindi/Tamil sentences (Indic scripts cost ~2 tokens/syllable);
# 200 was too tight and truncated mid-sentence.
DEFAULT_GENERATION_CONFIG: dict[str, Any] = {
    "temperature": 0.7,
    "topP": 0.9,
    "maxOutputTokens": 1000,  # Safety ceiling. Brevity is enforced by prompt.
    "stopSequences": [],
}


@dataclass(frozen=True)
class GeminiResponse:
    text: str
    finish_reason: str | None
    prompt_tokens: int
    output_tokens: int


class GeminiError(RuntimeError):
    """Raised for non-2xx or malformed responses."""


def _build_payload(
    *,
    system_message: str,
    user_message: str,
    generation_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**DEFAULT_GENERATION_CONFIG, **(generation_config or {})}
    return {
        "systemInstruction": {"parts": [{"text": system_message}]},
        "contents": [
            {"role": "user", "parts": [{"text": user_message}]},
        ],
        "generationConfig": cfg,
    }


async def generate(
    *,
    system_message: str,
    user_message: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    generation_config: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> GeminiResponse:
    """Single-shot generation. Use this for the slot extractor."""
    if not api_key:
        raise GeminiError("missing GEMINI_API_KEY")

    url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
    body = _build_payload(
        system_message=system_message,
        user_message=user_message,
        generation_config=generation_config,
    )

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            url, json=body, headers={"content-type": "application/json"}, timeout=timeout
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise GeminiError(f"Gemini {resp.status_code}: {resp.text[:300]}")

    try:
        payload = resp.json()
    except Exception as exc:
        raise GeminiError(f"non-JSON Gemini response: {exc}") from exc

    return _parse_response(payload)


def _parse_response(payload: dict[str, Any]) -> GeminiResponse:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError(f"no candidates in Gemini response: {payload.get('promptFeedback')}")

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()

    usage = payload.get("usageMetadata") or {}
    return GeminiResponse(
        text=text,
        finish_reason=candidate.get("finishReason"),
        prompt_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
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
    """Yield text chunks as Gemini streams them.

    Pipecat consumes these and feeds them to Sarvam TTS sentence-by-sentence
    so the first audio frame arrives ~400ms before generation finishes.
    """
    if not api_key:
        raise GeminiError("missing GEMINI_API_KEY")

    url = f"{GEMINI_BASE}/{model}:streamGenerateContent?key={api_key}&alt=sse"
    body = _build_payload(
        system_message=system_message,
        user_message=user_message,
        generation_config=generation_config,
    )

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        async with http.stream(
            "POST",
            url,
            json=body,
            headers={"content-type": "application/json"},
            timeout=timeout,
        ) as resp:
            if resp.status_code >= 400:
                detail = await resp.aread()
                raise GeminiError(f"Gemini stream {resp.status_code}: {detail[:300]!r}")
            async for line in resp.aiter_lines():
                chunk = _parse_sse_line(line)
                if chunk:
                    yield chunk
    finally:
        if owns_client:
            await http.aclose()


def _parse_sse_line(line: str) -> str | None:
    """SSE format: 'data: <json>'. Return the text inside, or None."""
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload_str = line[len("data:"):].strip()
    if payload_str == "[DONE]":
        return None
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return None

    candidates = payload.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    return text or None


def make_llm_for_slot_extractor(*, api_key: str, model: str = DEFAULT_MODEL):
    """Bind credentials so qualification.extract_slots can call llm(prompt).

    Returns an async (prompt) -> str closure matching qualification.LlmCall.
    The slot extractor passes the full instructions as the user_message and
    an empty system message — the instructions already include all rules.
    """
    async def _call(prompt: str) -> str:
        resp = await generate(
            system_message="You are a JSON extraction engine. Output ONLY valid JSON.",
            user_message=prompt,
            api_key=api_key,
            model=model,
            # Lower temperature for extraction = more stable JSON.
            generation_config={"temperature": 0.1, "maxOutputTokens": 600},
        )
        return resp.text

    return _call
