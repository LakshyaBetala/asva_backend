"""Tests for the Bulbul v3 streaming TTS adapter (no network)."""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from voice_agent.audio_codec import wav_to_pcm16
from voice_agent.sarvam_tts import TTSResult
from voice_agent.sarvam_tts_ws import (
    SarvamStreamingTTS,
    _looks_like_riff_preamble,
    pcm16_to_wav,
)


def test_pcm16_to_wav_roundtrip():
    pcm = bytes(range(256)) * 4
    wav = pcm16_to_wav(pcm, 8000)
    assert wav[:4] == b"RIFF"
    out, rate = wav_to_pcm16(wav)
    assert rate == 8000
    assert out == pcm


def test_riff_preamble_detection():
    assert _looks_like_riff_preamble(b"RIFF\xff\xff\xff\xffWAVE" + bytes(34))
    assert not _looks_like_riff_preamble(bytes(2200))  # real PCM chunk
    assert not _looks_like_riff_preamble(b"RIFF" + bytes(4000))  # full WAV


class _EventResponse:
    """Type name matters: the adapter ends a sentence on *Event* messages."""


class _FakeWS:
    def __init__(self, audio_chunks: list[bytes]):
        self.configured: list[dict] = []
        self.converted: list[str] = []
        self.flushed = 0
        self._queue: list[object] = [
            SimpleNamespace(data=SimpleNamespace(audio=base64.b64encode(c).decode()))
            for c in audio_chunks
        ] + [_EventResponse()]

    async def configure(self, **kwargs):
        self.configured.append(kwargs)

    async def convert(self, text):
        self.converted.append(text)

    async def flush(self):
        self.flushed += 1

    async def recv(self):
        return self._queue.pop(0)


def _collect(gen):
    async def run():
        return [c async for c in gen]
    return asyncio.run(run())


def test_synth_stream_skips_preamble_and_yields_pcm():
    preamble = b"RIFF\xff\xff\xff\xffWAVE" + bytes(34)
    chunks = [preamble, b"\x01\x02" * 100, b"\x03\x04" * 100]
    tts = SarvamStreamingTTS(api_key="k", speaker="priya", sample_rate=8000)
    fake = _FakeWS(chunks)
    tts._ws = fake

    out = _collect(tts.synth_stream("Sollunga sir?", "ta-IN"))
    assert out == [b"\x01\x02" * 100, b"\x03\x04" * 100]
    assert fake.converted == ["Sollunga sir?"]
    assert fake.flushed == 1
    assert fake.configured[0]["target_language_code"] == "ta-IN"
    assert fake.configured[0]["speech_sample_rate"] == 8000


def test_configure_only_on_language_change():
    tts = SarvamStreamingTTS(api_key="k", speaker="priya", sample_rate=8000)
    fake = _FakeWS([b"\x00\x00" * 50])
    tts._ws = fake
    _collect(tts.synth_stream("one", "ta-IN"))

    fake2 = _FakeWS([b"\x00\x00" * 50])
    fake2.configured = fake.configured  # share the log
    tts._ws = fake2
    _collect(tts.synth_stream("two", "ta-IN"))
    assert len(fake.configured) == 1  # same language → no reconfigure

    fake3 = _FakeWS([b"\x00\x00" * 50])
    fake3.configured = fake.configured
    tts._ws = fake3
    _collect(tts.synth_stream("three", "en-IN"))
    assert len(fake.configured) == 2  # language change → reconfigure


def test_ws_failure_degrades_to_rest(monkeypatch):
    tts = SarvamStreamingTTS(api_key="k", speaker="priya", sample_rate=8000)

    async def boom(self):
        raise ConnectionError("socket died")

    monkeypatch.setattr(SarvamStreamingTTS, "_ensure_ws", boom)

    pcm = b"\x05\x06" * 200
    async def fake_rest(**kwargs):
        return TTSResult(audio=pcm16_to_wav(pcm, 8000), request_id="r")

    monkeypatch.setattr("voice_agent.sarvam_tts_ws.rest_synthesize", fake_rest)

    out = _collect(tts.synth_stream("Sorry sir?", "hi-IN"))
    assert out == [pcm]  # WAV stripped back to raw PCM


def test_synth_assembles_full_wav():
    tts = SarvamStreamingTTS(api_key="k", speaker="priya", sample_rate=8000)
    tts._ws = _FakeWS([b"\x01\x02" * 100, b"\x03\x04" * 100])

    async def run():
        return await tts.synth("Ji, boliye?", "hi-IN")

    wav = asyncio.run(run())
    pcm, rate = wav_to_pcm16(wav)
    assert rate == 8000
    assert pcm == b"\x01\x02" * 100 + b"\x03\x04" * 100


def test_empty_text_yields_nothing():
    tts = SarvamStreamingTTS(api_key="k", speaker="priya", sample_rate=8000)
    assert _collect(tts.synth_stream("   ", "hi-IN")) == []
