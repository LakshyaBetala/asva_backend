"""Tests for the local audio harness.

We don't test the mic/speaker capture (needs real hardware), but we DO
test the wiring: adapters expose the right methods, WAV encoding works,
and missing creds raise clear errors.
"""
from __future__ import annotations

import wave
from io import BytesIO

import pytest

from voice_agent.local_audio import (
    SAMPLE_RATE_HZ,
    _NoOpR2,
    _build_deps,
    _GeminiAdapter,
    _SarvamSTTAdapter,
    _SarvamTTSAdapter,
    pcm_to_wav_bytes,
    wav_bytes_to_pcm,
)


def test_pcm_roundtrips_through_wav():
    pcm = b"\x00\x01" * 1000  # 1000 int16 samples
    wav = pcm_to_wav_bytes(pcm)
    out, sr = wav_bytes_to_pcm(wav)
    assert out == pcm
    assert sr == SAMPLE_RATE_HZ


def test_wav_header_is_valid():
    pcm = b"\x00\x00" * 500
    wav = pcm_to_wav_bytes(pcm)
    with wave.open(BytesIO(wav), "rb") as r:
        assert r.getnchannels() == 1
        assert r.getsampwidth() == 2
        assert r.getframerate() == SAMPLE_RATE_HZ


def test_build_deps_raises_clearly_when_sarvam_key_missing():
    import httpx

    async def _check():
        async with httpx.AsyncClient() as http:
            with pytest.raises(SystemExit, match="SARVAM_API_KEY"):
                _build_deps({}, http)

    import asyncio

    asyncio.run(_check())


def test_build_deps_raises_when_only_sarvam_set():
    import httpx

    async def _check():
        async with httpx.AsyncClient() as http:
            with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
                _build_deps({"SARVAM_API_KEY": "x"}, http)

    import asyncio

    asyncio.run(_check())


def test_build_deps_uses_noop_r2_when_r2_env_missing():
    """We log a warning and fall through — R2 is optional for local testing."""
    import httpx

    async def _check():
        async with httpx.AsyncClient() as http:
            deps = _build_deps(
                {"SARVAM_API_KEY": "x", "GEMINI_API_KEY": "y"}, http
            )
            assert isinstance(deps.r2_reader, _NoOpR2)
            assert isinstance(deps.r2_writer, _NoOpR2)

    import asyncio

    asyncio.run(_check())


@pytest.mark.asyncio
async def test_noop_r2_get_returns_none():
    r2 = _NoOpR2()
    assert await r2.get("anything") is None
    # put should not raise.
    await r2.put("k", b"v", "audio/mpeg")


def test_adapters_expose_protocol_methods():
    """The Protocol the orchestrator depends on must be satisfied."""
    import httpx

    async def _check():
        async with httpx.AsyncClient() as http:
            stt = _SarvamSTTAdapter(api_key="x", client=http)
            tts = _SarvamTTSAdapter(api_key="x", client=http)
            llm = _GeminiAdapter(api_key="x", model="gemini-2.5-flash", client=http)
            assert callable(getattr(stt, "transcribe", None))
            assert callable(getattr(tts, "synth", None))
            assert callable(getattr(llm, "respond", None))
            assert callable(getattr(llm, "extract", None))

    import asyncio

    asyncio.run(_check())
