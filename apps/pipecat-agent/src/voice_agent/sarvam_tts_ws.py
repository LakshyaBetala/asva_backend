"""Sarvam Bulbul v3 streaming TTS over WebSocket.

Why
---
The REST endpoint returns the full clip only after synthesis completes —
1.8-2.6s per sentence on live calls, the single largest latency cost in
the turn (LLM is ~400ms). The streaming WS starts emitting audio while
the text is still being synthesized: measured 97ms to first audio for a
Tamil sentence (probe 2026-06-12, scripts/probe_tts_ws.py).

Wire format (verified live against the real API)
------------------------------------------------
After `configure(output_audio_codec="wav", speech_sample_rate=8000)`:
  - first audio message carries a 44-byte RIFF header with an unknown
    (0xFFFFFFFF) length — streaming WAV preamble, NOT playable audio;
  - every subsequent audio message is raw signed-16 LE mono PCM at the
    configured rate (~2200-byte chunks ≈ 137ms each);
  - with send_completion_event="true" the server marks the end of each
    flush, so one connection serves the whole call.

The adapter exposes BOTH interfaces:
  - synth(text, lang) -> bytes        — full WAV, drop-in for the REST
    adapter (intro pre-synth, phrase-cache warming).
  - synth_stream(text, lang) -> AsyncIterator[bytes]  — raw PCM chunks
    as they arrive; the orchestrator forwards each to the phone line.

Any WS failure degrades to one REST call for that sentence — the lead
never hears silence because of a dropped socket.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import struct
from typing import AsyncIterator, Optional

from .audio_codec import pcm16_resample, wav_to_pcm16
from .sarvam_tts import (
    DEFAULT_MODEL,
    DEFAULT_SPEAKER,
    SarvamTTSError,
    default_dict_id,
    synthesize as rest_synthesize,
)

logger = logging.getLogger(__name__)

# Characters Sarvam buffers before the first audio chunk. Lower = faster
# first audio; too low degrades prosody on the opening words. 30 measured
# fine in the probe (full natural sentence).
DEFAULT_MIN_BUFFER_SIZE = 30
RECV_TIMEOUT_SEC = 10.0


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw signed-16 LE mono PCM in a minimal WAV container."""
    byte_rate = sample_rate * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, byte_rate, 2, 16,
        b"data", len(pcm),
    )
    return header + pcm


def _looks_like_riff_preamble(chunk: bytes) -> bool:
    return chunk[:4] == b"RIFF" and len(chunk) <= 64


