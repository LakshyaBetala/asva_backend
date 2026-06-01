"""Tests for the smallest.ai Lightning v3.1 TTS adapter."""
from __future__ import annotations

import json

import httpx
import pytest

from voice_agent.smallest_tts import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    SMALLEST_TTS_URL,
    SmallestTTSError,
    _ensure_wav,
    _lang_code,
    synthesize,
)


def test_lang_code_maps_indian_locales():
    assert _lang_code("hi-IN") == "hi"
    assert _lang_code("en-IN") == "en"
    assert _lang_code("ta-IN") == "ta"
    assert _lang_code("hi") == "hi"


def test_ensure_wav_passes_through_existing_wav():
    riff = b"RIFF\x00\x00\x00\x00WAVEfmt "
    assert _ensure_wav(riff, 16000) is riff


def test_ensure_wav_wraps_raw_pcm():
    pcm = b"\x01\x00\x02\x00"
    wrapped = _ensure_wav(pcm, 16000)
    assert wrapped[:4] == b"RIFF"
    assert pcm in wrapped


@pytest.mark.asyncio
async def test_synthesize_posts_correct_body_and_auth():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["accept"] = request.headers.get("accept")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"RIFF....WAVE-bytes")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await synthesize(
            text="Namaste sir", lang="hi-IN", api_key="sk_test", client=client
        )

    assert captured["url"] == SMALLEST_TTS_URL
    assert captured["auth"] == "Bearer sk_test"
    assert captured["accept"] == "audio/wav"
    assert captured["body"]["text"] == "Namaste sir"
    assert captured["body"]["voice_id"] == DEFAULT_VOICE
    assert captured["body"]["model"] == DEFAULT_MODEL
    assert captured["body"]["output_format"] == "wav"
    assert captured["body"]["language"] == "hi"
    assert res.audio == b"RIFF....WAVE-bytes"


@pytest.mark.asyncio
async def test_synthesize_omits_language_when_disabled():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await synthesize(
            text="hi", lang="hi-IN", api_key="k",
            client=client, send_language=False,
        )

    assert "language" not in captured


@pytest.mark.asyncio
async def test_synthesize_includes_speed_only_when_customized():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await synthesize(text="x", lang="hi-IN", api_key="k", client=client, speed=0.9)

    assert captured["speed"] == 0.9


@pytest.mark.asyncio
async def test_synthesize_wraps_raw_pcm_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x10\x00\x20\x00")  # not RIFF

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await synthesize(text="x", lang="hi-IN", api_key="k", client=client)

    assert res.audio[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_synthesize_empty_text_returns_empty_wav_no_call():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=b"RIFF")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await synthesize(text="   ", lang="hi-IN", api_key="k", client=client)

    assert called is False
    assert res.audio[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_synthesize_rejects_missing_key():
    with pytest.raises(SmallestTTSError, match="missing"):
        await synthesize(text="ok", lang="hi-IN", api_key="")


@pytest.mark.asyncio
async def test_synthesize_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SmallestTTSError, match="401"):
            await synthesize(text="x", lang="hi-IN", api_key="bad", client=client)
