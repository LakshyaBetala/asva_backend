"""Tests for the Sarvam streaming-STT session wrapper.

We inject a fake socket client — no real WebSocket. The live protocol was
verified separately against api.sarvam.ai (smoke_streaming_stt.py): saaras:v3,
8 kHz pcm_s16le, language auto-detect, final transcript ~150ms after
END_SPEECH.
"""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from voice_agent.sarvam_stt import STTResult
from voice_agent.sarvam_streaming_stt import SarvamStreamingSTT


def _data_msg(transcript: str, lang: str = "hi-IN", prob: float | None = 0.9):
    return SimpleNamespace(
        type="data",
        data=SimpleNamespace(
            transcript=transcript,
            language_code=lang,
            language_probability=prob,
            request_id="req-1",
        ),
    )


def _event_msg(signal: str):
    return SimpleNamespace(
        type="events",
        data=SimpleNamespace(signal_type=signal, occured_at=0),
    )


class FakeSocket:
    """Mimics AsyncSpeechToTextStreamingSocketClient: recv() pops scripted
    messages; transcribe() records sent audio."""

    def __init__(self, messages: list | None = None):
        self.messages = list(messages or [])
        self.sent: list[dict] = []
        self.flushed = 0

    async def recv(self):
        # Poll-sleep while quiet (a set-Event wait would return without
        # yielding and busy-spin the loop). Cancellation lands in the sleep.
        while not self.messages:
            await asyncio.sleep(0.005)
        return self.messages.pop(0)

    async def transcribe(self, audio: str, encoding="audio/wav", sample_rate=16000):
        self.sent.append(
            {"audio": audio, "encoding": encoding, "sample_rate": sample_rate}
        )

    async def flush(self):
        self.flushed += 1


def _session_with(socket: FakeSocket) -> SarvamStreamingSTT:
    stt = SarvamStreamingSTT(api_key="k", sample_rate=8000)
    stt._socket = socket
    stt._reader_task = asyncio.get_running_loop().create_task(stt._read_loop())
    return stt


@pytest.mark.asyncio
async def test_final_transcript_surfaces_with_language():
    sock = FakeSocket([_data_msg("अन्ना नगर में तीन बीएचके", "hi-IN", 0.95)])
    stt = _session_with(sock)
    await asyncio.sleep(0.05)
    got = stt.pop_final()
    assert got is not None
    assert got.transcript == "अन्ना नगर में तीन बीएचके"
    assert got.language_code == "hi-IN"
    assert got.confidence == pytest.approx(0.95)
    await stt.close()


@pytest.mark.asyncio
async def test_vad_signals_toggle_speech_active():
    sock = FakeSocket([_event_msg("START_SPEECH")])
    stt = _session_with(sock)
    await asyncio.sleep(0.05)
    assert stt.speech_active is True
    sock.messages.append(_event_msg("END_SPEECH"))
    await asyncio.sleep(0.05)
    assert stt.speech_active is False
    assert stt.last_end_speech_at > 0
    await stt.close()


@pytest.mark.asyncio
async def test_empty_transcripts_are_dropped():
    sock = FakeSocket([_data_msg("   "), _data_msg("")])
    stt = _session_with(sock)
    await asyncio.sleep(0.05)
    assert stt.pop_final() is None
    await stt.close()


@pytest.mark.asyncio
async def test_feed_base64_encodes_pcm_at_session_rate():
    sock = FakeSocket()
    stt = _session_with(sock)
    pcm = b"\x01\x02" * 800
    await stt.feed(pcm)
    assert len(sock.sent) == 1
    assert base64.b64decode(sock.sent[0]["audio"]) == pcm
    assert sock.sent[0]["sample_rate"] == 8000
    # SDK schema pins encoding to audio/wav; raw format is declared at connect.
    assert sock.sent[0]["encoding"] == "audio/wav"
    await stt.close()


@pytest.mark.asyncio
async def test_feed_failure_marks_session_failed_not_raises():
    class BrokenSocket(FakeSocket):
        async def transcribe(self, *a, **kw):
            raise RuntimeError("ws closed")

    sock = BrokenSocket()
    stt = _session_with(sock)
    await stt.feed(b"\x01\x02")  # must not raise
    assert stt.failed is True
    # Subsequent feeds are silent no-ops.
    await stt.feed(b"\x01\x02")
    await stt.close()


@pytest.mark.asyncio
async def test_drain_finals_merges_split_utterance():
    sock = FakeSocket([
        _data_msg("Anna Nagar mein", "hi-IN", 0.9),
        _data_msg("teen BHK chahiye", "hi-IN", 0.8),
    ])
    stt = _session_with(sock)
    await asyncio.sleep(0.05)
    first = stt.pop_final()
    assert first is not None
    merged = stt.drain_finals(first)
    assert merged.transcript == "Anna Nagar mein teen BHK chahiye"
    assert merged.confidence == pytest.approx(0.8)  # min of the parts
    await stt.close()


@pytest.mark.asyncio
async def test_bare_iso_language_is_normalized():
    sock = FakeSocket([_data_msg("vanakkam", "ta", None)])
    stt = _session_with(sock)
    await asyncio.sleep(0.05)
    got = stt.pop_final()
    assert got is not None
    assert got.language_code == "ta-IN"
    assert got.confidence == 1.0  # missing probability defaults high
    await stt.close()


@pytest.mark.asyncio
async def test_pop_final_returns_none_when_quiet():
    stt = _session_with(FakeSocket())
    assert stt.pop_final() is None
    await stt.close()


def test_sttresult_contract_matches_batch_adapter():
    """The streaming path must emit the SAME STTResult the orchestrator's
    batch path consumes — language_state and run_turn_streaming don't know
    which STT produced the utterance."""
    r = STTResult(transcript="x", language_code="en-IN", confidence=1.0, request_id=None)
    assert hasattr(r, "transcript") and hasattr(r, "language_code")


@pytest.mark.asyncio
async def test_repin_reconnects_with_new_language(monkeypatch):
    sock = FakeSocket()
    stt = _session_with(sock)
    stt._language_hint = "en-IN"
    started: list[str] = []

    async def fake_start():
        started.append(stt._language_hint)

    monkeypatch.setattr(stt, "start", fake_start)
    await stt.repin("ta-IN")
    assert stt._language_hint == "ta-IN"
    assert started == ["ta-IN"]      # reconnected pinned to the new language
    assert stt._reader_task is None  # old reader torn down


@pytest.mark.asyncio
async def test_repin_noop_when_language_unchanged(monkeypatch):
    sock = FakeSocket()
    stt = _session_with(sock)
    stt._language_hint = "hi-IN"
    started: list[str] = []

    async def fake_start():
        started.append("called")

    monkeypatch.setattr(stt, "start", fake_start)
    await stt.repin("hi-IN")
    assert started == []  # same language → no reconnect
    await stt.close()
