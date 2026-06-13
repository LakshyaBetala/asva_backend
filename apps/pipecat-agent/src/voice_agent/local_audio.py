"""Local mic/speaker harness for testing Priya without telephony.

Why this exists
---------------
Plivo / Exotel KYC takes 24-48 hours. We don't want to wait. This module
lets you talk to Priya through your laptop mic and hear her through your
speakers, hitting the same orchestrator, the same Sarvam STT/TTS, the
same Gemini, and the same R2 phrase cache that the production phone call
will hit.

If this works on your laptop, the only thing left to add for a real call
is the Plivo WebSocket transport — every voice/LLM/cache concern is
already proven by the time you plug a phone in.

Usage:

  cd apps/pipecat-agent
  python -m voice_agent.local_audio --lang hi-IN --lead-name Suresh

Press ENTER to start recording your turn. Press ENTER again to stop.
Priya responds. Repeat. Type 'q' to quit.

Hard caps + phase machine + cost guardrails apply the same as on a real call.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from .pipeline import HARD_CAP_SECONDS, make_initial_context
from .qualification import QualificationSlots
from .r2_client import R2Client, R2Config, R2ConfigError
from .sarvam_stt import STTResult, transcribe_batch
from .sarvam_tts import DEFAULT_SPEAKER as TTS_DEFAULT_SPEAKER
from .sarvam_tts import synthesize as tts_synthesize
from .cartesia_tts import synthesize as cartesia_synthesize
from .elevenlabs_tts import synthesize as elevenlabs_synthesize
from .smallest_tts import (
    DEFAULT_MODEL as SMALLEST_DEFAULT_MODEL,
    DEFAULT_SAMPLE_RATE as SMALLEST_DEFAULT_RATE,
    DEFAULT_VOICE as SMALLEST_DEFAULT_VOICE,
    synthesize as smallest_synthesize,
)
from .gemini_llm import generate as gemini_generate, stream_generate as gemini_stream
from .groq_llm import GroqError, generate as groq_generate, stream_generate as groq_stream
from .streaming_orchestrator import (
    AudioChunkEvent,
    StreamingDependencies,
    TurnCompleteEvent,
    run_turn_streaming,
)
from .turn_orchestrator import TurnDependencies


# Telephony-grade audio settings. Match what Plivo will deliver later so
# the pipeline behaves identically.
SAMPLE_RATE_HZ = 16000  # mic input; Sarvam accepts 8/16k. 16k = cleaner STT.
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # int16
TTS_OUTPUT_SAMPLE_RATE = 8000  # Sarvam returns 8k WAV by default


# -- Adapter wrappers exposing the Protocols the orchestrator expects -------

@dataclass
class _SarvamSTTAdapter:
    api_key: str
    client: httpx.AsyncClient

    async def transcribe(self, audio: bytes) -> STTResult:
        return await transcribe_batch(audio=audio, api_key=self.api_key, client=self.client)


@dataclass
class _SarvamTTSAdapter:
    api_key: str
    client: httpx.AsyncClient
    speaker: str = TTS_DEFAULT_SPEAKER

    async def synth(self, text: str, lang: str) -> bytes:
        result = await tts_synthesize(
            text=text, lang=lang, api_key=self.api_key, client=self.client,
            speaker=self.speaker,
        )
        return result.audio


@dataclass
class _CartesiaTTSAdapter:
    api_key: str
    client: httpx.AsyncClient
    voice: str = "arushi"

    async def synth(self, text: str, lang: str) -> bytes:
        result = await cartesia_synthesize(
            text=text, lang=lang, api_key=self.api_key,
            voice=self.voice, client=self.client,
        )
        return result.audio


@dataclass
class _SmallestTTSAdapter:
    api_key: str
    client: httpx.AsyncClient
    voice: str = SMALLEST_DEFAULT_VOICE
    model: str = SMALLEST_DEFAULT_MODEL
    sample_rate: int = SMALLEST_DEFAULT_RATE
    speed: float = 1.0
    # When to send the language hint: "tamil_only" (default) lets Lightning
    # auto-detect for hi/en so embedded English words + numbers are pronounced
    # naturally (code-mixing), but pins Tamil so romanized Tanglish isn't read
    # as English. "always" forces the hint; "never" always auto-detects.
    lang_hint: str = "tamil_only"

    def _send_language(self, lang: str) -> bool:
        if self.lang_hint == "always":
            return True
        if self.lang_hint == "never":
            return False
        return (lang or "").lower().startswith("ta")

    async def synth(self, text: str, lang: str) -> bytes:
        result = await smallest_synthesize(
            text=text, lang=lang, api_key=self.api_key,
            voice=self.voice, model=self.model,
            sample_rate=self.sample_rate, speed=self.speed,
            send_language=self._send_language(lang), client=self.client,
        )
        return result.audio


@dataclass
class _ElevenLabsTTSAdapter:
    api_key: str
    client: httpx.AsyncClient
    voice_id: str
    model: str = "eleven_flash_v2_5"

    async def synth(self, text: str, lang: str) -> bytes:
        result = await elevenlabs_synthesize(
            text=text, lang=lang, api_key=self.api_key,
            voice_id=self.voice_id, model=self.model, client=self.client,
        )
        return result.audio


@dataclass
class _HybridTTSAdapter:
    """Route by language: ElevenLabs for Hindi/English (hyper-realistic),
    Cartesia for Tamil (dedicated Tamil voice). Falls back to primary for
    anything else."""
    primary: Any  # ElevenLabs adapter (hi/en)
    tamil: Any    # Cartesia adapter (ta)

    async def synth(self, text: str, lang: str) -> bytes:
        if lang and lang.lower().startswith("ta"):
            return await self.tamil.synth(text, lang)
        return await self.primary.synth(text, lang)


@dataclass
class _GeminiAdapter:
    api_key: str
    model: str
    client: httpx.AsyncClient

    async def respond(self, system_message: str, user_message: str) -> str:
        resp = await gemini_generate(
            system_message=system_message,
            user_message=user_message,
            api_key=self.api_key,
            model=self.model,
            client=self.client,
        )
        return resp.text

    async def stream_respond(self, system_message: str, user_message: str):
        async for chunk in gemini_stream(
            system_message=system_message,
            user_message=user_message,
            api_key=self.api_key,
            model=self.model,
            client=self.client,
        ):
            yield chunk

    async def extract(self, prompt: str) -> str:
        resp = await gemini_generate(
            system_message="You are a JSON extraction engine. Output ONLY valid JSON.",
            user_message=prompt,
            api_key=self.api_key,
            model=self.model,
            client=self.client,
            generation_config={"temperature": 0.1, "maxOutputTokens": 600},
        )
        return resp.text


# Groq 429 bodies advise exactly when the TPM window frees up:
#   "Please try again in 410ms"  /  "Please try again in 3.86s"
_GROQ_RETRY_RE = re.compile(r"try again in\s*([\d.]+)\s*(ms|s)\b")


def _parse_groq_retry_after(msg: str) -> float | None:
    m = _GROQ_RETRY_RE.search(msg)
    if not m:
        return None
    val = float(m.group(1))
    return val / 1000.0 if m.group(2) == "ms" else val


# Gemini quota circuit breaker. Free-tier daily-quota 429s don't recover
# between turns, but the old code retried Gemini on EVERY turn and paid a
# failed round-trip each time (call 2b674c4c: 10 consecutive 429s). After
# a quota 429, route straight to Groq until the cooldown passes.
_GEMINI_QUOTA_COOLDOWN_SEC = 300.0
_gemini_down_until = 0.0


class _GeminiKeyPool:
    """Round-robin pool of Gemini API keys with per-key cooldown.

    Free-tier keys have separate daily quotas, so rotating one key per call
    across N keys gives ~Nx the free capacity AND keeps us on Gemini instead
    of falling through the slow Groq→Cerebras 429 cascade (which added 1-3s
    per turn, call 287e6c4d). A key that hits its quota is parked on cooldown
    and skipped until it recovers.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = [k for k in keys if k]
        self._i = 0
        self._down: dict[str, float] = {}

    def next_key(self) -> str:
        """Next key not on cooldown (round-robin); else the soonest-recovering."""
        if not self.keys:
            return ""
        now = time.monotonic()
        n = len(self.keys)
        for _ in range(n):
            k = self.keys[self._i % n]
            self._i += 1
            if self._down.get(k, 0.0) <= now:
                return k
        return min(self.keys, key=lambda k: self._down.get(k, 0.0))

    def is_down(self, key: str) -> bool:
        return self._down.get(key, 0.0) > time.monotonic()

    def mark_exhausted(self, key: str, cooldown: float = _GEMINI_QUOTA_COOLDOWN_SEC) -> None:
        if key:
            self._down[key] = time.monotonic() + cooldown


