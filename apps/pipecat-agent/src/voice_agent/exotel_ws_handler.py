"""FastAPI WebSocket handler for Exotel Voice Streaming.

Exotel opens a WebSocket to us when a call connects. The handler:

  1. Reads inbound μ-law audio chunks from the lead.
  2. Buffers them until a silence threshold (simple VAD) or a max-buffer.
  3. Converts buffer → WAV PCM → Sarvam STT (via the orchestrator).
  4. Sends Priya's TTS audio (μ-law) back over the same WS.

The orchestrator drives all conversation logic — this file only handles
the audio framing + WS lifecycle. Per-call CallContext lives in memory
keyed by Exotel's stream_sid.

Mounted under voice_agent.server at:

  WS  /exotel/stream/{call_id}
  POST /exotel/calls          (place outbound + return call_sid)
"""
from __future__ import annotations

import array
import asyncio
import datetime
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from .audio_codec import apply_gain, exotel_pcm_to_wav_for_stt, tts_wav_to_exotel_pcm
from .exotel_transport import (
    ExotelError,
    ExotelStreamSession,
    OutboundCallRequest,
    StreamMediaFrame,
    StreamStartFrame,
    StreamStopFrame,
    hangup_call,
    place_outbound_call,
)
from .pipeline import HARD_CAP_SECONDS, CallContext, make_initial_context
from .prompts import build_intro_text
from .qualification import QualificationSlots
from .tenant_config import TenantConfig, TenantNotFound, get_tenant
from .r2_client import R2Client, R2Config, R2ConfigError
from .sarvam_stt import STTResult
from .sarvam_streaming_stt import SarvamStreamingSTT
from .streaming_orchestrator import (
    AudioChunkEvent,
    StreamingDependencies,
    TurnCompleteEvent,
    prepare_intro_for_tts,
    run_turn_streaming,
    transcript_unfinished,
)
from .supabase_client import (
    AgentSupabaseClient,
    SupabaseConfig,
    SupabaseConfigError,
    persist_turn_async,
)
from .turn_orchestrator import TurnDependencies, run_turn

logger = logging.getLogger(__name__)

router = APIRouter()


# -- Human-readable per-call transcript log --------------------------------
#
# Appends every turn (what the lead said + detected language + confidence,
# what Priya replied in which language, intent, and latency) to a flat file
# so the conversation — words, slang, language switches, smoothness — can be
# reviewed after a call. Override path with CALL_LOG_PATH; off if set to "".
_CALL_LOG_PATH = os.environ.get(
    "CALL_LOG_PATH",
    str(Path(__file__).resolve().parents[2] / "call-logs.txt"),
)


def _clog(call_id: str, kind: str, msg: str) -> None:
    """Log one call event to stderr AND append to the transcript file."""
    short = call_id[:8]
    logger.info("[%s] %s: %s", short, kind, msg)
    if not _CALL_LOG_PATH:
        return
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        with open(_CALL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{short}] {kind:6} {msg}\n")
    except Exception:
        logger.debug("call-log write failed", exc_info=True)


# -- In-process call registry ----------------------------------------------
#
# Maps call_id → CallContext + slots. Lives only as long as the process.
# For multi-instance deployment we'd push this to Redis; SPC's demo runs
# on one Hetzner box so an in-memory dict is fine for now.

@dataclass
class _ActiveCall:
    ctx: CallContext
    slots: QualificationSlots
    deps: TurnDependencies
    # Resolved once at trigger time so every WS-side branch (intro fallback,
    # mid-call prompt rebuild, end-of-call hook) has the same view of who
    # this agent is. Never None for an active call — trigger refuses to
    # register the call without a valid tenant.
    tenant: TenantConfig | None = None
    db: AgentSupabaseClient | None = None
    # Intro audio pre-synthesized at dial time (during the ring) so there is
    # zero dead air after pickup — the gap the lead perceived as a spam "second
    # ring". Falls back to live synth on connect if not ready in time.
    intro_audio: bytes | None = None
    intro_text: str | None = None
    # Exotel's CallSid for this call leg, set after place_outbound_call returns.
    # Needed to call Exotel REST hangup explicitly when the agent decides to
    # end (otherwise closing only the WS can leave the phone line open).
    exotel_call_sid: str | None = None
    # Full transcript captured turn-by-turn so the post-call scorer has the
    # whole conversation, not just the rolling window in conversation_state.
    transcript: list[dict[str, str]] = field(default_factory=list)
    # Lead's destination phone (E.164) captured from the trigger payload.
    # Needed for the post-call WhatsApp confirmation — Exotel's status
    # callback doesn't echo the original `to` field reliably across regions.
    lead_phone: str = ""


_active_calls: dict[str, _ActiveCall] = {}

# Strong refs to fire-and-forget background tasks (intro pre-synth) so the
# event loop doesn't garbage-collect them before they finish.
_bg_tasks: set = set()

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(s: str | None) -> bool:
    """True iff s looks like a real UUID — used to gate DB writes so we never
    POST a placeholder like 'call-1e4b...' to a uuid column."""
    return bool(s) and bool(_UUID_RE.match(s))


# call_id of the most recently triggered outbound call. Exotel's static
# Voicebot applet URL means the WS arrives with no CustomField to match on,
# so for the (single-concurrent) demo we fall back to this — that's the call
# we just dialed, carrying the right lead name + language.
_last_pending_call_id: str | None = None


# -- Inbound-audio buffering (simple silence VAD) ---------------------------

# Exotel AgentStream sends ~100ms raw 16-bit PCM chunks (3200 bytes at
# 16 kHz, 1600 at 8 kHz). We accumulate them and flush to STT when either:
#   - silence threshold met (low peak amplitude for `SILENCE_MS_THRESHOLD`)
#   - hard buffer cap reached (avoids runaway when lead never pauses)

# ms of quiet → assume the lead finished talking. Higher = Priya waits longer
# before replying (more polite, won't cut off a slow speaker) but adds that
# much latency. 700 is snappy; 850-1000 feels more human on Indian calls.
SILENCE_MS_THRESHOLD = int(os.environ.get("EXOTEL_SILENCE_MS", "750"))
MAX_BUFFER_MS = 8000         # hard cap so STT call doesn't grow unbounded
MIN_UTTERANCE_MS = 400       # noise floor — drop buffers shorter than this

# Stream sample rate must match the Voicebot applet's configured rate.
EXOTEL_STREAM_SAMPLE_RATE = int(os.environ.get("EXOTEL_STREAM_SAMPLE_RATE", "8000"))

# Output volume boost. TTS sits below telephony full-scale, so Priya can sound
# faint on a phone earpiece. 1.0 = off; 1.4-1.8 lifts her; >2 risks clipping.
EXOTEL_TTS_GAIN = float(os.environ.get("EXOTEL_TTS_GAIN", "1.0"))

# Silent PCM prepended to every TTS chunk so the cellular channel can stabilize
# before the first syllable. Without this, words like "Vanakkam" can lose their
# leading "Va-" on the line. 30-60ms is imperceptible to the listener.
EXOTEL_LEAD_SILENCE_MS = int(os.environ.get("EXOTEL_LEAD_SILENCE_MS", "50"))

