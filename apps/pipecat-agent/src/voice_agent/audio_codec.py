"""Telephony audio codec + WAV stripping helpers.

Two transports, two on-the-wire formats:

  - Plivo (legacy): 8 kHz μ-law / G.711. See pcm16_to_mulaw / mulaw_to_pcm16.
  - Exotel AgentStream (current): raw 16-bit PCM (slin), configurable sample
    rate (8 kHz default). NOT μ-law. See the exotel_* / pcm16_resample helpers.

Per turn on Exotel:

  Lead → Exotel (raw PCM @ stream rate) → us → WAV → Sarvam STT
  Cartesia/Sarvam TTS (WAV @ 16 kHz) → us → resample → raw PCM @ stream rate → Exotel → Lead

This module owns the conversion. Stdlib only — no audioop in 3.13+ so we
ship a tiny pure-Python implementation. Performance is fine for one
call's worth of mono audio.
"""
from __future__ import annotations

import array
import io
import struct
import wave

MU_LAW_BIAS = 0x84
MU_LAW_CLIP = 32635

# G.711 μ-law segment end-points (after BIAS add). Standard table.
_SEG_END = (0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF)


def pcm16_to_mulaw(pcm: bytes) -> bytes:
    """Convert signed-16 PCM bytes (little-endian) to G.711 μ-law bytes.

    1 PCM sample (2 bytes) → 1 μ-law byte. Spec: ITU-T G.711.
    """
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm) - 1, 2):
        sample = struct.unpack_from("<h", pcm, i)[0]
        if sample < 0:
            sample = -sample
            sign = 0x80
        else:
            sign = 0
        if sample > MU_LAW_CLIP:
            sample = MU_LAW_CLIP
        sample = sample + MU_LAW_BIAS
        # Find segment by table lookup (G.711 standard).
        seg = 7
        for idx, end in enumerate(_SEG_END):
            if sample <= end:
                seg = idx
                break
        mantissa = (sample >> (seg + 3)) & 0x0F
        byte = ~(sign | (seg << 4) | mantissa) & 0xFF
        out[i // 2] = byte
    return bytes(out)


def mulaw_to_pcm16(mu_law: bytes) -> bytes:
    """Convert G.711 μ-law bytes to signed-16 PCM bytes (little-endian).

    1 μ-law byte → 1 PCM sample (2 bytes).
    """
    out = bytearray(len(mu_law) * 2)
    for i, b in enumerate(mu_law):
        b = ~b & 0xFF
        sign = b & 0x80
        seg = (b & 0x70) >> 4
        mantissa = b & 0x0F
        sample = ((mantissa << 3) + MU_LAW_BIAS) << seg
        sample = sample - MU_LAW_BIAS
        if sign:
            sample = -sample
        struct.pack_into("<h", out, i * 2, sample)
    return bytes(out)


def wav_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    """Strip WAV header. Returns (raw PCM bytes, sample rate)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as r:
        if r.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit PCM")
        if r.getnchannels() != 1:
            raise ValueError("WAV must be mono")
        return r.readframes(r.getnframes()), r.getframerate()


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap PCM in a WAV container for Sarvam STT."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def tts_wav_to_mulaw_8k(wav_bytes: bytes) -> bytes:
    """End-to-end: Sarvam TTS WAV → μ-law ready to send to Exotel.

    Sarvam returns 8 kHz mono PCM-WAV when we request speech_sample_rate=8000.
    If Sarvam ever returns 16 kHz we naive-downsample by dropping every
    other sample — adequate for telephony, but log this so we can move
    to a real resampler later.
    """
    pcm, sr = wav_to_pcm16(wav_bytes)
    if sr == 8000:
        return pcm16_to_mulaw(pcm)
    if sr == 16000:
        # Naive 2:1 downsample. Sufficient for PSTN 8 kHz; quality loss
        # is below telephony codec floor anyway.
        downsampled = bytearray(len(pcm) // 2)
        for i in range(0, len(pcm) - 3, 4):
            downsampled[i // 2] = pcm[i]
            downsampled[i // 2 + 1] = pcm[i + 1]
        return pcm16_to_mulaw(bytes(downsampled))
    raise ValueError(f"unsupported TTS sample rate: {sr} (expected 8000 or 16000)")


def mulaw_to_wav_for_stt(mu_law: bytes, sample_rate: int = 8000) -> bytes:
    """End-to-end: Plivo μ-law chunk → WAV ready to send to Sarvam STT."""
    pcm = mulaw_to_pcm16(mu_law)
    return pcm16_to_wav(pcm, sample_rate)


# -- Exotel AgentStream: raw 16-bit PCM (slin) -----------------------------

def pcm16_resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample mono signed-16 little-endian PCM via linear interpolation.

    Used to bridge Cartesia's 16 kHz TTS output to Exotel's stream rate
    (8 kHz by default) and vice-versa. Linear interp is plenty for
    telephony-band speech and avoids a numpy/scipy dependency.
    """
    if src_rate == dst_rate or not pcm:
        return pcm
    src = array.array("h")
    src.frombytes(pcm[: len(pcm) // 2 * 2])  # drop a trailing odd byte if any
    n_src = len(src)
    if n_src == 0:
        return b""
    n_dst = max(1, round(n_src * dst_rate / src_rate))
    dst = array.array("h", bytes(2 * n_dst))
    if n_dst == 1:
        dst[0] = src[0]
        return dst.tobytes()
    ratio = (n_src - 1) / (n_dst - 1)
    for i in range(n_dst):
        pos = i * ratio
        idx = int(pos)
        frac = pos - idx
        s0 = src[idx]
        s1 = src[idx + 1] if idx + 1 < n_src else s0
        dst[i] = int(s0 + (s1 - s0) * frac)
    return dst.tobytes()


def exotel_pcm_to_wav_for_stt(pcm: bytes, sample_rate: int) -> bytes:
    """Exotel inbound raw PCM chunk → WAV ready for Sarvam STT.

    Exotel hands us raw 16-bit mono PCM at the stream's configured rate;
    Sarvam STT just needs it in a WAV container (it resamples internally).
    """
    return pcm16_to_wav(pcm, sample_rate)


def apply_gain(pcm: bytes, gain: float) -> bytes:
    """Scale signed-16 PCM by `gain` with hard clipping at ±full-scale.

    smallest.ai (and most TTS) output sits well below telephony full-scale, so
    Priya can sound faint on a phone earpiece. A gain of ~1.4-1.8x lifts her to
    a comfortable level; beyond ~2x risks clipping distortion.
    """
    if gain == 1.0 or not pcm:
        return pcm
    arr = array.array("h")
    arr.frombytes(pcm[: len(pcm) // 2 * 2])
    for i in range(len(arr)):
        v = int(arr[i] * gain)
        arr[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return arr.tobytes()


def tts_wav_to_exotel_pcm(
    wav_bytes: bytes, target_rate: int, gain: float = 1.0, lead_silence_ms: int = 0,
) -> bytes:
    """TTS WAV (Cartesia 16 kHz or Sarvam 8/16 kHz) → raw PCM at Exotel's rate.

    Returns headerless signed-16 little-endian PCM, resampled to
    `target_rate` (the rate the Voicebot applet is configured for), optionally
    amplified by `gain` so Priya isn't faint on the phone.

    `lead_silence_ms` prepends silent PCM so the cellular channel has time to
    stabilize before the first syllable. Without this, the start of words like
    "Vanakkam" can clip on connection setup. ~30-60ms is imperceptible to the
    listener but recovers the lost articulation.
    """
    pcm, sr = wav_to_pcm16(wav_bytes)
    resampled = pcm16_resample(pcm, sr, target_rate)
    amplified = apply_gain(resampled, gain)
    if lead_silence_ms > 0:
        pad_samples = int(target_rate * lead_silence_ms / 1000)
        return bytes(pad_samples * 2) + amplified
    return amplified
