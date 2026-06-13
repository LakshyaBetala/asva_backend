"""Sarvam Saaras v3 STREAMING STT over WebSocket.

Replaces the batch-per-utterance path (sarvam_stt.transcribe_batch) on live
phone calls. Why streaming wins on telephony:

  1. Endpointing happens SERVER-SIDE with a model-based VAD instead of our
     local peak-amplitude silence counter. The local 750 ms silence flush is
     what kept cutting leads off mid-sentence ("do you forget things in
     between?") — a thinking pause looks identical to end-of-turn when all
     you measure is amplitude.
  2. Audio streams to Sarvam WHILE the lead is still talking, so the final
     transcript lands ~immediately after END_SPEECH instead of paying a
     350-2500 ms batch POST after we detect silence. Net ~0.7-2.5 s faster
     to first LLM token.
  3. Pricing is the same Rs 30/audio-hour as batch, so the Rs 7 / 2.5-min
     call ceiling is unaffected.

The Exotel WS handler owns the audio loop; this class owns one Sarvam WS
per call:

    stt = SarvamStreamingSTT(api_key=...)        # 8 kHz pcm_s16le default
    await stt.start()
    await stt.feed(pcm_chunk)                    # every inbound media frame
    result = stt.pop_final()                     # STTResult | None, per loop
    await stt.close()

Failure model: any send/connect error marks the session `.failed` and the
handler silently falls back to the old buffer+batch path mid-call — a
dropped Sarvam WS must never drop a phone call.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from .sarvam_stt import STTResult, _normalize_lang

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "saaras:v3"
DEFAULT_SAMPLE_RATE = 8000  # Exotel telephony PCM — fed through unchanged.

# transcribe mode returns text in the SPOKEN language plus a language_code
# label — same contract as the batch /speech-to-text endpoint the language
# state machine was built around. (translate would flatten everything to
# English; the LLM must read the lead's actual phrasing to mirror it.)
DEFAULT_MODE = "transcribe"


class SarvamStreamingSTT:
    """One live Sarvam streaming-STT WebSocket session (one per call)."""

    def __init__(
        self,
        *,
        api_key: str,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        model: str = DEFAULT_MODEL,
        mode: str = DEFAULT_MODE,
        language_hint: str = "unknown",  # "unknown" = Saaras auto-detect
        high_vad_sensitivity: bool = True,
    ) -> None:
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._model = model
        self._mode = mode
        self._language_hint = language_hint
        self._high_vad = high_vad_sensitivity

        self._socket: Any = None
        self._cm: Any = None
        self._reader_task: asyncio.Task | None = None
        self._finals: asyncio.Queue[STTResult] = asyncio.Queue()
        self._closed = False
        self.failed = False
        # Monotonic time of the last END_SPEECH event — lets the handler
        # report how long Sarvam took from end-of-speech to final transcript.
        self.last_end_speech_at: float = 0.0
        self.speech_active = False  # between START_SPEECH and END_SPEECH

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Open the WS. Raises on failure — caller decides the fallback."""
        from sarvamai import AsyncSarvamAI

        client = AsyncSarvamAI(api_subscription_key=self._api_key)
        self._cm = client.speech_to_text_streaming.connect(
            language_code=self._language_hint,
            model=self._model,
            mode=self._mode,
            sample_rate=str(self._sample_rate),
            input_audio_codec="pcm_s16le",
            high_vad_sensitivity="true" if self._high_vad else "false",
            vad_signals="true",
            flush_signal="true",
        )
        self._socket = await self._cm.__aenter__()
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info(
            "sarvam streaming STT connected (model=%s mode=%s rate=%d lang=%s)",
            self._model, self._mode, self._sample_rate, self._language_hint,
        )

    async def repin(self, language_hint: str) -> None:
        """Reconnect the STT pinned to a NEW language — mid-call flip.

        We pin language_code for accuracy (auto-detect garbles single-
        language calls). When the language state machine confirms a real
        switch (e.g. lead says "Tamil please" on an English call), the STT
        must follow or it keeps mis-transcribing in the old language. This
        tears down the current WS and reopens pinned to the new language.
        Fired as a background task while Priya speaks the bridge line, so
        the ~1s reconnect lands during her audio (lead isn't talking).
        No-op if the language is unchanged or the session is dead.
        """
        if (
            not language_hint
            or language_hint == self._language_hint
            or self.failed
            or self._closed
        ):
            return
        logger.info(
            "sarvam STT re-pin %s -> %s (mid-call language flip)",
            self._language_hint, language_hint,
        )
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None
        self._socket = None
        self._language_hint = language_hint
        self.speech_active = False
        try:
            await self.start()
        except Exception:
            logger.exception("sarvam STT re-pin connect failed — marking failed")
            self.failed = True

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None
        self._socket = None

    # -- audio in ------------------------------------------------------------

    async def feed(self, pcm: bytes) -> None:
        """Send one raw 16-bit mono PCM chunk. Errors mark the session failed."""
        if self._socket is None or self.failed or self._closed or not pcm:
            return
        try:
            # encoding is pinned to "audio/wav" by the SDK's message schema;
            # the actual payload format (raw pcm_s16le) was declared at
            # connect time via input_audio_codec.
            await self._socket.transcribe(
                audio=base64.b64encode(pcm).decode("ascii"),
                encoding="audio/wav",
                sample_rate=self._sample_rate,
            )
        except Exception:
            logger.exception("sarvam streaming feed failed — marking session dead")
            self.failed = True

    async def flush(self) -> None:
        """Force-finalize whatever Sarvam is still holding (e.g. barge-in)."""
        if self._socket is None or self.failed or self._closed:
            return
        try:
            await self._socket.flush()
        except Exception:
            logger.exception("sarvam streaming flush failed — marking session dead")
            self.failed = True

    # -- transcripts out -------------------------------------------------------

    def pop_final(self) -> STTResult | None:
        """Non-blocking: next finalized utterance, or None.

        The handler calls this once per inbound media frame (~100 ms cadence),
        so worst-case added latency from polling is one frame.
        """
        try:
            return self._finals.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def drain_finals(self, first: STTResult) -> STTResult:
        """Merge any further queued finals into `first` so one lead turn that
        Sarvam endpointed into two segments still reaches the LLM as one
        utterance (the mid-sentence-fragment fix, done at the source)."""
        parts = [first.transcript]
        last = first
        while True:
            nxt = self.pop_final()
            if nxt is None:
                break
            parts.append(nxt.transcript)
            last = nxt
        if len(parts) == 1:
            return first
        return STTResult(
            transcript=" ".join(p for p in parts if p).strip(),
            language_code=last.language_code,
            confidence=min(first.confidence, last.confidence),
            request_id=last.request_id,
        )

    # -- reader ----------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Consume server messages: VAD signals + finalized transcripts."""
        try:
            while not self._closed:
                msg = await self._socket.recv()
                mtype = getattr(msg, "type", None)
                data = getattr(msg, "data", None)
                if mtype == "events":
                    signal = (
                        getattr(data, "signal_type", None)
                        or getattr(data, "event_type", None)
                        or ""
                    )
                    if signal == "START_SPEECH":
                        self.speech_active = True
                    elif signal == "END_SPEECH":
                        self.speech_active = False
                        self.last_end_speech_at = time.monotonic()
                    continue
                if mtype == "error":
                    logger.warning("sarvam streaming error frame: %s", data)
                    continue
                # type == "data" → finalized transcript segment.
                transcript = (getattr(data, "transcript", "") or "").strip()
                if not transcript:
                    continue
                lang = getattr(data, "language_code", None) or "en-IN"
                if "-" not in lang:
                    lang = _normalize_lang(lang)
                conf = getattr(data, "language_probability", None)
                self._finals.put_nowait(
                    STTResult(
                        transcript=transcript,
                        language_code=lang,
                        confidence=float(conf) if conf is not None else 1.0,
                        request_id=getattr(data, "request_id", None),
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._closed:
                logger.exception("sarvam streaming reader died — marking failed")
                self.failed = True