# Inter-sentence silent pad (ms). The streaming pipeline yields each sentence
# as a separate WAV; without a small gap between them, the cellular channel
# blends the trailing consonant of sentence N into the opening of sentence N+1,
# which is what listeners hear as "the words are running together / overlapping".
# Tamil is most sensitive — the bulbul model already pronounces slightly fast,
# so we pad more for ta-IN. Tunable via env.
EXOTEL_SENTENCE_GAP_MS = int(os.environ.get("EXOTEL_SENTENCE_GAP_MS", "120"))
EXOTEL_SENTENCE_GAP_MS_TA = int(os.environ.get("EXOTEL_SENTENCE_GAP_MS_TA", "180"))

# Peak-amplitude threshold below which a raw-PCM chunk counts as "silent".
# Mirrors the local harness VAD (SILENCE_THRESHOLD=300).
_PCM_SILENCE_THRESHOLD = 300

# Barge-in: let the lead interrupt Priya mid-sentence. While she speaks we
# normally stay half-duplex, but LOUD + SUSTAINED speech is treated as a real
# interruption: flush her queued audio and start listening. The threshold sits
# well above Priya's own (attenuated) echo, and the orchestrator's echo-overlap
# guard is a second safety net so a false trigger degrades to "(silence)"
# rather than derailing the call. Disable on an echoey line with EXOTEL_BARGE_IN=0.
BARGE_IN_ENABLED = os.environ.get("EXOTEL_BARGE_IN", "1").strip().lower() not in (
    "0", "false", "no", "",
)

# Streaming STT (Sarvam saaras:v3 over WebSocket). Audio streams to Sarvam
# WHILE the lead talks; the server's model-based VAD endpoints the utterance
# and the final transcript lands ~150ms later — replacing BOTH the local
# 750ms amplitude-silence wait AND the 350-2500ms batch STT POST. The local
# buffer+batch path below stays as the automatic fallback if the Sarvam WS
# fails to connect or dies mid-call. Disable with EXOTEL_STREAMING_STT=0.
STREAMING_STT_ENABLED = os.environ.get(
    "EXOTEL_STREAMING_STT", "1"
).strip().lower() not in ("0", "false", "no", "")

# After Sarvam finalizes an utterance, hold the turn for this grace window —
# if the lead was only pausing mid-sentence, the next segment arrives and is
# MERGED into one utterance (the "answers half-questions" fix, done at the
# source). The hold extends while Sarvam reports speech is still active,
# capped at STREAM_MAX_HOLD_SEC so a stuck VAD flag can't stall the call.
STREAM_MERGE_GRACE_SEC = int(
    os.environ.get("EXOTEL_STREAM_MERGE_GRACE_MS", "250")
) / 1000.0
STREAM_MAX_HOLD_SEC = 4.0
# Extra one-shot hold when the merged transcript looks cut off mid-sentence
# ("Budget is around" — dangling connective / no terminal punctuation). The
# lead is mid-thought; give them one longer beat to finish before answering
# a fragment. Applied at most once per utterance so a lead who really does
# trail off still gets a reply within grace + this.
STREAM_DANGLING_HOLD_SEC = int(
    os.environ.get("EXOTEL_STREAM_DANGLING_MS", "700")
) / 1000.0
_BARGE_IN_PCM_THRESHOLD = int(os.environ.get("EXOTEL_BARGE_IN_THRESHOLD", "2500"))
BARGE_IN_MS = int(os.environ.get("EXOTEL_BARGE_IN_MS", "500"))


