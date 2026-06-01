"""Tests for the Sarvam Saaras v3 STT adapter."""
from __future__ import annotations

import json

import httpx
import pytest

from voice_agent.sarvam_stt import (
    DEFAULT_MODEL,
    SARVAM_STT_URL,
    SarvamSTTError,
    STTResult,
    _normalize_lang,
    _parse_stt_response,
    transcribe_batch,
)


def test_parse_response_uses_transcript_field():
    res = _parse_stt_response(
        {"transcript": "Namaste ji", "language_code": "hi-IN", "request_id": "r1"}
    )
    assert res.transcript == "Namaste ji"
    assert res.language_code == "hi-IN"
    assert res.request_id == "r1"


def test_parse_response_normalizes_bare_iso_lang():
    res = _parse_stt_response({"transcript": "hi", "language_code": "ta"})
    assert res.language_code == "ta-IN"


def test_parse_response_defaults_confidence_to_one():
    res = _parse_stt_response({"transcript": "ok", "language_code": "en-IN"})
    assert res.confidence == 1.0


def test_parse_response_falls_back_to_text_field():
    res = _parse_stt_response({"text": "hello"})
    assert res.transcript == "hello"
    assert res.language_code == "en-IN"  # default fallback


def test_normalize_lang_unknown_falls_back_to_en_in():
    assert _normalize_lang("zz") == "en-IN"


@pytest.mark.asyncio
async def test_transcribe_batch_sends_form_fields_and_parses(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers.get("api-subscription-key")
        captured["body_len"] = len(request.content)
        return httpx.Response(
            200,
            json={
                "transcript": "Aap se baat karna chahta hoon",
                "language_code": "hi-IN",
                "request_id": "req-123",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await transcribe_batch(
            audio=b"FAKE-WAV-BYTES",
            api_key="sk_test",
            client=client,
        )

    assert captured["url"] == SARVAM_STT_URL
    assert captured["header"] == "sk_test"
    assert captured["body_len"] > 0
    assert isinstance(res, STTResult)
    assert res.transcript == "Aap se baat karna chahta hoon"
    assert res.language_code == "hi-IN"


@pytest.mark.asyncio
async def test_transcribe_batch_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SarvamSTTError, match="401"):
            await transcribe_batch(
                audio=b"x", api_key="bad", client=client
            )


@pytest.mark.asyncio
async def test_transcribe_batch_rejects_empty_audio():
    with pytest.raises(SarvamSTTError, match="empty"):
        await transcribe_batch(audio=b"", api_key="sk_test")


@pytest.mark.asyncio
async def test_transcribe_batch_rejects_missing_key():
    with pytest.raises(SarvamSTTError, match="missing"):
        await transcribe_batch(audio=b"x", api_key="")


@pytest.mark.asyncio
async def test_transcribe_batch_includes_language_hint_when_passed():
    captured_data: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_data["body"] = request.content
        return httpx.Response(200, json={"transcript": "ok", "language_code": "ta-IN"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await transcribe_batch(
            audio=b"x",
            api_key="sk_test",
            language_hint="ta-IN",
            client=client,
        )

    assert b"ta-IN" in captured_data["body"]
