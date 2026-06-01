"""smallest.ai Lightning v3.1 TTS adapter — India-native, telephony-tuned.

Lightning v3.1 renders Hindi, English and Tamil from a single voice identity
with native code-mixing (Hinglish / Tanglish) and ~200ms TTFB. It is the
default Priya voice because it pronounces embedded English business terms
cleanly inside Hindi — the exact client complaint we're fixing — and keeps
one consistent speaker across all three languages.

Drop-in for cartesia_tts / elevenlabs_tts when SMALLEST_API_KEY is set.
Returns a WAV container so the return shape matches the other adapters.

Endpoint / model / voice / sample-rate are env-overridable so a minor API
drift never needs a code change:
  SMALLEST_TTS_URL, SMALLEST_MODEL, SMALLEST_VOICE, SMALLEST_SAMPLE_RATE
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import httpx

SMALLEST_TTS_URL = "https://api.smallest.ai/waves/v1/tts"
DEFAULT_MODEL = "lightning_v3.1_pro"
# Indian female voice. Override with SMALLEST_VOICE once the team A/Bs the
# voice library and picks Priya's exact voice.
DEFAULT_VOICE = "meher"
# 16 kHz source → clean 2:1 downsample to Exotel's 8 kHz telephony stream
# (avoids the aliasing a 24k→8k drop would add). Override per stream rate.
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_TIMEOUT_SECONDS = 15.0


class SmallestTTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    audio: bytes
    sample_rate: int = DEFAULT_SAMPLE_RATE


def _lang_code(lang: str) -> str:
    mapping = {"hi-IN": "hi", "en-IN": "en", "ta-IN": "ta"}
    return mapping.get(lang, lang.split("-")[0] if "-" in lang else lang)


def _ensure_wav(audio: bytes, sample_rate: int) -> bytes:
    """smallest.ai returns WAV when output_format=wav. If a deployment ever
    hands back raw PCM, wrap it so downstream wav_to_pcm16 still works."""
    if audio[:4] == b"RIFF":
        return audio
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio)
    return buf.getvalue()


async def synthesize(
    *,
    text: str,
    lang: str = "hi-IN",
    api_key: str,
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    speed: float = 1.0,
    url: str = SMALLEST_TTS_URL,
    send_language: bool = True,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TTSResult:
    if not api_key:
        raise SmallestTTSError("missing SMALLEST_API_KEY")
    if not text.strip():
        return TTSResult(audio=_ensure_wav(b"", sample_rate), sample_rate=sample_rate)

    body: dict = {
        "text": text,
        "voice_id": voice,
        "model": model,
        "sample_rate": sample_rate,
        "output_format": "wav",
    }
    if speed != 1.0:
        body["speed"] = speed
    # Lightning v3.1 auto-detects language, but passing the per-turn language
    # keeps pronunciation locked when our state machine has already decided.
    if send_language:
        body["language"] = _lang_code(lang)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/wav",
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(url, json=body, headers=headers, timeout=timeout)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise SmallestTTSError(f"smallest.ai {resp.status_code}: {resp.text[:300]}")

    return TTSResult(
        audio=_ensure_wav(resp.content, sample_rate), sample_rate=sample_rate
    )
