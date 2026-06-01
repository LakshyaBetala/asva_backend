"""Cartesia Sonic TTS adapter — ultra-low latency streaming TTS.

Cartesia Sonic-3.5 delivers <100ms latency with streaming, compared to
Sarvam Bulbul v3's 2-5s batch latency. Supports Hindi natively with
dedicated Hinglish voices.

Used as a drop-in replacement for sarvam_tts when CARTESIA_API_KEY is set.
"""
from __future__ import annotations

import base64
import io
import json
import struct
import wave
from dataclasses import dataclass
from typing import Any

import httpx

CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_SSE_URL = "https://api.cartesia.ai/tts/sse"
CARTESIA_VERSION = "2026-03-01"
DEFAULT_MODEL = "sonic-3.5"
DEFAULT_TIMEOUT_SECONDS = 15.0

VOICES = {
    "arushi": "95d51f79-c397-46f9-b49a-23763d3eaa2d",
    "riya": "faf0731e-dfb9-4cfc-8119-259a79b27e12",
    "meera": "a81fccdc-5595-4dfc-ae76-4de6a515b8a2",
    "parvati": "bec003e2-3cb3-429c-8468-206a393c67ad",
    "sneha": "6b02ffe5-e3cb-48c0-a023-c72f85953375",
    "nisha": "0f14d8cb-f039-41fe-a813-a9b4bee7eed8",
    "rohan": "4877b818-c7fe-4c89-b1cf-eadf8e23da72",
    "dev": "910fb75e-1d20-4840-ac63-ac6b26a71bdc",
    "vishal": "098fb15d-2597-4186-8b74-25340050b6e7",
    "ayush": "791d5162-d5eb-40f0-8189-f19db44611d8",
    "nithya": "80e4e2b3-ec54-4930-97ac-667eba950352",
    "anitha": "d4470f50-295e-4e11-82a2-158d45bf6abc",
    "kavitha": "01d7796d-ac10-4ea3-8df0-3cc04f2d25ff",
    "katie": "f786b574-daa5-4673-aa0c-cbe3e8534c02",
}

HINDI_VOICES = VOICES

LANG_DEFAULT_VOICE: dict[str, str] = {
    "hi-IN": "arushi",
    "hi": "arushi",
    "ta-IN": "nithya",
    "ta": "nithya",
    "en-IN": "katie",
    "en": "katie",
}

DEFAULT_VOICE = "arushi"
DEFAULT_SAMPLE_RATE = 16000


class CartesiaTTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    audio: bytes
    sample_rate: int = DEFAULT_SAMPLE_RATE


def _pcm_to_wav(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
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
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TTSResult:
    if not api_key:
        raise CartesiaTTSError("missing CARTESIA_API_KEY")

    if voice == DEFAULT_VOICE:
        lang_voice = LANG_DEFAULT_VOICE.get(lang, LANG_DEFAULT_VOICE.get(_lang_code(lang), DEFAULT_VOICE))
        voice_id = VOICES.get(lang_voice, VOICES.get(voice, voice))
    else:
        voice_id = VOICES.get(voice, voice)

    body = {
        "model_id": model,
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": sample_rate,
        },
        "language": _lang_code(lang),
    }

    headers = {
        "X-API-Key": api_key,
        "Cartesia-Version": CARTESIA_VERSION,
        "Content-Type": "application/json",
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            CARTESIA_TTS_URL,
            json=body,
            headers=headers,
            timeout=timeout,
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise CartesiaTTSError(f"Cartesia {resp.status_code}: {resp.text[:300]}")

    pcm_bytes = resp.content
    wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate)
    return TTSResult(audio=wav_bytes, sample_rate=sample_rate)