def gemini_keys_from_env(env: dict[str, str] | None = None) -> list[str]:
    """Parse GEMINI_API_KEYS (comma-separated) with GEMINI_API_KEY fallback."""
    src = env if env is not None else os.environ
    multi = src.get("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    single = src.get("GEMINI_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)
    return keys


# Process-wide pool, lazily initialised from env on first use.
_gemini_pool: _GeminiKeyPool | None = None


def _get_gemini_pool() -> _GeminiKeyPool:
    global _gemini_pool
    if _gemini_pool is None:
        _gemini_pool = _GeminiKeyPool(gemini_keys_from_env())
    return _gemini_pool


def next_gemini_key() -> str:
    """Pick the next Gemini key for a new call (round-robin, skips exhausted).
    Empty string if no keys configured."""
    return _get_gemini_pool().next_key()
# Same breaker for Groq's DAILY token cap (TPD) — once it's gone it's gone
# for ~hours, but call be21ced9 paid a Groq 429 round-trip on every single
# turn before hopping to Cerebras. Minute-level (TPM) 429s do NOT trip
# this — those recover in seconds and are handled by the retry below.
_GROQ_TPD_COOLDOWN_SEC = 600.0
_groq_down_until = 0.0


@dataclass
class _GroqAdapter:
    api_key: str
    model: str
    client: httpx.AsyncClient
    # Slot extraction is simple JSON work — run it on a small fast model so
    # the big conversational model's TPM budget (and bill) isn't paid twice
    # per turn. Call d4cffcb9: extract on the 70B doubled token burn and
    # tripped the free-tier 12K TPM limit every other turn.
    extract_model: str = "llama-3.1-8b-instant"
    # When set, slot extraction uses Gemini (off by default so we don't burn
    # Gemini's free-tier rate budget on every turn).
    gemini_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    # Fallback key used ONLY when Groq's streaming respond fails with a 429
    # / 5xx. Independent of `gemini_key` so we can keep extraction on Groq
    # but still survive a Groq daily-cap hit on the response path.
    fallback_gemini_key: str = ""
    fallback_gemini_model: str = "gemini-2.0-flash"
    # Optional second OpenAI-compatible provider tried BEFORE Gemini when
    # the primary 429s — a separate free-tier TPM pool on faster hardware
    # (intended: Cerebras gpt-oss-120b at ~3000 tok/s, 30K TPM). Env:
    # ALT_LLM_BASE_URL / ALT_LLM_API_KEY / ALT_LLM_MODEL.
    alt_base_url: str = ""
    alt_api_key: str = ""
    alt_model: str = ""
    # Process-wide Gemini quota circuit breaker lives at module scope
    # (below the class) — adapters are rebuilt per call, the cooldown
    # must survive them.
    # When True, Gemini handles the conversation turns and Groq becomes the
    # fallback (extraction stays on Groq either way). Set LLM_PRIMARY=gemini.
    # Why: llama-3.3-70b parrots quoted directive examples verbatim and
    # ignores competing instructions (calls 43ea487c, 3cfaeed8); Gemini
    # 2.5 Flash follows the sales directives and writes far better
    # Hinglish/Tanglish.
    gemini_primary: bool = False

    async def respond(self, system_message: str, user_message: str) -> str:
        resp = await groq_generate(
            system_message=system_message,
            user_message=user_message,
            api_key=self.api_key,
            model=self.model,
            client=self.client,
        )
        return resp.text

    async def stream_respond(self, system_message: str, user_message: str):
        """Stream from Groq, fall back to Gemini on 429 / 5xx so a daily-cap
        hit on Groq doesn't kill the live call. Production logs caught this
        the hard way: Groq raised 'Rate limit reached on tokens per day' mid-
        stream and the orchestrator just crashed; the lead got silence.

        TPM 429s come with a server-advised wait ("Please try again in
        410ms"). When that wait is short, sleeping it out and retrying Groq
        beats switching providers — call 21c9952b paid 5.7-6.3s for Gemini
        fallbacks that a sub-second retry would have avoided."""
        if self.gemini_primary:
            pool = _get_gemini_pool()
            # The key assigned to this call (rotated per call by the deps
            # builder); fall back to a fresh pool pick if unset.
            g_key = self.fallback_gemini_key or self.gemini_key or pool.next_key()
            if g_key and not pool.is_down(g_key):
                got_gemini_chunk = False
                try:
                    async for chunk in gemini_stream(
                        system_message=system_message,
                        user_message=user_message,
                        api_key=g_key,
                        model=self.fallback_gemini_model or self.gemini_model,
                        client=self.client,
                    ):
                        got_gemini_chunk = True
                        yield chunk
                    return
                except Exception as exc:
                    if got_gemini_chunk:
                        # Already speaking — don't switch providers mid-sentence.
                        raise
                    msg = str(exc).lower()
                    if "429" in msg or "quota" in msg or "rate limit" in msg:
                        # This key's quota is gone — park it on cooldown so
                        # the pool skips it; the next call rotates to another
                        # key. (Per-key, not global: with 3 keys we keep
                        # serving on Gemini instead of the slow Groq cascade.)
                        pool.mark_exhausted(g_key)
                        logger.warning(
                            "gemini key exhausted — parked %.0fs, falling back "
                            "to groq this turn (%s)", _GEMINI_QUOTA_COOLDOWN_SEC, exc,
                        )
                    else:
                        logger.warning(
                            "gemini primary failed (%s); falling back to groq", exc
                        )
        global _groq_down_until
        first_chunk = True
        retried = False
        last_exc: GroqError | None = None
        while time.monotonic() >= _groq_down_until:
            try:
                async for chunk in groq_stream(
                    system_message=system_message,
                    user_message=user_message,
                    api_key=self.api_key,
                    model=self.model,
                    client=self.client,
                ):
                    first_chunk = False
                    yield chunk
                return
            except GroqError as exc:
                last_exc = exc
                msg = str(exc).lower()
                transient = (
                    "429" in msg or "rate limit" in msg or "tokens per day" in msg
                    or "500" in msg or "502" in msg or "503" in msg or "504" in msg
                )
                if "tokens per day" in msg or "tpd" in msg:
                    # Daily cap — gone for hours; stop paying the failed
                    # round-trip on every turn (call be21ced9).
                    _groq_down_until = time.monotonic() + _GROQ_TPD_COOLDOWN_SEC
                    logger.warning(
                        "groq daily cap hit — routing to alt/gemini for the "
                        "next %.0fs", _GROQ_TPD_COOLDOWN_SEC,
                    )
                wait = _parse_groq_retry_after(msg)
                if (
                    transient and first_chunk and not retried
                    and wait is not None and wait <= 2.0
                ):
                    retried = True
                    logger.warning(
                        "groq 429 — retrying in %.2fs (server-advised) instead of "
                        "falling back", wait,
                    )
                    await asyncio.sleep(wait + 0.05)
                    continue
                # Only fall back if we haven't already started speaking — once
                # Priya has emitted text, switching providers mid-sentence would
                # produce gibberish. If we crashed mid-stream, propagate.
                fb_key = self.fallback_gemini_key or self.gemini_key
                has_alt = bool(self.alt_base_url and self.alt_api_key and self.alt_model)
                if not (transient and first_chunk and (fb_key or has_alt)):
                    raise
                break
        # Hop 1: alternate OpenAI-compatible pool (Cerebras) — faster than
        # Gemini and a fully separate free-tier TPM budget.
        if self.alt_base_url and self.alt_api_key and self.alt_model:
            logger.warning(
                "groq stream failed (%s); trying alt provider %s/%s",
                last_exc, self.alt_base_url, self.alt_model,
            )
            cfg: dict[str, Any] = {}
            if "gpt-oss" in self.alt_model:
                # gpt-oss is a reasoning model — cap deliberation for telephony.
                cfg["reasoning_effort"] = "low"
                # Reasoning tokens COUNT toward max_tokens on gpt-oss; the
                # default 120 can be consumed entirely by deliberation and
                # return ZERO content (the lead hears silence). Raise the
                # ceiling — brevity stays enforced by the prompt and the
                # orchestrator's 2-sentence cap.
                cfg["max_tokens"] = 480
            got_chunk = False
            try:
                async for chunk in groq_stream(
                    system_message=system_message,
                    user_message=user_message,
                    api_key=self.alt_api_key,
                    model=self.alt_model,
                    client=self.client,
                    base_url=self.alt_base_url,
                    generation_config=cfg or None,
                ):
                    got_chunk = True
                    yield chunk
                return
            except GroqError as exc:
                if got_chunk:
                    # Already speaking — switching providers mid-sentence
                    # would produce gibberish. Propagate.
                    raise
                logger.warning("alt provider failed too (%s); trying gemini", exc)
        # Hop 2: Gemini (thinking disabled for 2.5-family — see gemini_llm).
        fb_key = self.fallback_gemini_key or self.gemini_key
        if not fb_key:
            raise last_exc if last_exc else GroqError("groq stream failed")
        logger.warning("falling back to gemini for this turn")
        # Reached only on transient failure before any chunk yielded.
        async for chunk in gemini_stream(
            system_message=system_message,
            user_message=user_message,
            api_key=self.fallback_gemini_key or self.gemini_key,
            model=self.fallback_gemini_model or self.gemini_model,
            client=self.client,
        ):
            yield chunk

    async def extract(self, prompt: str) -> str:
        if self.gemini_key:
            resp = await gemini_generate(
                system_message="You are a JSON extraction engine. Output ONLY valid JSON.",
                user_message=prompt,
                api_key=self.gemini_key,
                model=self.gemini_model,
                client=self.client,
                generation_config={"temperature": 0.1, "maxOutputTokens": 600},
            )
            return resp.text
        resp = await groq_generate(
            system_message="You are a JSON extraction engine. Output ONLY valid JSON.",
            user_message=prompt,
            api_key=self.api_key,
            model=self.extract_model or self.model,
            client=self.client,
            generation_config={"temperature": 0.1, "max_tokens": 600},
        )
        return resp.text