class SarvamStreamingTTS:
    """Persistent-connection Bulbul v3 streaming synthesizer.

    One instance per process; one WS connection reused across turns and
    calls (reconnects lazily after errors). `synth_stream` is serialized
    with a lock — Sarvam interleaves audio of concurrent converts on one
    socket, so sentences must take turns.
    """

    def __init__(
        self,
        *,
        api_key: str,
        speaker: str = DEFAULT_SPEAKER,
        sample_rate: int = 8000,
        model: str = DEFAULT_MODEL,
        min_buffer_size: int = DEFAULT_MIN_BUFFER_SIZE,
    ) -> None:
        self.api_key = api_key
        self.speaker = speaker
        self.sample_rate = sample_rate
        self.model = model
        self.min_buffer_size = min_buffer_size
        self._lock = asyncio.Lock()
        self._cm = None  # the connect() async context manager
        self._ws = None
        self._configured_lang: Optional[str] = None

    # -- connection management ------------------------------------------

    async def _ensure_ws(self):
        if self._ws is not None:
            return self._ws
        from sarvamai import AsyncSarvamAI

        client = AsyncSarvamAI(api_subscription_key=self.api_key)
        self._cm = client.text_to_speech_streaming.connect(
            model=self.model, send_completion_event="true"
        )
        self._ws = await self._cm.__aenter__()
        self._configured_lang = None
        return self._ws

    async def _drop_ws(self) -> None:
        cm, self._cm, self._ws = self._cm, None, None
        self._configured_lang = None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

    async def aclose(self) -> None:
        async with self._lock:
            await self._drop_ws()

    async def warmup(self) -> None:
        """Open the WS ahead of the first sentence — connection setup costs
        ~0.5-1.5s that would otherwise land on the call's first reply."""
        try:
            async with self._lock:
                await self._ensure_ws()
        except Exception as exc:
            logger.warning("streaming TTS warmup failed: %s", exc)

    async def _configure(self, ws, lang: str) -> None:
        # Reconfigure only on language change — the speaker and rate are
        # constant for the call; redundant configures add a round-trip.
        if self._configured_lang == lang:
            return
        cfg: dict = dict(
            target_language_code=lang,
            speaker=self.speaker,
            speech_sample_rate=self.sample_rate,
            output_audio_codec="wav",
            min_buffer_size=self.min_buffer_size,
        )
        dict_id = default_dict_id()
        if dict_id:
            cfg["dict_id"] = dict_id
        await ws.configure(**cfg)
        self._configured_lang = lang

    # -- synthesis --------------------------------------------------------

    async def _stream_once(self, text: str, lang: str) -> AsyncIterator[bytes]:
        ws = await self._ensure_ws()
        await self._configure(ws, lang)
        await ws.convert(text)
        await ws.flush()
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT_SEC)
            audio_b64 = getattr(getattr(msg, "data", None), "audio", None)
            if audio_b64:
                chunk = base64.b64decode(audio_b64)
                if _looks_like_riff_preamble(chunk):
                    continue
                yield chunk
                continue
            # Non-audio message: completion event ends the sentence;
            # error responses surface as exceptions.
            name = type(msg).__name__.lower()
            text_repr = str(msg).lower()
            if "error" in name or "error" in text_repr[:80]:
                raise SarvamTTSError(f"streaming TTS error: {str(msg)[:200]}")
            if "event" in name or "final" in text_repr or "complete" in text_repr:
                return

    async def synth_stream(self, text: str, lang: str) -> AsyncIterator[bytes]:
        """Yield raw PCM16 chunks at self.sample_rate. Serialized per
        sentence; degrades to one REST call on WS failure."""
        if not text.strip():
            return
        async with self._lock:
            try:
                # Hold the first two chunks (~270ms audio) before releasing:
                # the phone line plays at exactly 1x; if generation hiccups
                # early, the line runs dry mid-word — heard as random gaps
                # inside a sentence ("sometimes it takes gaps"). A small
                # jitter buffer absorbs that for ~140ms extra latency.
                held: list[bytes] = []
                async for chunk in self._stream_once(text, lang):
                    if held is not None:
                        held.append(chunk)
                        if len(held) < 2:
                            continue
                        for h in held:
                            yield h
                        held = None  # type: ignore[assignment]
                        continue
                    yield chunk
                if held:
                    for h in held:
                        yield h
                return
            except Exception as exc:
                logger.warning(
                    "streaming TTS failed (%s) — REST fallback for: %.40s",
                    exc, text,
                )
                await self._drop_ws()
        # REST fallback outside the lock — it's a plain HTTP call. Strip
        # the WAV container so the contract stays "raw PCM at sample_rate".
        result = await rest_synthesize(
            text=text, lang=lang, api_key=self.api_key,
            speaker=self.speaker, sample_rate=self.sample_rate,
        )
        pcm, sr = wav_to_pcm16(result.audio)
        yield pcm16_resample(pcm, sr, self.sample_rate)

    async def synth(self, text: str, lang: str) -> bytes:
        """Full-WAV interface (intro pre-synth, phrase cache warming)."""
        chunks: list[bytes] = []
        async for chunk in self.synth_stream(text, lang):
            chunks.append(chunk)
        return pcm16_to_wav(b"".join(chunks), self.sample_rate)