def _is_silent_pcm(pcm: bytes, threshold: int = _PCM_SILENCE_THRESHOLD) -> bool:
    """Rough VAD on signed-16 little-endian PCM: peak below threshold = silent."""
    if len(pcm) < 2:
        return True
    arr = array.array("h")
    arr.frombytes(pcm[: len(pcm) // 2 * 2])
    if not arr:
        return True
    return max(abs(s) for s in arr) < threshold


def _is_loud_voiced(pcm: bytes, threshold: int = _BARGE_IN_PCM_THRESHOLD) -> bool:
    """Peak at/above `threshold` = loud enough to be the lead interrupting
    (not Priya's attenuated echo). Used only for barge-in detection."""
    if len(pcm) < 2:
        return False
    arr = array.array("h")
    arr.frombytes(pcm[: len(pcm) // 2 * 2])
    if not arr:
        return False
    return max(abs(s) for s in arr) >= threshold


def _chunk_ms(pcm: bytes, sample_rate: int) -> int:
    """Duration in ms of a raw-PCM chunk (2 bytes/sample, mono)."""
    return int((len(pcm) // 2) / sample_rate * 1000)


# Half-duplex: we stream Priya's whole reply into Exotel's buffer instantly,
# but it PLAYS over several seconds. While it plays we ignore inbound audio —
# otherwise we transcribe her own echo and she talks over herself ("rapping").
# This is time-based, not silence-based, because we can't reliably hear
# playback end on a phone line.
#
# RETIRED 2026-06-13: the extra post-playback deaf tail (SPEAK_TAIL_SEC=0.7)
# ate the first words of fast answers — leads answer the moment the question
# lands ("Anna Nagar" ×5 unheard, call f838d0d5). Stray echo right after
# playback is handled by the orchestrator's echo-skip instead.

# Only run a turn when the lead actually SPOKE this much (non-silent audio).
# Pure silence/comfort-noise must never trigger a response, or Priya nags
# "Sir, sun pa rahe hain?" on every quiet moment.
MIN_VOICED_MS = 350

# Outbound frames to Exotel must be small (multiples of 320 bytes / ~100ms).
# 1600 bytes = 800 samples = 100ms at 8 kHz. We slice TTS audio into these.
_OUT_FRAME_BYTES = 1600


def _audio_dur_sec(pcm: bytes, sample_rate: int) -> float:
    """Playback duration of raw 16-bit mono PCM."""
    return (len(pcm) // 2) / sample_rate


# Streaming TTS holds a persistent WS to Sarvam; deps are rebuilt per call,
# so the instance lives at module scope and is shared across calls.
_streaming_tts: Any = None


def _get_streaming_tts(api_key: str, speaker: str):
    global _streaming_tts
    if _streaming_tts is None or _streaming_tts.speaker != speaker:
        from .sarvam_tts_ws import SarvamStreamingTTS

        _streaming_tts = SarvamStreamingTTS(
            api_key=api_key,
            speaker=speaker,
            sample_rate=EXOTEL_STREAM_SAMPLE_RATE,
        )
    return _streaming_tts


async def _send_pcm_chunked(session: ExotelStreamSession, pcm: bytes) -> None:
    """Send raw PCM to Exotel in small, applet-friendly frames."""
    for i in range(0, len(pcm), _OUT_FRAME_BYTES):
        await session.send_audio(pcm[i : i + _OUT_FRAME_BYTES])


async def _play_wav(
    session: ExotelStreamSession, active: _ActiveCall, wav: bytes, text: str
) -> float:
    """Stream already-synthesized WAV to the lead, record it as a Priya turn.
    Returns the audio's playback duration in seconds (for the mute window)."""
    pcm = tts_wav_to_exotel_pcm(
        wav, EXOTEL_STREAM_SAMPLE_RATE,
        gain=EXOTEL_TTS_GAIN, lead_silence_ms=EXOTEL_LEAD_SILENCE_MS,
    )
    await _send_pcm_chunked(session, pcm)
    if text.strip():
        active.ctx.conversation_state.record_priya_turn(text)
    return _audio_dur_sec(pcm, EXOTEL_STREAM_SAMPLE_RATE)


async def _play_text(
    session: ExotelStreamSession, active: _ActiveCall, text: str
) -> float:
    """Synthesize the intro `text` live, then stream it. Slower path — prefer
    pre-synth. Runs the text through prepare_intro_for_tts so the tenant
    pronunciation pack (e.g. "XYZ Broker" -> "Eks Why Zee Broker") + Tamil
    pacing are applied — otherwise the greeting is the one line that NEVER
    got pack treatment, which is why the company/area names came out garbled."""
    if not text.strip():
        return 0.0
    lang = active.ctx.language_state.current.value
    pack = active.tenant.pronunciation_pack if active.tenant is not None else None
    spoken = prepare_intro_for_tts(text, lang, pack)
    wav = await active.deps.tts.synth(spoken, lang)
    # Record the ORIGINAL text (not the pacing-mangled form) for echo/dedupe.
    return await _play_wav(session, active, wav, text)


async def _presynth_intro(active: _ActiveCall, text: str) -> None:
    """Synthesize the intro during the ring so pickup has zero dead air.

    The text is pack-substituted + paced via prepare_intro_for_tts before
    synthesis so the pre-rendered greeting audio pronounces the company and
    locality names correctly (the live path does the same)."""
    try:
        lang = active.ctx.language_state.current.value
        pack = active.tenant.pronunciation_pack if active.tenant is not None else None
        spoken = prepare_intro_for_tts(text, lang, pack)
        active.intro_audio = await active.deps.tts.synth(spoken, lang)
    except Exception:
        logger.exception("intro pre-synth failed; will synth live on connect")


# -- Outbound trigger endpoint ---------------------------------------------

class PlaceCallRequest(BaseModel):
    to: str = Field(..., description="E.164 lead number, e.g. +919876543210")
    from_: str | None = Field(None, alias="from", description="ExoPhone (defaults to EXOTEL_FROM_NUMBER)")
    lead_first_name: str | None = None
    lead_company: str | None = None
    lang_hint: str = "hi-IN"
    # Required — resolved via tenant_config.get_tenant() at trigger time. An
    # unknown id rejects the call with 400 (we never silently fall back to
    # a default tenant — that's how SPC strings used to leak into other clients).
    tenant_id: str = Field(..., description="Resolves to TenantConfig at boot")
    lead_id: str | None = None


class PlaceCallResponse(BaseModel):
    call_sid: str
    status: str
    flow_url: str


@router.post("/exotel/calls", response_model=PlaceCallResponse)
async def trigger_outbound_call(req: PlaceCallRequest) -> PlaceCallResponse:
    """Place an outbound Exotel call. Returns the Exotel call_sid synchronously.

    Exotel dials the lead, then runs the App flow (EXOTEL_FLOW_URL) whose
    Voicebot applet opens a WebSocket to /exotel/stream/{call_id}. The
    applet's WSS URL is configured in App Bazaar (static); we correlate the
    pre-built context via CustomField=call_id, echoed in the start frame.
    """
    sid = os.environ.get("EXOTEL_SID", "")
    api_key = os.environ.get("EXOTEL_API_KEY", "")
    api_token = os.environ.get("EXOTEL_API_TOKEN", "")
    region = os.environ.get("EXOTEL_REGION", "")
    caller_id = req.from_ or os.environ.get("EXOTEL_FROM_NUMBER", "")
    flow_url = os.environ.get("EXOTEL_FLOW_URL", "").strip()
    if not (sid and api_key and api_token and caller_id and flow_url):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "EXOTEL_SID / EXOTEL_API_KEY / EXOTEL_API_TOKEN / EXOTEL_FROM_NUMBER / "
            "EXOTEL_FLOW_URL must be set",
        )

    # Resolve tenant FIRST — a bad tenant_id is the kind of failure we want
    # loud (400 returned synchronously), not silent (call dialed with the
    # wrong agent identity). Never falls back to a default tenant.
    try:
        tenant = get_tenant(req.tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown tenant_id={req.tenant_id!r}: {exc}",
        ) from exc

    # call_id MUST be a real uuid4 — calls.id is a uuid column and downstream
    # writes (transcripts, turn_latencies, lead_scores) FK to it. The earlier
    # "call-{hex}" scheme caused every persist to 400 with 22P02.
    call_id = str(uuid.uuid4())

    # Pre-build the CallContext + dependencies. Keyed by call_id; picked up
    # when Exotel's WS connects and reports CustomField=call_id.
    deps = _build_deps_from_env()
    ctx = make_initial_context(
        call_id=call_id,
        tenant_id=req.tenant_id,
        # lead_id falls back to call_id only for ad-hoc trial calls without a
        # real lead row; DB persistence is gated on _is_uuid(lead_id) so a
        # made-up lead_id won't trigger a FK violation.
        lead_id=req.lead_id or call_id,
        lead_first_name=req.lead_first_name,
        lead_company=req.lead_company,
        default_lang=req.lang_hint,
        industry_key=tenant.industry_key,
    )
    db = _build_db_client()
    active = _ActiveCall(
        ctx=ctx, slots=QualificationSlots(), deps=deps, tenant=tenant, db=db,
        lead_phone=req.to,
    )
    _active_calls[call_id] = active
    global _last_pending_call_id
    _last_pending_call_id = call_id

    # Insert the calls row NOW so per-turn transcripts have a valid FK target.
    # insert_call() self-skips unless all three of call_id/tenant_id/lead_id
    # are real UUIDs, so ad-hoc trial calls (default-tenant sentinel) remain
    # a no-op and don't spam 23503 errors mid-call.
    if db is not None:
        _ins_task = asyncio.create_task(
            db.insert_call(
                call_id=call_id,
                tenant_id=req.tenant_id,
                lead_id=req.lead_id or call_id,
                lang=req.lang_hint,
            )
        )
        _bg_tasks.add(_ins_task)
        _ins_task.add_done_callback(_bg_tasks.discard)

    # Pre-synthesize the intro NOW, while the phone is still ringing, so the
    # first word plays the instant the stream opens — no dead air the lead
    # could mistake for a spam "second ring".
    active.intro_text = build_intro_text(
        tenant=tenant,
        lang=ctx.language_state.current.value,
        first_name=ctx.lead_first_name,
    )
    _task = asyncio.create_task(_presynth_intro(active, active.intro_text))
    _bg_tasks.add(_task)
    _task.add_done_callback(_bg_tasks.discard)

    status_cb_base = os.environ.get("EXOTEL_STATUS_CALLBACK_URL", "").rstrip("/")
    status_callback = (
        f"{status_cb_base}/exotel/status/{call_id}" if status_cb_base else None
    )

    try:
        resp = await place_outbound_call(
            request=OutboundCallRequest(
                to=req.to,
                caller_id=caller_id,
                flow_url=flow_url,
                custom_field=call_id,
                status_callback=status_callback,
                record=True,
                time_limit_seconds=HARD_CAP_SECONDS,
            ),
            account_sid=sid,
            api_key=api_key,
            api_token=api_token,
            region=region,
        )
    except ExotelError as exc:
        _active_calls.pop(call_id, None)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"exotel: {exc}") from exc

    active.exotel_call_sid = resp.call_sid
    return PlaceCallResponse(
        call_sid=resp.call_sid, status=resp.status, flow_url=flow_url
    )


# -- WebSocket handler ------------------------------------------------------

def _resolve_active_call(path_call_id: str, custom_field: str | None) -> tuple[str, _ActiveCall]:
    """Find the pre-built call context for this WS connection.

    The Voicebot applet's WSS URL is static in App Bazaar, so the path
    `call_id` may be a placeholder (e.g. "live"). The authoritative key is
    the CustomField echoed in the start frame. Falls back to the path id,
    then bootstraps a fresh context so we never drop a live call.
    """
    for key in (custom_field, path_call_id, _last_pending_call_id):
        if key and key in _active_calls:
            if key == _last_pending_call_id and key not in (custom_field, path_call_id):
                logger.info("WS matched last-pending call_id=%s (name carried)", key)
            return key, _active_calls[key]

    incoming = custom_field or path_call_id
    # Always upgrade the key to a real UUID — DB writes are no-ops on
    # non-UUID call_ids (see persist_turn_async guard), but at least the
    # in-memory ctx is consistent and ready if persistence gets enabled.
    call_id = incoming if _is_uuid(incoming) else str(uuid.uuid4())
    logger.warning(
        "WS start for unknown call_id=%s (incoming=%s); bootstrapping default ctx",
        call_id, incoming,
    )
    active = _ActiveCall(
        ctx=make_initial_context(
            call_id=call_id, tenant_id="unknown", lead_id=call_id,
            lead_first_name=None, lead_company=None, default_lang="hi-IN",
        ),
        slots=QualificationSlots(),
        deps=_build_deps_from_env(),
    )
    _active_calls[call_id] = active
    return call_id, active


@router.websocket("/exotel/stream/{call_id}")
async def exotel_stream(ws: WebSocket, call_id: str) -> None:
    """Exotel opens this WS when the call connects. Drives one full conversation."""
    await ws.accept()

    session = ExotelStreamSession(_FastapiWSAdapter(ws))
    active: _ActiveCall | None = None
    buffer = bytearray()
    silence_ms = 0
    buffered_ms = 0
    voiced_ms = 0  # how much actual (non-silent) speech is in the buffer
    client_gone = False  # set when the lead hangs up mid-reply (send fails)
    barge_voiced_ms = 0  # loud speech heard *while Priya is talking* (barge-in)
    # Wall-clock time until which Priya is still speaking; ignore inbound
    # audio until then so she doesn't transcribe her own echo.
    speaking_until = 0.0
    # Streaming-STT state. pending_finals holds utterance segments Sarvam has
    # finalized but we haven't answered yet (merge-grace window may still be
    # open). None stt_stream = batch fallback path.
    stt_stream: SarvamStreamingSTT | None = None
    pending_finals: list[STTResult] = []
    pending_deadline = 0.0
    pending_first_at = 0.0
    pending_extended = False  # dangling-fragment hold used for this utterance

    try:
        async for frame in session:
            if isinstance(frame, StreamStartFrame):
                call_id, active = _resolve_active_call(call_id, frame.custom_field)
                logger.info(
                    "call_id=%s stream_sid=%s started (custom_field=%s)",
                    call_id, frame.stream_sid, frame.custom_field,
                )
                # Create the parent calls row up front so transcripts /
                # turn_latencies / qualification_slots can FK to it. Skip when
                # lead_id is not a real UUID (ad-hoc test calls) — the
                # persist_turn_async guard then no-ops every per-turn write.
                if (
                    active.db is not None
                    and _is_uuid(active.ctx.call_id)
                    and _is_uuid(active.ctx.lead_id)
                ):
                    try:
                        await active.db.insert_call(
                            call_id=active.ctx.call_id,
                            tenant_id=active.ctx.tenant_id,
                            lead_id=active.ctx.lead_id,
                            lang=active.ctx.language_state.current.value,
                        )
                    except Exception:
                        logger.exception("call_id=%s insert_call failed", call_id)
                # Priya opens the call — greet first, then wait for the lead.
                # Use the intro pre-synthesized at dial time (instant, no dead
                # air); fall back to live synth only if it isn't ready yet.
                try:
                    intro = active.intro_text or (
                        build_intro_text(
                            tenant=active.tenant,
                            lang=active.ctx.language_state.current.value,
                            first_name=active.ctx.lead_first_name,
                        )
                        if active.tenant is not None
                        else ""
                    )
                    if active.intro_audio is not None:
                        dur = await _play_wav(session, active, active.intro_audio, intro)
                        source = "pre-synth"
                    else:
                        dur = await _play_text(session, active, intro)
                        source = "live"
                    speaking_until = time.monotonic() + dur
                    logger.info(
                        "call_id=%s intro played (%s, %.1fs): %s",
                        call_id, source, dur, intro[:60],
                    )
                    _clog(
                        call_id, "START",
                        f"lang={active.ctx.language_state.current.value} "
                        f"lead={active.ctx.lead_first_name or '-'} | INTRO: {intro}",
                    )
                except Exception:
                    logger.exception("call_id=%s intro playback failed", call_id)
                # Open the Sarvam streaming-STT WS in the background (takes
                # ~1.2s) — it overlaps the intro playback, during which all
                # inbound audio is zero-fed anyway. If connect fails, the
                # session marks itself failed and we fall back to batch.
                if STREAMING_STT_ENABLED and os.environ.get("SARVAM_API_KEY"):
                    # PIN the STT to the call's known language instead of
                    # auto-detect. With lang=unknown, saaras re-guessed the
                    # language every utterance and rendered Hindi/Tamil
                    # speech in random Indic scripts (Gujarati "હા બોલો",
                    # Telugu "థర్టీ ఫైవ్", Punjabi "ਕਿਸ ਗੱਲ" — call
                    # 6d9dc0f8), which the language state machine then
                    # treated as garble. The call's language is known at
                    # dial time; pinning it is Sarvam's documented path to
                    # max accuracy on single-language calls (code-mixed
                    # English terms are still handled). Revert to auto with
                    # SARVAM_STT_PIN_LANG=0.
                    pinned = "unknown"
                    if os.environ.get("SARVAM_STT_PIN_LANG", "1") != "0":
                        try:
                            pinned = active.ctx.language_state.current.value
                        except Exception:
                            pinned = "unknown"
                    stt_stream = SarvamStreamingSTT(
                        api_key=os.environ["SARVAM_API_KEY"],
                        sample_rate=EXOTEL_STREAM_SAMPLE_RATE,
                        language_hint=pinned,
                    )

                    async def _start_stt(s: SarvamStreamingSTT = stt_stream) -> None:
                        try:
                            await s.start()
                        except Exception:
                            logger.exception(
                                "streaming STT connect failed — batch fallback"
                            )
                            s.failed = True

                    _stt_task = asyncio.create_task(_start_stt())
                    _bg_tasks.add(_stt_task)
                    _stt_task.add_done_callback(_bg_tasks.discard)
                buffer.clear()
                buffered_ms = silence_ms = voiced_ms = 0
                barge_voiced_ms = 0
                pending_finals.clear()
                pending_extended = False
                continue
            if isinstance(frame, StreamStopFrame):
                logger.info("call_id=%s stopped: %s", call_id, frame.reason)
                break
            if not isinstance(frame, StreamMediaFrame):
                continue
            if active is None:
                # Media before start (shouldn't happen) — bootstrap from path.
                call_id, active = _resolve_active_call(call_id, None)

            chunk = frame.audio_bytes
            chunk_ms = _chunk_ms(chunk, EXOTEL_STREAM_SAMPLE_RATE)

            # A dead Sarvam WS must never kill a phone call — drop to the
            # batch path for the rest of the call (one utterance may be lost
            # at the failure moment; the lead naturally repeats).
            if stt_stream is not None and stt_stream.failed:
                logger.warning(
                    "call_id=%s streaming STT died — batch STT fallback", call_id
                )
                _close_task = asyncio.create_task(stt_stream.close())
                _bg_tasks.add(_close_task)
                _close_task.add_done_callback(_bg_tasks.discard)
                stt_stream = None
                pending_finals.clear()
                pending_extended = False
            use_stream = stt_stream is not None

            # While Priya's reply is still playing (+ a settle tail) we are
            # half-duplex: most inbound audio is just her own echo. EXCEPT —
            # if barge-in is on and we hear LOUD, SUSTAINED speech during her
            # actual playback, treat it as the lead interrupting: flush her
            # queued audio and start listening immediately.
            now = time.monotonic()
            # Deaf only while audio is actually PLAYING. The old window
            # extended SPEAK_TAIL_SEC past playback and fed silence there
            # too — but fast leads answer inside that tail, so their first
            # words (or whole short answers: "Anna Nagar" said five times,
            # call f838d0d5) were never heard. Echo that leaks in right
            # after playback is absorbed by the orchestrator's echo-skip.
            if now < speaking_until:
                interrupted = False
                if BARGE_IN_ENABLED:
                    if _is_loud_voiced(chunk):
                        barge_voiced_ms += chunk_ms
                    else:
                        # Decay, don't hard-reset: real speech has micro-gaps
                        # between words; a single quiet frame used to zero the
                        # counter so barge-in effectively never fired.
                        barge_voiced_ms = max(0, barge_voiced_ms - chunk_ms)
                    interrupted = barge_voiced_ms >= BARGE_IN_MS
                if not interrupted:
                    buffer.clear()
                    buffered_ms = silence_ms = voiced_ms = 0
                    if use_stream:
                        # Keep the Sarvam WS alive + its VAD timeline
                        # continuous, but feed SILENCE instead of the line
                        # audio (which is mostly Priya's own echo). Anything
                        # it finalized from just before she spoke is stale —
                        # she already answered it.
                        await stt_stream.feed(b"\x00" * len(chunk))
                        pending_finals.clear()
                        pending_extended = False
                        while stt_stream.pop_final() is not None:
                            pass
                    if active.ctx.should_hard_stop():
                        await session.send_clear()
                        break
                    continue
                # Lead barged in — stop Priya now and capture their words.
                await session.send_clear()
                logger.info("call_id=%s barge-in — Priya yields to lead", call_id)
                speaking_until = 0.0
                barge_voiced_ms = 0
                buffer.clear()
                buffered_ms = silence_ms = voiced_ms = 0
                # fall through: this chunk starts the lead's interrupting turn.

            pre_transcribed: STTResult | None = None
            wav = b""
            if use_stream:
                # STREAMING path: every frame goes straight to Sarvam; its
                # model-based VAD endpoints the utterance server-side. Local
                # silence accounting / buffering is bypassed entirely.
                await stt_stream.feed(chunk)
                while True:
                    fin = stt_stream.pop_final()
                    if fin is None:
                        break
                    if not pending_finals:
                        pending_first_at = time.monotonic()
                    pending_finals.append(fin)
                    pending_deadline = time.monotonic() + STREAM_MERGE_GRACE_SEC
                if not pending_finals:
                    if active.ctx.should_hard_stop():
                        await session.send_clear()
                        break
                    continue
                # Merge-grace: hold the turn while the grace window is open
                # or Sarvam still hears the lead talking — a mid-sentence
                # pause then arrives as a second segment and is merged below
                # instead of being answered as a half-question.
                now = time.monotonic()
                held_too_long = now - pending_first_at > STREAM_MAX_HOLD_SEC
                if (now < pending_deadline or stt_stream.speech_active) and not held_too_long:
                    if active.ctx.should_hard_stop():
                        await session.send_clear()
                        break
                    continue
                merged_text = " ".join(
                    r.transcript for r in pending_finals if r.transcript
                ).strip()
                # Cut-off guard: "Budget is around" finalizing on a thinking
                # pause is a half-question — answering it literally derails
                # the call (56e606ca). One extra hold per utterance lets the
                # rest of the sentence arrive and merge.
                if (
                    not pending_extended
                    and not held_too_long
                    and transcript_unfinished(merged_text)
                ):
                    pending_extended = True
                    pending_deadline = now + STREAM_DANGLING_HOLD_SEC
                    _clog(call_id, "HOLD", f"dangling fragment, +{STREAM_DANGLING_HOLD_SEC:.1f}s: {merged_text[:60]}")
                    if active.ctx.should_hard_stop():
                        await session.send_clear()
                        break
                    continue
                last = pending_finals[-1]
                confidence = min(r.confidence for r in pending_finals)
                # Streaming STT reports confidence=1.00 unconditionally, and
                # its language tag on 1-2 word clips is a coin toss (logged:
                # Gujarati "ઓકે", Telugu "ఓకే" for plain "ok"). Scale short
                # merges below MIN_LANG_CONFIDENCE so the language state
                # machine ignores their tag instead of flipping the call.
                if len(merged_text.split()) <= 2:
                    confidence = min(confidence, 0.5)
                pre_transcribed = STTResult(
                    transcript=merged_text,
                    language_code=last.language_code,
                    confidence=confidence,
                    request_id=last.request_id,
                )
                if len(pending_finals) > 1:
                    _clog(
                        call_id, "MERGE",
                        f"{len(pending_finals)} segments -> one utterance",
                    )
                pending_finals = []
                pending_extended = False
            else:
                # BATCH fallback path: local amplitude VAD + buffered POST.
                silent = _is_silent_pcm(chunk)
                if silent:
                    silence_ms += chunk_ms
                else:
                    silence_ms = 0
                    voiced_ms += chunk_ms
                # Don't accumulate leading silence — only buffer once speech starts.
                if voiced_ms > 0:
                    buffer.extend(chunk)
                    buffered_ms += chunk_ms

                # Flush only when the lead actually spoke, then paused. Pure
                # silence never flushes → Priya stays quiet and waits naturally.
                should_flush = voiced_ms >= MIN_VOICED_MS and (
                    silence_ms >= SILENCE_MS_THRESHOLD or buffered_ms >= MAX_BUFFER_MS
                )
                if not should_flush:
                    if active.ctx.should_hard_stop():
                        await session.send_clear()
                        break
                    continue

                # Run the STREAMING orchestrator — audio chunks arrive as
                # sentences are generated, so the lead hears Priya's first
                # sentence ~1.5s after they stop talking (vs 8-10s sequential).
                wav = exotel_pcm_to_wav_for_stt(bytes(buffer), EXOTEL_STREAM_SAMPLE_RATE)
                buffer.clear()
                buffered_ms = silence_ms = voiced_ms = 0

            streaming_deps = StreamingDependencies(
                stt=active.deps.stt,
                tts=active.deps.tts,
                llm=active.deps.llm,
                r2_reader=active.deps.r2_reader,
                r2_writer=active.deps.r2_writer,
                voice_id=active.deps.voice_id,
                pronunciation_pack=(
                    active.tenant.pronunciation_pack
                    if active.tenant is not None
                    else {}
                ),
            )

            turn_end_call = False
            first_chunk_of_turn = True
            try:
                async for event in run_turn_streaming(
                    ctx=active.ctx,
                    audio_in=wav,
                    deps=streaming_deps,
                    prior_slots=active.slots,
                    pre_transcribed=pre_transcribed,
                ):
                    if isinstance(event, AudioChunkEvent):
                        try:
                            # First sentence of a turn: bigger pad so the
                            # channel stabilises before the opening syllable.
                            # Subsequent sentences: smaller "breath" gap so
                            # Priya doesn't sound like she's running words
                            # together — Tamil voice especially. Without this
                            # the trailing consonant of one sentence blends
                            # into the opening of the next on the cellular
                            # line, which leads complained about.
                            # Streaming TTS sends one sentence as MANY raw-PCM
                            # events; only the first carries text — pads apply
                            # at sentence starts, never mid-sentence (a pad
                            # between chunks is an audible stutter).
                            sentence_start = bool(event.text)
                            current_lang = (
                                active.ctx.language_state.current.value
                                if active.ctx.language_state else "hi-IN"
                            )
                            if first_chunk_of_turn:
                                pad_ms = EXOTEL_LEAD_SILENCE_MS
                            elif not sentence_start:
                                pad_ms = 0
                            elif current_lang == "ta-IN":
                                pad_ms = EXOTEL_SENTENCE_GAP_MS_TA
                            else:
                                pad_ms = EXOTEL_SENTENCE_GAP_MS
                            first_chunk_of_turn = False
                            if event.is_raw_pcm:
                                out_pcm = apply_gain(event.audio, EXOTEL_TTS_GAIN)
                                if pad_ms > 0:
                                    pad = bytes(
                                        2 * int(EXOTEL_STREAM_SAMPLE_RATE * pad_ms / 1000)
                                    )
                                    out_pcm = pad + out_pcm
                            else:
                                out_pcm = tts_wav_to_exotel_pcm(
                                    event.audio, EXOTEL_STREAM_SAMPLE_RATE,
                                    gain=EXOTEL_TTS_GAIN, lead_silence_ms=pad_ms,
                                )
                            await _send_pcm_chunked(session, out_pcm)
                            speaking_until = (
                                max(speaking_until, time.monotonic())
                                + _audio_dur_sec(out_pcm, EXOTEL_STREAM_SAMPLE_RATE)
                            )
                            if sentence_start:
                                _clog(
                                    call_id, "PRIYA",
                                    f"[{'cache' if event.used_cache else 'tts'} "
                                    f"s{event.sentence_idx}] {event.text}",
                                )
                        except (WebSocketDisconnect, RuntimeError) as exc:
                            # Lead hung up mid-reply — the Exotel WS is gone.
                            # Stop sending: every remaining chunk would throw
                            # and flood the logs (call 287e6c4d dumped 15
                            # tracebacks). Mark the client gone and bail out.
                            logger.info(
                                "call_id=%s client disconnected mid-send (%s) "
                                "— ending call", call_id, type(exc).__name__,
                            )
                            client_gone = True
                            break
                        except Exception:
                            logger.exception("audio chunk send failed")
                    elif isinstance(event, TurnCompleteEvent):
                        active.slots = event.slots
                        turn_end_call = event.end_call
                        lm = event.latency_ms
                        # Language flipped this turn (e.g. lead said "Tamil
                        # please") → re-pin the STT to the new language so it
                        # stops transcribing in the old one. Background task:
                        # the ~1s reconnect overlaps Priya's bridge line, and
                        # the lead isn't speaking yet. Only when we're pinning
                        # and on the streaming path.
                        if (
                            event.language_transition.switched
                            and stt_stream is not None
                            and not stt_stream.failed
                            and os.environ.get("SARVAM_STT_PIN_LANG", "1") != "0"
                        ):
                            _rp = asyncio.ensure_future(
                                stt_stream.repin(
                                    event.language_transition.current_language.value
                                )
                            )
                            _bg_tasks.add(_rp)
                            _rp.add_done_callback(_bg_tasks.discard)
                        _clog(
                            call_id, "LEAD",
                            f"[{event.lead_lang} conf={event.lead_confidence:.2f} "
                            f"intent={event.lead_intent}] {event.lead_text}",
                        )
                        _clog(
                            call_id, "TURN",
                            f"reply_lang={event.language_transition.current_language.value} "
                            f"stt={lm.get('stt_ms', 0)}ms "
                            f"llm={lm.get('llm_first_sentence_ms', 0)}ms "
                            f"tts={lm.get('tts_first_sentence_ms', 0)}ms "
                            f"total={lm.get('total_ms', 0)}ms",
                        )
                        if event.lead_text:
                            active.transcript.append({"speaker": "lead", "text": event.lead_text})
                        if event.priya_full_text:
                            active.transcript.append({"speaker": "priya", "text": event.priya_full_text})
                        persist_turn_async(
                            active.db,
                            call_id=active.ctx.call_id,
                            tenant_id=active.ctx.tenant_id,
                            lead_id=active.ctx.lead_id,
                            turn_idx=active.ctx.turn_idx - 1,
                            lead_text=event.lead_text,
                            lead_lang=event.lead_lang,
                            priya_text=event.priya_full_text,
                            slots_row=event.slots.to_db_row(
                                call_id=active.ctx.call_id,
                                tenant_id=active.ctx.tenant_id,
                                lead_id=active.ctx.lead_id,
                                turn_idx=active.ctx.turn_idx - 1,
                            ),
                            latency=event.latency_ms,
                        )
            except Exception:
                logger.exception("call_id=%s streaming orchestrator failure", call_id)

            if client_gone:
                break  # lead hung up — exit the frame loop, don't keep serving

            # Priya just spoke — reset capture. speaking_until (set per audio
            # chunk above) already keeps us deaf until her reply finishes.
            buffer.clear()
            buffered_ms = silence_ms = voiced_ms = 0
            barge_voiced_ms = 0
            pending_finals.clear()
            pending_extended = False

            if turn_end_call:
                # Let the goodbye line finish playing, then drop the call.
                # Closing only the WS isn't enough in some Voicebot-applet
                # flows — Exotel may keep the carrier leg open. Hit the REST
                # hangup endpoint to drop the phone line explicitly.
                wait = speaking_until - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait + 0.3)
                logger.info("call_id=%s hanging up (end_call)", call_id)
                try:
                    sid = os.environ.get("EXOTEL_SID", "")
                    api_key = os.environ.get("EXOTEL_API_KEY", "")
                    api_token = os.environ.get("EXOTEL_API_TOKEN", "")
                    region = os.environ.get("EXOTEL_REGION", "in")
                    if active.exotel_call_sid and sid and api_key and api_token:
                        await hangup_call(
                            call_sid=active.exotel_call_sid,
                            account_sid=sid,
                            api_key=api_key,
                            api_token=api_token,
                            region=region,
                        )
                        logger.info(
                            "call_id=%s exotel hangup sent (call_sid=%s)",
                            call_id, active.exotel_call_sid,
                        )
                except ExotelError as exc:
                    # Non-fatal: the WS close that follows still terminates the
                    # carrier leg cleanly. Most "Method not allowed" responses
                    # mean the API key lacks call-management scope — the
                    # account-level fix is in the Exotel dashboard, not here.
                    logger.warning(
                        "exotel hangup REST failed (%s); WS close will end the call",
                        exc,
                    )
                except Exception:
                    logger.exception("exotel hangup failed (continuing to WS close)")
                break

            if active.ctx.should_hard_stop():
                await session.send_clear()
                break
    except WebSocketDisconnect:
        logger.info("call_id=%s WS disconnected", call_id)
    finally:
        if stt_stream is not None:
            try:
                await stt_stream.close()
            except Exception:
                pass
        # Keep the slots/context for a short grace period so a webhook can
        # still read final state; in production push to DB instead.
        if active is not None:
            logger.info(
                "call_id=%s ended elapsed=%.1fs turns=%d cache_hits=%d billed_units=%d",
                call_id,
                active.ctx.elapsed(),
                active.ctx.turn_idx,
                active.ctx.phrase_cache_hits,
                active.ctx.billed_units(),
            )
            _clog(
                call_id, "END",
                f"elapsed={active.ctx.elapsed():.1f}s turns={active.ctx.turn_idx} "
                f"cache_hits={active.ctx.phrase_cache_hits}",
            )
        else:
            logger.info("call_id=%s ended before stream start (no audio)", call_id)


# -- StatusCallback webhook (Exotel POSTs after call ends) -----------------

@router.post("/exotel/status/{call_id}")
async def exotel_status_callback(call_id: str, request: Any = None) -> dict:
    """Exotel POSTs call completion data here (duration, status, recording URL).

    We merge it with the in-memory call state and persist to Supabase.
    This is the CRM integration point — each tenant's call outcome lands here.
    """
    from fastapi import Request as FastAPIRequest

    # Exotel sends form-encoded POST with: CallSid, Status, Duration,
    # RecordingUrl, From, To, Direction, StartTime, EndTime, etc.
    active = _active_calls.get(call_id)
    if active is None:
        logger.warning("status callback for unknown call_id=%s", call_id)
        return {"status": "ok", "call_id": call_id, "warning": "unknown_call"}

    logger.info(
        "call_id=%s status_callback: elapsed=%.1fs turns=%d billed=%d slots=%s",
        call_id,
        active.ctx.elapsed(),
        active.ctx.turn_idx,
        active.ctx.billed_units(),
        active.slots.to_summary(),
    )

    if active.db:
        try:
            await active.db.update_call_status(
                call_id=call_id,
                tenant_id=active.ctx.tenant_id,
                status="completed",
                billed_units=active.ctx.billed_units(),
                duration_sec=active.ctx.elapsed(),
                turns=active.ctx.turn_idx,
            )
        except Exception:
            logger.exception("call_id=%s failed to persist final status", call_id)

        # Post-call hot/warm/cold scoring — fire-and-forget so a slow Gemini
        # response never holds up the StatusCallback ack.
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key and _is_uuid(call_id) and _is_uuid(active.ctx.lead_id):
            async def _score_and_persist() -> None:
                try:
                    from .lead_scorer import score_call
                    result = await score_call(
                        transcript_turns=active.transcript,
                        slots=active.slots.to_db_row(
                            call_id=active.ctx.call_id,
                            tenant_id=active.ctx.tenant_id,
                            lead_id=active.ctx.lead_id,
                            turn_idx=active.ctx.turn_idx,
                        ),
                        api_key=gemini_key,
                    )
                    await active.db.insert_lead_score(
                        lead_id=active.ctx.lead_id,
                        call_id=call_id,
                        classification=result.classification,
                        score=result.score,
                        reason=result.reason,
                        summary=result.summary,
                        next_action=result.next_action,
                        extracted=result.extracted,
                    )
                    logger.info(
                        "call_id=%s scored: %s (%d) next=%s",
                        call_id, result.classification, result.score, result.next_action,
                    )

                    # Booking + WhatsApp hook. Fires only on hot/warm so cold
                    # numbers don't burn Meta template quality score. Each step
                    # fails open — a missed booking is recoverable by human
                    # follow-up; we just want to log what happened.
                    if active.tenant is not None:
                        try:
                            from .post_call_hook import run_post_call_hook
                            hook_extracted = result.extracted or {}
                            hook_result = await run_post_call_hook(
                                tenant=active.tenant,
                                classification=result.classification,
                                lead_first_name=active.ctx.lead_first_name,
                                lead_phone=active.lead_phone,
                                primary_pain=str(hook_extracted.get("primary_pain", ""))[:200],
                                broker_focus=str(hook_extracted.get("broker_focus", ""))[:120],
                            )
                            logger.info(
                                "call_id=%s post_call_hook: booked=%s wa=%s reason=%s meet=%s",
                                call_id,
                                hook_result.booked,
                                hook_result.whatsapp_sent,
                                hook_result.reason,
                                hook_result.meet_link or "-",
                            )
                        except Exception:
                            logger.exception(
                                "call_id=%s post_call_hook failed", call_id,
                            )
                except Exception:
                    logger.exception("call_id=%s post-call scoring failed", call_id)
            asyncio.create_task(_score_and_persist())

    _active_calls.pop(call_id, None)
    return {"status": "ok", "call_id": call_id}


# -- Adapters ---------------------------------------------------------------

class _FastapiWSAdapter:
    """Wrap FastAPI's WebSocket to look like the WebSocketLike protocol the
    ExotelStreamSession expects (which uses send/recv text)."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def send(self, data: str) -> None:
        await self._ws.send_text(data)

    async def recv(self) -> str:
        return await self._ws.receive_text()


# One keep-alive HTTP client for the whole process. A fresh per-call client
# paid full TLS handshakes to Sarvam/Groq/Smallest on every call — live logs
# showed 1.8-2.5s first-STT and ~2.2s first-TTS spikes that vanish once the
# connections are pooled and warm.
_shared_http: httpx.AsyncClient | None = None


def _get_shared_http() -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is None or _shared_http.is_closed:
        _shared_http = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(
                max_connections=24,
                max_keepalive_connections=12,
                keepalive_expiry=60.0,
            ),
        )
    return _shared_http


def _build_deps_from_env() -> TurnDependencies:
    """Build TurnDependencies from env vars. Mirrors local_audio._build_deps so
    the phone path uses the SAME low-latency stack as the local harness:
    Sarvam STT + Groq LLM + sentence-streamed TTS.

    All adapters share one keep-alive httpx client (see _get_shared_http)."""
    from .local_audio import (
        TTS_DEFAULT_SPEAKER,
        _CartesiaTTSAdapter,
        _ElevenLabsTTSAdapter,
        _GeminiAdapter,
        _GroqAdapter,
        _HybridTTSAdapter,
        _NoOpR2,
        _SarvamSTTAdapter,
        _SarvamTTSAdapter,
        _SmallestTTSAdapter,
    )

    sarvam_key = os.environ.get("SARVAM_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
    cartesia_voice = os.environ.get("CARTESIA_VOICE", "arushi")
    eleven_key = os.environ.get("ELEVENLABS_API_KEY", "")
    eleven_voice = os.environ.get("ELEVENLABS_VOICE_ID", "")
    eleven_model = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    smallest_key = os.environ.get("SMALLEST_API_KEY", "")
    smallest_voice = os.environ.get("SMALLEST_VOICE", "meher")
    smallest_model = os.environ.get("SMALLEST_MODEL", "lightning_v3.1_pro")
    smallest_rate = int(os.environ.get("SMALLEST_SAMPLE_RATE", "16000"))
    smallest_speed = float(os.environ.get("SMALLEST_SPEED", "1.0"))
    smallest_lang_hint = os.environ.get("SMALLEST_LANG_HINT", "tamil_only")
    if not sarvam_key:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SARVAM_API_KEY must be set (STT)",
        )
    if not groq_key and not gemini_key:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "GROQ_API_KEY or GEMINI_API_KEY must be set (LLM)",
        )

    http = _get_shared_http()

    try:
        r2_cfg = R2Config.from_env()
        r2 = R2Client(r2_cfg)
        r2_reader: Any = r2
        r2_writer: Any = r2
    except R2ConfigError as exc:
        logger.warning("R2 disabled (%s); phrase cache will always miss", exc)
        r2_reader = _NoOpR2()
        r2_writer = _NoOpR2()

    if groq_key:
        # Slot extraction runs on every turn. Gemini's free tier 429s under
        # live-call rate, so when Groq is available we extract with Groq too
        # (fast, reliable) by NOT handing the adapter a Gemini extraction
        # key. BUT we still wire Gemini as the streaming-respond *fallback*
        # so a Groq daily-cap hit (TPD 500k) doesn't kill the live call —
        # production caught this with mid-stream 429s breaking calls outright.
        llm_adapter: Any = _GroqAdapter(
            api_key=groq_key, model=groq_model, client=http,
            # Provider-specific small model for slot extraction (Groq:
            # llama-3.1-8b-instant, Cerebras: llama3.1-8b).
            extract_model=os.environ.get(
                "GROQ_EXTRACT_MODEL", "llama-3.1-8b-instant"
            ),
            gemini_key="", gemini_model=gemini_model,
            fallback_gemini_key=gemini_key,
            fallback_gemini_model=gemini_model,
            # Second OpenAI-compatible pool tried before Gemini on a 429 —
            # e.g. Cerebras gpt-oss-120b (30K TPM free, ~3000 tok/s).
            alt_base_url=os.environ.get("ALT_LLM_BASE_URL", ""),
            alt_api_key=os.environ.get("ALT_LLM_API_KEY", ""),
            alt_model=os.environ.get("ALT_LLM_MODEL", ""),
            # LLM_PRIMARY=gemini → Gemini speaks, Groq is the fallback +
            # extractor. llama-3.3-70b parrots quoted directive examples
            # and ignores the answer-first rule (calls 43ea487c, 3cfaeed8).
            gemini_primary=(
                os.environ.get("LLM_PRIMARY", "").strip().lower() == "gemini"
                and bool(gemini_key)
            ),
        )
    else:
        llm_adapter = _GeminiAdapter(api_key=gemini_key, model=gemini_model, client=http)

    # All-Sarvam voice mode (TTS_PROVIDER=sarvam): one Bulbul v3 speaker
    # across hi/en/ta — the SPC formula. The hybrid stacks below swap voices
    # on language flip (smallest meher ↔ bulbul), which leads heard as two
    # different people on one call; pronunciation complaints on en/hi trace
    # to meher (2026-06-12 demo feedback).
    tts_provider_override = os.environ.get("TTS_PROVIDER", "").strip().lower()
    if tts_provider_override == "sarvam":
        speaker = os.environ.get("SARVAM_TTS_SPEAKER", TTS_DEFAULT_SPEAKER)
        if os.environ.get("SARVAM_TTS_STREAMING", "1") != "0":
            # Bulbul v3 streaming WS: ~100-250ms to first audio vs
            # 1.8-2.6s REST (probes 2026-06-12). One process-wide
            # instance — the connection is reused across turns and
            # calls; warm it now so setup (~0.5-1.5s) never lands on
            # the call's first reply.
            tts_adapter: Any = _get_streaming_tts(sarvam_key, speaker)
            try:
                asyncio.ensure_future(tts_adapter.warmup())
            except RuntimeError:
                pass  # no running loop (tests) — first sentence connects
        else:
            tts_adapter = _SarvamTTSAdapter(
                api_key=sarvam_key, client=http, speaker=speaker,
            )
    elif smallest_key:
        # smallest.ai Lightning v3.1 — one voice across hi/en/ta with native
        # code-mixing + clean English-term pronunciation.
        smallest_adapter = _SmallestTTSAdapter(
            api_key=smallest_key, client=http, voice=smallest_voice,
            model=smallest_model, sample_rate=smallest_rate, speed=smallest_speed,
            lang_hint=smallest_lang_hint,
        )
        # Tamil rendering on meher is the worst pronunciation in the stack —
        # native TN listeners report it as incomprehensible. Sarvam bulbul:v3
        # is Indic-native and produces a far better Tamil voice. Route ta-IN
        # to a dedicated provider; fall back to smallest only if neither
        # Sarvam nor Cartesia is configured.
        tamil_provider = os.environ.get(
            "SMALLEST_TAMIL_PROVIDER", "sarvam"
        ).strip().lower()
        if tamil_provider == "sarvam" and sarvam_key:
            tts_adapter: Any = _HybridTTSAdapter(
                primary=smallest_adapter,
                tamil=_SarvamTTSAdapter(api_key=sarvam_key, client=http),
            )
        elif tamil_provider == "cartesia" and cartesia_key:
            tts_adapter = _HybridTTSAdapter(
                primary=smallest_adapter,
                tamil=_CartesiaTTSAdapter(
                    api_key=cartesia_key, client=http, voice="nithya",
                ),
            )
        else:
            tts_adapter = smallest_adapter
    elif eleven_key:
        el_adapter = _ElevenLabsTTSAdapter(
            api_key=eleven_key, client=http,
            voice_id=eleven_voice or "EXAVITQu4vr4xnSDxMaL", model=eleven_model,
        )
        if cartesia_key:
            # Hindi/English → ElevenLabs (realism); Tamil → Cartesia nithya.
            tts_adapter = _HybridTTSAdapter(
                primary=el_adapter,
                tamil=_CartesiaTTSAdapter(api_key=cartesia_key, client=http, voice="nithya"),
            )
        else:
            tts_adapter = el_adapter
    elif cartesia_key:
        tts_adapter = _CartesiaTTSAdapter(api_key=cartesia_key, client=http, voice=cartesia_voice)
    else:
        tts_adapter = _SarvamTTSAdapter(api_key=sarvam_key, client=http)

    return TurnDependencies(
        stt=_SarvamSTTAdapter(api_key=sarvam_key, client=http),
        tts=tts_adapter,
        llm=llm_adapter,
        r2_reader=r2_reader,
        r2_writer=r2_writer,
    )


def _build_db_client() -> AgentSupabaseClient | None:
    """Build Supabase client from env. Returns None if unconfigured."""
    try:
        cfg = SupabaseConfig.from_env()
        return AgentSupabaseClient(cfg)
    except SupabaseConfigError as exc:
        logger.warning("Supabase disabled (%s); no DB persistence", exc)
        return None