# -- WAV helpers (PCM int16 ↔ WAV bytes ready for Sarvam) ------------------

def pcm_to_wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE_HZ) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH_BYTES)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_bytes_to_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
    """Return (raw_pcm, sample_rate) so sounddevice can play it back."""
    with wave.open(BytesIO(wav_bytes), "rb") as w:
        sr = w.getframerate()
        pcm = w.readframes(w.getnframes())
    return pcm, sr


# -- Press-ENTER mic capture (sync loop on a thread) -----------------------

def _get_sounddevice():
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        return sd, np
    except ImportError:
        raise SystemExit(
            "Local audio needs sounddevice + numpy. Install:\n"
            "  pip install sounddevice numpy"
        )


def list_audio_devices() -> None:
    """Print available audio devices so the user can pick the right mic."""
    sd, _ = _get_sounddevice()
    print("\n=== Audio devices ===")
    print(sd.query_devices())
    default_in = sd.query_devices(kind="input")
    print(f"\nDefault INPUT: {default_in['name']} (index {default_in['index']})")
    print()


MIN_RECORDING_MS = 1500

def record_until_enter(device: int | None = None) -> bytes:
    """Record from mic until ENTER pressed (minimum 1.5s).

    Uses sd.rec() for Windows reliability. Enforces minimum duration
    to avoid sending noise/clicks to STT.
    """
    sd, np = _get_sounddevice()

    if device is None:
        dev_info = sd.query_devices(kind="input")
    else:
        dev_info = sd.query_devices(device)
    print(f"[mic: {dev_info['name']}]")
    print("[recording — speak now, press ENTER when done]")

    sd.stop()
    time.sleep(0.15)

    max_seconds = 30
    recording = sd.rec(
        int(max_seconds * SAMPLE_RATE_HZ),
        samplerate=SAMPLE_RATE_HZ,
        channels=CHANNELS,
        dtype="int16",
        device=device,
    )
    rec_start = time.monotonic()

    try:
        input()
    except EOFError:
        pass

    elapsed_ms = (time.monotonic() - rec_start) * 1000
    if elapsed_ms < MIN_RECORDING_MS:
        remaining = (MIN_RECORDING_MS - elapsed_ms) / 1000
        print(f"[keep talking... {remaining:.1f}s more]")
        time.sleep(remaining)

    sd.stop()

    flat = recording.flatten()
    nonzero_idx = np.nonzero(flat)[0]
    if len(nonzero_idx) == 0:
        print("[no audio captured — mic may be muted]")
        return b""

    end = min(nonzero_idx[-1] + SAMPLE_RATE_HZ // 4, len(flat))
    pcm = flat[:end].tobytes()
    duration_ms = len(pcm) / (SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES) * 1000
    peak = int(np.abs(flat[:end]).max())
    print(f"[captured {duration_ms:.0f}ms, peak={peak}]")

    if peak < 100:
        print("[WARNING: very low audio — mic may be muted]")
    if peak > 30000:
        print("[WARNING: audio clipping — reduce mic volume to 60-70%]")

    return pcm


SILENCE_THRESHOLD = 300
SILENCE_STOP_SEC = 2.0
MAX_RECORD_SEC = 15.0

def auto_record(duration_sec: float = 15.0, device: int | None = None) -> bytes:
    """Record until lead stops talking (2s silence) or max duration.

    Like a real phone — listens until natural pause, not a fixed timer.
    """
    sd, np = _get_sounddevice()

    sd.stop()
    time.sleep(0.15)

    chunk_size = 1024
    chunks: list = []
    peak_level = 0
    silence_chunks = 0
    silence_limit = int(SILENCE_STOP_SEC * SAMPLE_RATE_HZ / chunk_size)
    speech_detected = False

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE_HZ, channels=CHANNELS,
        dtype="int16", device=device, blocksize=chunk_size,
    )
    stream.start()
    start = time.monotonic()

    try:
        while (time.monotonic() - start) < duration_sec:
            data, _ = stream.read(chunk_size)
            chunks.append(data.copy())
            level = int(np.abs(data).max())
            if level > peak_level:
                peak_level = level

            if level > SILENCE_THRESHOLD:
                speech_detected = True
                silence_chunks = 0
            else:
                silence_chunks += 1

            if speech_detected and silence_chunks >= silence_limit:
                break
    finally:
        stream.stop()
        stream.close()

    if not speech_detected or peak_level < 100:
        print("  [no speech detected]")
        return b""

    pcm = np.concatenate(chunks).tobytes()
    duration_ms = len(pcm) / (SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES) * 1000
    print(f"  [captured {duration_ms:.0f}ms, peak={peak_level}]")

    if peak_level > 30000:
        print("  [WARNING: clipping — reduce mic volume]")

    return pcm


