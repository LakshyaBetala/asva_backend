"""ElevenLabs TTS adapter — hyper-realistic multilingual voice.

Used as a drop-in for cartesia_tts when ELEVENLABS_API_KEY is set. ElevenLabs
sounds markedly more human on Hindi/Hinglish and pronounces embedded English
business terms cleanly, which is exactly the client feedback we're fixing.

A single voice_id speaks Hindi, Tamil AND English — the model + language_code
drive the language, so language switching keeps the same voice identity.

We request raw 16-bit PCM (pcm_16000) and wrap it in a WAV header so the
return shape matches the Cartesia/Sarvam adapters. NOTE: PCM output requires
a paid ElevenLabs tier; on free tiers the API rejects pcm_* formats.
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import httpx

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Flash v2.5: low latency (~75ms), 32 languages incl. Hindi/Tamil, accepts
# language_code. Override with ELEVENLABS_MODEL=eleven_multilingual_v2 for
# slightly higher quality at higher latency.
DEFAULT_MODEL = "eleven_flash_v2_5"
# Fallback voice (Sarah). Override with a real Indian Hindi female voice from
# the ElevenLabs Voice Library via ELEVENLABS_VOICE_ID for best results.
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_TIMEOUT_SECONDS = 15.0


class ElevenLabsTTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    audio: bytes
    sample_rate: int = DEFAULT_SAMPLE_RATE


def _pcm_to_wav(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _lang_code(lang: str) -> str:
    mapping = {"hi-IN": "hi", "en-IN": "en", "ta-IN": "ta"}
    return mapping.get(lang, lang.split("-")[0] if "-" in lang else lang)


async def synthesize(
    *,
    text: str,
    lang: str = "hi-IN",
    api_key: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model: str = DEFAULT_MODEL,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    stability: float = 0.45,
    similarity_boost: float = 0.8,
    style: float = 0.25,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TTSResult:
    if not api_key:
        raise ElevenLabsTTSError("missing ELEVENLABS_API_KEY")
    if not text.strip():
        return TTSResult(audio=_pcm_to_wav(b"", sample_rate), sample_rate=sample_rate)

    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    body = {
        "text": text,
        "model_id": model,
        "language_code": _lang_code(lang),
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    params = {"output_format": f"pcm_{sample_rate}"}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            url, json=body, headers=headers, params=params, timeout=timeout
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise ElevenLabsTTSError(f"ElevenLabs {resp.status_code}: {resp.text[:300]}")

    return TTSResult(audio=_pcm_to_wav(resp.content, sample_rate), sample_rate=sample_rate)
