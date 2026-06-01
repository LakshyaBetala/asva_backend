"""Sarvam Saaras v3 STT adapter.

Two surfaces:

  1. transcribe_batch() — single-shot HTTP request, used for the
     "lead finished talking, send the full utterance" path. Returns
     transcript + detected language + confidence.
  2. SarvamSTTStream — websocket-like streaming wrapper for the live
     telephony loop. Pipecat feeds 8 kHz μ-law frames; we accumulate
     and flush at VAD endpoints. This module exposes the protocol; the
     real WS wire-up lives in pipeline.py.

Why batch + streaming both? Saaras' streaming endpoint is great for
latency but the per-utterance language label is more reliable when you
hand it a full clip. The language-state machine relies on that label, so
we call batch at every endpoint for the authoritative language tag.

Endpoint:
  https://api.sarvam.ai/speech-to-text-translate  (Saaras v3, multilingual)

Headers:
  api-subscription-key: <SARVAM_API_KEY>

Form fields:
  model: saaras:v3
  language_code: unknown   (let Saaras detect; we read it back)
  with_diarization: false
  file: <audio bytes, WAV/MP3>

Response (JSON):
  {
    "transcript": "...",
    "language_code": "hi-IN" | "en-IN" | "ta-IN" | ...,
    "diarized_transcript": null,
    "request_id": "..."
  }
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import httpx

# IMPORTANT: /speech-to-text returns text in the SPOKEN language (with a
# language_code label). /speech-to-text-translate auto-translates to English
# and discards the original language — bad for our use case because we want
# the LLM to read what the lead actually said so it can mirror their phrasing.
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
DEFAULT_MODEL = "saaras:v3"
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class STTResult:
    transcript: str
    language_code: str
    confidence: float  # Sarvam doesn't always return this; default 1.0 when missing.
    request_id: str | None


class SarvamSTTError(RuntimeError):
    """Raised for non-2xx responses or malformed JSON."""


async def transcribe_batch(
    *,
    audio: bytes,
    api_key: str,
    model: str = DEFAULT_MODEL,
    language_hint: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    filename: str = "utterance.wav",
    content_type: str = "audio/wav",
) -> STTResult:
    """Send one utterance to Saaras and return transcript + detected lang.

    The optional language_hint biases detection; pass None to let Saaras
    auto-detect (which the language_state machine relies on).
    """
    if not audio:
        raise SarvamSTTError("empty audio buffer")
    if not api_key:
        raise SarvamSTTError("missing SARVAM_API_KEY")

    files = {"file": (filename, io.BytesIO(audio), content_type)}
    data: dict[str, str] = {"model": model}
    if language_hint:
        data["language_code"] = language_hint

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": api_key},
            data=data,
            files=files,
            timeout=timeout,
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise SarvamSTTError(f"Sarvam STT {resp.status_code}: {resp.text[:300]}")

    try:
        payload: dict[str, Any] = resp.json()
    except Exception as exc:
        raise SarvamSTTError(f"non-JSON STT response: {exc}") from exc

    return _parse_stt_response(payload)


def _parse_stt_response(payload: dict[str, Any]) -> STTResult:
    """Tolerant parser. Sarvam's response shape has shifted across versions."""
    transcript = (payload.get("transcript") or payload.get("text") or "").strip()
    lang = (
        payload.get("language_code")
        or payload.get("detected_language")
        or "en-IN"
    )
    if "-" not in lang:
        lang = _normalize_lang(lang)

    # Confidence is optional; default to 1.0 when Sarvam doesn't return it
    # so downstream callers (LanguageState) don't down-weight valid utterances.
    confidence = float(payload.get("confidence", 1.0))
    return STTResult(
        transcript=transcript,
        language_code=lang,
        confidence=confidence,
        request_id=payload.get("request_id"),
    )


def _normalize_lang(code: str) -> str:
    """Map bare ISO-639 to BCP-47 used by language_state."""
    mapping = {
        "hi": "hi-IN",
        "en": "en-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "kn": "kn-IN",
        "ml": "ml-IN",
        "bn": "bn-IN",
        "mr": "mr-IN",
        "gu": "gu-IN",
        "pa": "pa-IN",
    }
    return mapping.get(code.lower(), "en-IN")