def play_pcm(pcm: bytes, sample_rate: int) -> None:
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        raise SystemExit("sounddevice/numpy missing — see record_until_enter() msg")

    sd.stop()
    arr = np.frombuffer(pcm, dtype=np.int16)
    sd.play(arr, samplerate=sample_rate)
    sd.wait()
    sd.stop()


# -- Boot the harness ------------------------------------------------------

def _load_env() -> dict[str, str]:
    """Pull credentials, prefer apps/pipecat-agent/.env then os.environ."""
    try:
        from dotenv import dotenv_values  # type: ignore[import-not-found]
    except ImportError:
        dotenv_values = None

    env: dict[str, str] = {}
    if dotenv_values:
        env.update({k: v for k, v in dotenv_values(".env").items() if v})
    env.update({k: v for k, v in os.environ.items() if v})
    return env


def _build_deps(env: dict[str, str], http: httpx.AsyncClient) -> TurnDependencies:
    sarvam_key = env.get("SARVAM_API_KEY", "")
    # Rotate one Gemini key per call across GEMINI_API_KEYS (free-tier quota
    # spread + keeps us on Gemini instead of the slow Groq→Cerebras cascade).
    gemini_key = next_gemini_key() or env.get("GEMINI_API_KEY", "")
    gemini_model = env.get("GEMINI_MODEL", "gemini-2.5-flash")
    groq_key = env.get("GROQ_API_KEY", "")
    groq_model = env.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    cartesia_key = env.get("CARTESIA_API_KEY", "")
    cartesia_voice = env.get("CARTESIA_VOICE", "arushi")
    eleven_key = env.get("ELEVENLABS_API_KEY", "")
    eleven_voice = env.get("ELEVENLABS_VOICE_ID", "")
    eleven_model = env.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    smallest_key = env.get("SMALLEST_API_KEY", "")
    smallest_voice = env.get("SMALLEST_VOICE", SMALLEST_DEFAULT_VOICE)
    smallest_model = env.get("SMALLEST_MODEL", SMALLEST_DEFAULT_MODEL)
    smallest_rate = int(env.get("SMALLEST_SAMPLE_RATE", str(SMALLEST_DEFAULT_RATE)))
    smallest_speed = float(env.get("SMALLEST_SPEED", "1.0"))
    smallest_lang_hint = env.get("SMALLEST_LANG_HINT", "tamil_only")
    if not sarvam_key and not cartesia_key and not smallest_key:
        raise SystemExit("SARVAM_API_KEY, SMALLEST_API_KEY or CARTESIA_API_KEY must be set in .env")
    if not gemini_key and not groq_key:
        raise SystemExit("GEMINI_API_KEY or GROQ_API_KEY must be set in .env")

    # R2 is optional — without it the phrase cache simply always misses.
    try:
        r2_cfg = R2Config.from_env(env)
        r2 = R2Client(r2_cfg)
        r2_reader = r2
        r2_writer = r2
    except R2ConfigError as exc:
        print(f"[warn] R2 disabled ({exc}). Phrase cache will always miss.")
        r2_reader = _NoOpR2()
        r2_writer = _NoOpR2()

    gemini_primary = env.get("LLM_PRIMARY", "").strip().lower() == "gemini"
    if groq_key:
        if gemini_primary and gemini_key:
            print(f"[LLM: Gemini {gemini_model} primary, Groq {groq_model} fallback  (extraction: Groq)]")
        else:
            print(f"[LLM: Groq {groq_model}  (extraction: Groq)]")
        # Extract with Groq too — Gemini free tier 429s under live-call rate.
        llm_adapter = _GroqAdapter(
            api_key=groq_key, model=groq_model, client=http,
            extract_model=env.get("GROQ_EXTRACT_MODEL", "llama-3.1-8b-instant"),
            gemini_key="", gemini_model=gemini_model,
            fallback_gemini_key=gemini_key,
            fallback_gemini_model=gemini_model,
            alt_base_url=env.get("ALT_LLM_BASE_URL", ""),
            alt_api_key=env.get("ALT_LLM_API_KEY", ""),
            alt_model=env.get("ALT_LLM_MODEL", ""),
            gemini_primary=gemini_primary,
        )
    else:
        print(f"[LLM: Gemini {gemini_model}]")
        llm_adapter = _GeminiAdapter(api_key=gemini_key, model=gemini_model, client=http)

    # All-Sarvam voice mode: one Bulbul v3 speaker across hi/en/ta — the
    # SPC formula. The hybrid stacks below swap voices on language flip
    # (smallest meher → bulbul), which leads heard as "two different
    # people"; TTS_PROVIDER=sarvam pins one identity.
    tts_provider_override = env.get("TTS_PROVIDER", "").strip().lower()
    sarvam_speaker = env.get("SARVAM_TTS_SPEAKER", TTS_DEFAULT_SPEAKER)
    if tts_provider_override == "sarvam" and sarvam_key:
        print(f"[TTS: Sarvam Bulbul v3 speaker={sarvam_speaker} (single voice, all languages)]")
        tts_adapter = _SarvamTTSAdapter(api_key=sarvam_key, client=http, speaker=sarvam_speaker)
    elif smallest_key:
        smallest_adapter = _SmallestTTSAdapter(
            api_key=smallest_key, client=http, voice=smallest_voice,
            model=smallest_model, sample_rate=smallest_rate, speed=smallest_speed,
            lang_hint=smallest_lang_hint,
        )
        tamil_provider = env.get("SMALLEST_TAMIL_PROVIDER", "sarvam").strip().lower()
        if tamil_provider == "sarvam" and sarvam_key:
            print(f"[TTS: smallest.ai {smallest_voice} (hi/en) + Sarvam bulbul:v3 priya (ta)]")
            tts_adapter = _HybridTTSAdapter(
                primary=smallest_adapter,
                tamil=_SarvamTTSAdapter(api_key=sarvam_key, client=http),
            )
        elif tamil_provider == "cartesia" and cartesia_key:
            print(f"[TTS: smallest.ai {smallest_voice} (hi/en) + Cartesia nithya (ta)]")
            tts_adapter = _HybridTTSAdapter(
                primary=smallest_adapter,
                tamil=_CartesiaTTSAdapter(api_key=cartesia_key, client=http, voice="nithya"),
            )
        else:
            print(f"[TTS: smallest.ai {smallest_model} voice={smallest_voice} "
                  f"@ {smallest_rate}Hz (hi/en/ta single voice)]")
            tts_adapter = smallest_adapter
    elif eleven_key:
        if not eleven_voice:
            print("[warn] ELEVENLABS_VOICE_ID unset — using default (US accent). "
                  "Set an Indian Hindi female voice_id for natural Hindi.")
        el_adapter = _ElevenLabsTTSAdapter(
            api_key=eleven_key, client=http,
            voice_id=eleven_voice or "EXAVITQu4vr4xnSDxMaL", model=eleven_model,
        )
        if cartesia_key:
            print(f"[TTS: ElevenLabs {eleven_model} (hi/en) + Cartesia nithya (ta)]")
            tts_adapter = _HybridTTSAdapter(
                primary=el_adapter,
                tamil=_CartesiaTTSAdapter(api_key=cartesia_key, client=http, voice="nithya"),
            )
        else:
            print(f"[TTS: ElevenLabs {eleven_model}]")
            tts_adapter = el_adapter
    elif cartesia_key:
        print(f"[TTS: Cartesia Sonic-3.5 voice={cartesia_voice}]")
        tts_adapter = _CartesiaTTSAdapter(api_key=cartesia_key, client=http, voice=cartesia_voice)
    else:
        print("[TTS: Sarvam Bulbul v3]")
        tts_adapter = _SarvamTTSAdapter(api_key=sarvam_key, client=http)

    return TurnDependencies(
        stt=_SarvamSTTAdapter(api_key=sarvam_key, client=http),
        tts=tts_adapter,
        llm=llm_adapter,
        r2_reader=r2_reader,
        r2_writer=r2_writer,
    )


