"""Sarvam Bulbul v3 TTS adapter.

Single voice pinned across HI/EN/TA (PINNED_VOICE_ID in phrase_cache.py).
The language flip happens inside one voice's range, not by swapping
voices — that is what keeps Priya sounding like one person.

Endpoint:
  https://api.sarvam.ai/text-to-speech

Headers:
  api-subscription-key: <SARVAM_API_KEY>

JSON body:
  {
    "inputs": ["<text>"],
    "target_language_code": "hi-IN" | "en-IN" | "ta-IN",
    "speaker": "anushka",            # one female Chennai voice
    "pitch": 0.0,                    # neutral
    "pace": 1.0,                     # slightly slower to sound calm
    "loudness": 1.0,
    "speech_sample_rate": 8000,      # PSTN-grade; matches Plivo stream
    "enable_preprocessing": true,
    "model": "bulbul:v3"
  }

Response (JSON):
  {
    "audios": ["<base64 wav>"],
    "request_id": "...",
    "metrics": { ... }
  }

We decode the first audio to raw bytes. Sarvam returns WAV at the rate
we requested; Pipecat handles resampling if Plivo needs μ-law.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
DEFAULT_MODEL = "bulbul:v3"

# Bulbul v3 speaker roster (Sarvam, mid-2026). Anushka/Meera from v2 are
# NOT available on v3; passing them returns HTTP 400.
BULBUL_V3_FEMALE_SPEAKERS: frozenset[str] = frozenset({
    "priya", "ritu", "neha", "pooja", "simran", "kavya", "ishita",
    "shreya", "roopa", "tanya",
})
BULBUL_V3_MALE_SPEAKERS: frozenset[str] = frozenset({
    "aditya", "ashutosh", "rahul", "rohan", "amit", "dev", "ratan",
    "varun", "manan", "sumit", "kabir", "aayan", "shubh", "advait",
    "anand", "tarun",
})
BULBUL_V3_SPEAKERS: frozenset[str] = BULBUL_V3_FEMALE_SPEAKERS | BULBUL_V3_MALE_SPEAKERS

# Per-tenant CRM picks one of these two. Defaults below are picked for SPC.
DEFAULT_FEMALE_SPEAKER = "priya"  # Matches our agent persona name. Convenient.
DEFAULT_MALE_SPEAKER = "rahul"

# Backward-compatible default — what the system uses if a tenant hasn't
# picked a voice yet. CRM settings page overrides this per tenant.
DEFAULT_SPEAKER = DEFAULT_FEMALE_SPEAKER
DEFAULT_SAMPLE_RATE = 8000  # Match Plivo PSTN audio stream.
DEFAULT_TIMEOUT_SECONDS = 20.0


def is_valid_v3_speaker(speaker: str) -> bool:
    """Guard against silent breakage when a tenant or env var sets a stale name."""
    return speaker.lower() in BULBUL_V3_SPEAKERS


@dataclass(frozen=True)
class TTSResult:
    audio: bytes  # decoded WAV
    request_id: str | None


class SarvamTTSError(RuntimeError):
    """Raised for non-2xx responses or malformed JSON."""


def default_dict_id() -> str:
    """Sarvam server-side pronunciation dictionary (phoneme-level word
    fixes, scoped per language). Created once via
    scripts/upload_pronunciation_dict.py; the returned p_... id goes in
    SARVAM_TTS_DICT_ID. Empty = no dictionary."""
    import os

    return os.environ.get("SARVAM_TTS_DICT_ID", "").strip()


async def synthesize(
    *,
    text: str,
    lang: str,
    api_key: str,
    speaker: str = DEFAULT_SPEAKER,
    model: str = DEFAULT_MODEL,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    pitch: float = 0.0,
    pace: float = 1.0,
    loudness: float = 1.0,
    dict_id: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TTSResult:
    """Synthesize one phrase. Returns WAV bytes ready to push to Plivo."""
    if not text.strip():
        raise SarvamTTSError("empty text")
    if not api_key:
        raise SarvamTTSError("missing SARVAM_API_KEY")

    body: dict[str, Any] = {
        "inputs": [text],
        "target_language_code": lang,
        "speaker": speaker,
        "speech_sample_rate": sample_rate,
        "enable_preprocessing": True,
        "model": model,
    }
    effective_dict = dict_id if dict_id is not None else default_dict_id()
    if effective_dict:
        body["dict_id"] = effective_dict
    # Bulbul v3 rejects pitch/loudness; bulbul v2 accepts them. Only send
    # when the caller customized them AND we're on a model that accepts.
    if model.startswith("bulbul:v2"):
        body["pitch"] = pitch
        body["pace"] = pace
        body["loudness"] = loudness
    elif pace != 1.0:
        # v3 still accepts pace; only include when changed from default.
        body["pace"] = pace

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            SARVAM_TTS_URL,
            headers={
                "api-subscription-key": api_key,
                "content-type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise SarvamTTSError(f"Sarvam TTS {resp.status_code}: {resp.text[:300]}")

    try:
        payload: dict[str, Any] = resp.json()
    except Exception as exc:
        raise SarvamTTSError(f"non-JSON TTS response: {exc}") from exc

    audio = _extract_audio(payload)
    return TTSResult(audio=audio, request_id=payload.get("request_id"))


def _extract_audio(payload: dict[str, Any]) -> bytes:
    audios = payload.get("audios") if "audios" in payload else payload.get("audio")
    if isinstance(audios, list):
        if not audios:
            raise SarvamTTSError("empty audios array")
        first = audios[0]
    elif isinstance(audios, str):
        first = audios
    else:
        raise SarvamTTSError(f"unexpected audios field: {type(audios).__name__}")

    if not isinstance(first, str):
        raise SarvamTTSError("audio entry not a base64 string")

    try:
        return base64.b64decode(first)
    except Exception as exc:
        raise SarvamTTSError(f"audio b64 decode failed: {exc}") from exc


def make_phrase_synthesizer(
    *,
    api_key: str,
    client: httpx.AsyncClient | None = None,
    speaker: str = DEFAULT_SPEAKER,
):
    """Bind credentials so phrase_cache.warm_phrase_cache can call synth(text, lang).

    Returns an async (text, lang) -> bytes closure matching phrase_cache.Synthesizer.
    """
    async def _synth(text: str, lang: str) -> bytes:
        result = await synthesize(
            text=text,
            lang=lang,
            api_key=api_key,
            speaker=speaker,
            client=client,
        )
        return result.audio

    return _synth
