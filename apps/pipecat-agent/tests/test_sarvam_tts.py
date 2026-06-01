"""Tests for the Sarvam Bulbul v3 TTS adapter."""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from voice_agent.sarvam_tts import (
    BULBUL_V3_FEMALE_SPEAKERS,
    BULBUL_V3_MALE_SPEAKERS,
    BULBUL_V3_SPEAKERS,
    DEFAULT_FEMALE_SPEAKER,
    DEFAULT_MALE_SPEAKER,
    DEFAULT_MODEL,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SPEAKER,
    SARVAM_TTS_URL,
    SarvamTTSError,
    _extract_audio,
    is_valid_v3_speaker,
    make_phrase_synthesizer,
    synthesize,
)


def test_default_speaker_is_a_valid_v3_speaker():
    """Regression: anushka was a v2 speaker; v3 rejects it with HTTP 400."""
    assert DEFAULT_SPEAKER in BULBUL_V3_SPEAKERS
    assert DEFAULT_FEMALE_SPEAKER in BULBUL_V3_FEMALE_SPEAKERS
    assert DEFAULT_MALE_SPEAKER in BULBUL_V3_MALE_SPEAKERS


def test_is_valid_v3_speaker_rejects_legacy_v2_names():
    assert is_valid_v3_speaker("priya") is True
    assert is_valid_v3_speaker("rahul") is True
    assert is_valid_v3_speaker("anushka") is False  # v2 only
    assert is_valid_v3_speaker("meera") is False    # v2 only
    assert is_valid_v3_speaker("nonsense") is False


def test_female_and_male_rosters_are_disjoint():
    """A speaker should be in exactly one of female/male, never both."""
    assert BULBUL_V3_FEMALE_SPEAKERS & BULBUL_V3_MALE_SPEAKERS == frozenset()


def test_extract_audio_handles_list_form():
    encoded = base64.b64encode(b"WAV-DATA").decode()
    assert _extract_audio({"audios": [encoded]}) == b"WAV-DATA"


def test_extract_audio_handles_string_form():
    encoded = base64.b64encode(b"WAV-DATA").decode()
    assert _extract_audio({"audios": encoded}) == b"WAV-DATA"


def test_extract_audio_rejects_empty_list():
    with pytest.raises(SarvamTTSError, match="empty"):
        _extract_audio({"audios": []})


def test_extract_audio_rejects_bad_base64():
    with pytest.raises(SarvamTTSError, match="b64"):
        _extract_audio({"audios": ["%%not-base64%%"]})


@pytest.mark.asyncio
async def test_synthesize_posts_correct_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers.get("api-subscription-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"audios": [base64.b64encode(b"WAV").decode()], "request_id": "r1"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await synthesize(
            text="Haan ji",
            lang="hi-IN",
            api_key="sk_test",
            client=client,
        )

    assert captured["url"] == SARVAM_TTS_URL
    assert captured["header"] == "sk_test"
    assert captured["body"]["target_language_code"] == "hi-IN"
    assert captured["body"]["speaker"] == DEFAULT_SPEAKER
    assert captured["body"]["model"] == DEFAULT_MODEL
    assert captured["body"]["speech_sample_rate"] == DEFAULT_SAMPLE_RATE
    assert captured["body"]["inputs"] == ["Haan ji"]
    assert res.audio == b"WAV"
    assert res.request_id == "r1"


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_text():
    with pytest.raises(SarvamTTSError, match="empty"):
        await synthesize(text="   ", lang="hi-IN", api_key="sk")


@pytest.mark.asyncio
async def test_synthesize_rejects_missing_key():
    with pytest.raises(SarvamTTSError, match="missing"):
        await synthesize(text="ok", lang="hi-IN", api_key="")


@pytest.mark.asyncio
async def test_synthesize_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SarvamTTSError, match="429"):
            await synthesize(text="x", lang="hi-IN", api_key="sk", client=client)


@pytest.mark.asyncio
async def test_synthesize_omits_pitch_loudness_for_bulbul_v3():
    """Bulbul v3 rejects pitch/loudness with HTTP 400. Regression guard."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, json={"audios": [base64.b64encode(b"x").decode()]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await synthesize(
            text="haan", lang="hi-IN", api_key="k",
            client=client, model="bulbul:v3",
        )

    assert "pitch" not in captured
    assert "loudness" not in captured
    # pace at default also omitted (we only send if customized).
    assert "pace" not in captured


@pytest.mark.asyncio
async def test_synthesize_includes_pace_when_customized_for_v3():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, json={"audios": [base64.b64encode(b"x").decode()]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await synthesize(
            text="haan", lang="hi-IN", api_key="k",
            client=client, model="bulbul:v3", pace=0.9,
        )

    assert captured["pace"] == 0.9
    assert "pitch" not in captured


@pytest.mark.asyncio
async def test_phrase_synthesizer_returns_bytes_and_matches_protocol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"audios": [base64.b64encode(b"OK").decode()]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        synth = make_phrase_synthesizer(api_key="sk_test", client=client)
        out = await synth("Achha", "hi-IN")
    assert out == b"OK"