class _NoOpR2:
    """Fallback when R2 env vars aren't set. Pretends every key is missing."""

    async def get(self, key: str) -> bytes | None:
        return None

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        return None


async def run_local(args: argparse.Namespace) -> None:
    if args.list_devices:
        list_audio_devices()
        return

    env = _load_env()
    async with httpx.AsyncClient(timeout=30.0) as http:
        deps = _build_deps(env, http)

        ctx = make_initial_context(
            call_id="local-test",
            tenant_id=args.tenant_id,
            lead_id="local-lead",
            lead_first_name=args.lead_name,
            lead_company=args.lead_company,
            default_lang=args.lang,
        )

        print(
            f"\n=== Priya local harness ===\n"
            f"Lang: {args.lang}  Lead: {args.lead_name} @ {args.lead_company}\n"
            f"Hard cap: {HARD_CAP_SECONDS}s. Type 'q' + ENTER to quit.\n"
        )

        # ---- PRIYA STARTS FIRST (like a real outbound call) ----
        # On a real call, Priya delivers the intro BEFORE the lead speaks.
        from .prompts import build_intro_text
        from .tenant_config import get_tenant
        tenant_cfg = get_tenant(args.tenant_id)
        intro_text = build_intro_text(
            tenant=tenant_cfg, lang=args.lang, first_name=args.lead_name,
        )
        print(f"  PRIYA (intro): Synthesizing...")
        try:
            from .streaming_orchestrator import prepare_intro_for_tts
            intro_spoken = prepare_intro_for_tts(
                intro_text, args.lang, tenant_cfg.pronunciation_pack
            )
            intro_audio = await deps.tts.synth(intro_spoken, args.lang)
            print(f"  PRIYA: {intro_text}")
            try:
                intro_pcm, intro_sr = wav_bytes_to_pcm(intro_audio)
                play_pcm(intro_pcm, intro_sr)
            except Exception:
                print("  [intro playback failed]")
        except Exception as exc:
            print(f"  [intro TTS failed: {exc}]")
        print()

        slots = QualificationSlots()
        sdeps = StreamingDependencies(
            stt=deps.stt, tts=deps.tts, llm=deps.llm,
            r2_reader=deps.r2_reader, r2_writer=deps.r2_writer,
        )
        device = args.device

        auto_record_sec = args.record_seconds

        while True:
            if ctx.should_hard_stop():
                print("[hard cap reached — ending call]")
                break

            if auto_record_sec > 0:
                print(f"\n  [listening...]")
                pcm = auto_record(duration_sec=MAX_RECORD_SEC, device=device)
            else:
                line = input("Press ENTER to record (or 'q' to quit): ").strip()
                if line.lower() == "q":
                    break
                pcm = record_until_enter(device=device)

            if not pcm:
                print("[no speech detected]")
                continue

            wav = pcm_to_wav_bytes(pcm)
            t0 = time.monotonic()

            sentence_count = 0
            rest_pcm_parts: list[bytes] = []
            playback_sr = TTS_OUTPUT_SAMPLE_RATE

            async for event in run_turn_streaming(
                ctx=ctx, audio_in=wav, deps=sdeps, prior_slots=slots,
            ):
                if isinstance(event, AudioChunkEvent):
                    sentence_count += 1
                    if sentence_count == 1:
                        first_audio_ms = int((time.monotonic() - t0) * 1000)
                        print(f"\n  [{first_audio_ms}ms] ", end="", flush=True)
                    print(f"{event.text} ", end="", flush=True)
                    try:
                        chunk_pcm, playback_sr = wav_bytes_to_pcm(event.audio)
                        if sentence_count == 1:
                            play_pcm(chunk_pcm, playback_sr)
                        else:
                            rest_pcm_parts.append(chunk_pcm)
                    except Exception:
                        pass
                elif isinstance(event, TurnCompleteEvent):
                    slots = event.slots
                    wall_ms = int((time.monotonic() - t0) * 1000)
                    lm = event.latency_ms
                    print(
                        f"\n  LEAD: {event.lead_text}"
                        f"\n  [{ctx.turn_idx}|{ctx.conversation_state.phase.value}|"
                        f"stt={lm.get('stt_ms', 0)}|llm={lm.get('llm_first_sentence_ms', 0)}|"
                        f"tts={lm.get('tts_first_sentence_ms', 0)}|wall={wall_ms}ms]"
                    )

            if rest_pcm_parts:
                play_pcm(b"".join(rest_pcm_parts), playback_sr)

            time.sleep(0.3)

        print("\n=== Call summary ===")
        print(f"  turns:        {ctx.turn_idx}")
        print(f"  elapsed:      {ctx.elapsed():.1f}s")
        print(f"  billed units: {ctx.billed_units()}")
        print(f"  cache hits:   {ctx.phrase_cache_hits}")
        print(f"  final score:  {slots.score(frozenset())}")


def main() -> None:
    p = argparse.ArgumentParser(prog="voice_agent.local_audio")
    p.add_argument("--lang", default="hi-IN", choices=["hi-IN", "en-IN", "ta-IN"])
    p.add_argument("--lead-name", default="Suresh")
    p.add_argument("--lead-company", default="Acme Chemicals")
    p.add_argument("--tenant-id", default="spc-tenant")
    p.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    p.add_argument("--device", type=int, default=None, help="Input device index (from --list-devices)")
    p.add_argument("--record-seconds", type=float, default=8.0, help="Auto-record duration (0=press-enter mode)")
    args = p.parse_args()
    asyncio.run(run_local(args))


if __name__ == "__main__":
    main()
