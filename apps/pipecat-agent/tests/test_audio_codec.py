"""Tests for the G.711 μ-law codec + WAV helpers.

We don't have a reference μ-law encoder in the test env, so we verify:
  - Round-trip PCM → μ-law → PCM stays within G.711's quantization noise.
  - WAV ↔ PCM is exact (no quantization, lossless wrapping).
  - Sample-rate handling: 8 kHz passes through, 16 kHz downsamples.
"""
from __future__ import annotations

import struct
import wave
from io import BytesIO

import pytest

from voice_agent.audio_codec import (
    mulaw_to_pcm16,
    mulaw_to_wav_for_stt,
    pcm16_to_mulaw,
    pcm16_to_wav,
    tts_wav_to_mulaw_8k,
    wav_to_pcm16,
)


def _make_pcm(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", s) for s in samples)


def _unpack_pcm(pcm: bytes) -> list[int]:
    return [struct.unpack_from("<h", pcm, i)[0] for i in range(0, len(pcm), 2)]


def test_mulaw_round_trip_preserves_signal_within_quantization():
    samples = [0, 100, -100, 1000, -1000, 5000, -5000, 16000, -16000, 32000, -32000]
    pcm = _make_pcm(samples)
    mu = pcm16_to_mulaw(pcm)
    assert len(mu) == len(samples)
    back = _unpack_pcm(mulaw_to_pcm16(mu))
    # G.711 μ-law uses log-companding; high-magnitude samples have larger
    # quantization step. Tolerate up to ~10% error or 256 absolute (whichever larger).
    for original, decoded in zip(samples, back):
        tol = max(256, abs(original) // 10)
        assert abs(original - decoded) <= tol, f"{original} -> {decoded}"


def test_mulaw_zero_round_trips_to_zero_or_near_zero():
    pcm = _make_pcm([0])
    mu = pcm16_to_mulaw(pcm)
    back = _unpack_pcm(mulaw_to_pcm16(mu))
    assert abs(back[0]) <= 256  # G.711 has no exact zero codeword.


def test_wav_round_trip_is_lossless():
    pcm = _make_pcm([100, -200, 300, -400])
    wav = pcm16_to_wav(pcm, 8000)
    out, sr = wav_to_pcm16(wav)
    assert out == pcm
    assert sr == 8000


def test_wav_to_pcm_rejects_non_mono():
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00\x00\x00")
    with pytest.raises(ValueError, match="mono"):
        wav_to_pcm16(buf.getvalue())


def test_wav_to_pcm_rejects_non_16bit():
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x00")
    with pytest.raises(ValueError, match="16-bit"):
        wav_to_pcm16(buf.getvalue())


def test_tts_wav_to_mulaw_8k_handles_8k_input():
    pcm = _make_pcm([100, 200, 300, 400])
    wav = pcm16_to_wav(pcm, 8000)
    mu = tts_wav_to_mulaw_8k(wav)
    assert len(mu) == 4  # 4 samples → 4 μ-law bytes


def test_tts_wav_to_mulaw_8k_downsamples_16k():
    pcm = _make_pcm([100, 200, 300, 400, 500, 600, 700, 800])
    wav = pcm16_to_wav(pcm, 16000)
    mu = tts_wav_to_mulaw_8k(wav)
    # 8 samples @16k → 4 samples @8k → 4 μ-law bytes.
    assert len(mu) == 4


def test_tts_wav_to_mulaw_8k_rejects_other_rates():
    pcm = _make_pcm([0])
    wav = pcm16_to_wav(pcm, 24000)
    with pytest.raises(ValueError, match="24000"):
        tts_wav_to_mulaw_8k(wav)


def test_mulaw_to_wav_for_stt_round_trips_to_audible_wav():
    mu = bytes([0x7F, 0x80, 0xFF, 0x00])  # arbitrary μ-law
    wav = mulaw_to_wav_for_stt(mu, sample_rate=8000)
    # Must be a parsable WAV with the same number of samples.
    pcm, sr = wav_to_pcm16(wav)
    assert sr == 8000
    assert len(pcm) == 8  # 4 μ-law bytes → 4 PCM samples × 2 bytes
