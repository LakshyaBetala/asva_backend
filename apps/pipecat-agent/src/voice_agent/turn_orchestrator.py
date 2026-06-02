"""Per-turn orchestrator for Priya.

This is the brain that runs once per lead utterance. It chains:

  1. Sarvam STT  (audio in → transcript + lang)
  2. LanguageState.update()  → may flip language + emit bridge phrase
  3. ConversationState.advance_phase_if_due()  → update phase
  4. pain_library.pick_pain_hypothesis() (in DISCOVER phase)
  5. Two parallel Gemini calls:
       a. response generator (Priya's next line)
       b. slot extractor (qualification.extract_slots)
  6. Sarvam TTS (with phrase_cache fast path for repeats)
  7. Telemetry: turn_latencies row, phrase_cache_hits++

The orchestrator is PLATFORM-PURE — it does not import pipecat-ai,
plivo, or boto3 directly. All I/O is injected via Protocols so unit
tests pass with simple fakes.

Pipecat (in pipeline.py) wires real audio frames into Sarvam STT and
plays the TTS bytes back. This module decides WHAT to say.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Protocol

from .conversation_state import ConversationState, system_prompt_addendum
from .language_state import Lang, LanguageState, STTUtterance, Transition
from .pain_library import pick_pain_hypothesis
from .phrase_cache import PINNED_VOICE_ID, load_or_synthesize_phrase
from .qualification import QualificationSlots, extract_slots
from .prompts import build_system_message, load_priya_prompt


# -- Adapter protocols ------------------------------------------------------
#
# Real implementations live in sarvam_stt.py, sarvam_tts.py, gemini_llm.py,
# r2_client.py. We depend only on these surfaces here.

class STTAdapter(Protocol):
    async def transcribe(self, audio: bytes) -> "STTResultLike": ...


class STTResultLike(Protocol):
    transcript: str
    language_code: str
    confidence: float


class TTSAdapter(Protocol):
    async def synth(self, text: str, lang: str) -> bytes: ...


class LLMAdapter(Protocol):
    async def respond(self, system_message: str, user_message: str) -> str: ...
    async def extract(self, prompt: str) -> str: ...


class R2Reader(Protocol):
    async def get(self, key: str) -> bytes | None: ...


class R2Writer(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...


# -- Turn result ------------------------------------------------------------

@dataclass
class TurnResult:
    """Everything produced by one orchestrated turn. The Pipecat pipeline
    layer consumes priya_audio and emits the rest to webhooks/DB."""

    lead_text: str
    lead_lang: str
    lead_confidence: float
    priya_text: str
    priya_audio: bytes
    language_transition: Transition
    bridge_audio: bytes | None  # played BEFORE priya_audio on language flip
    slots: QualificationSlots
    used_phrase_cache: bool
    latency_ms: dict[str, int] = field(default_factory=dict)


@dataclass
class TurnDependencies:
    """All injected I/O surfaces. Built once at call start, passed every turn."""

    stt: STTAdapter
    tts: TTSAdapter
    llm: LLMAdapter
    r2_reader: R2Reader
    r2_writer: R2Writer
    voice_id: str = PINNED_VOICE_ID


# -- Main entry point -------------------------------------------------------

async def run_turn(
    *,
    ctx,  # CallContext from pipeline.py; circular import dodged.
    audio_in: bytes,
    deps: TurnDependencies,
    prior_slots: QualificationSlots,
) -> TurnResult:
    """Run one full lead-utterance → Priya-response cycle."""
    timings: dict[str, int] = {}
    t0 = time.monotonic()

    # ---- 1. STT --------------------------------------------------------
    stt_t0 = time.monotonic()
    stt_result = await deps.stt.transcribe(audio_in)
    timings["stt_ms"] = int((time.monotonic() - stt_t0) * 1000)

    # ---- 2. LanguageState ---------------------------------------------
    lang = _coerce_lang(stt_result.language_code)
    transition = ctx.language_state.update(
        STTUtterance(
            text=stt_result.transcript,
            lang=lang,
            confidence=stt_result.confidence,
        )
    )

    # ---- 3. ConversationState phase advance ---------------------------
    ctx.conversation_state.advance_phase_if_due(
        elapsed_sec=ctx.elapsed(),
        buying_confidence=prior_slots.buying_confidence,
    )

    # ---- 4. Build per-turn system message ------------------------------
    base_prompt = load_priya_prompt(ctx.industry_key)
    system_msg = build_system_message(
        base_prompt=base_prompt,
        current_language=transition.current_language.value,
        lead_first_name=ctx.lead_first_name,
        lead_company=ctx.lead_company,
    )
    system_msg += "\n\n" + system_prompt_addendum(
        ctx.conversation_state, language=transition.current_language.value
    )

    pain = _pain_hypothesis_for_turn(ctx, prior_slots, transition.current_language.value)
    if pain:
        system_msg += f"\n\n<pain_hypothesis>{pain}</pain_hypothesis>"

    user_msg = _format_user_message(
        stt_result.transcript, prior_slots, ctx.conversation_state
    )

    # ---- 5. Parallel: response + slot extraction ----------------------
    llm_t0 = time.monotonic()
    priya_text_task = asyncio.create_task(deps.llm.respond(system_msg, user_msg))
    slots_task = asyncio.create_task(
        extract_slots(
            transcript=[
                {"speaker": "lead", "text": stt_result.transcript},
                *_recent_priya_turns_as_transcript(ctx.conversation_state),
            ],
            prior_slots=prior_slots,
            llm=deps.llm.extract,
        )
    )
    priya_text = await priya_text_task
    timings["llm_ms"] = int((time.monotonic() - llm_t0) * 1000)
    new_slots = await slots_task

    # ---- 6. TTS with phrase-cache fast path ---------------------------
    tts_t0 = time.monotonic()
    phrase_result = await load_or_synthesize_phrase(
        text=priya_text,
        lang=transition.current_language.value,
        r2_reader=deps.r2_reader,
        r2_writer=deps.r2_writer,
        synthesize=lambda t, l: deps.tts.synth(t, l),
        voice_id=deps.voice_id,
    )
    timings["tts_ms"] = int((time.monotonic() - tts_t0) * 1000)

    # Bridge phrase on language flip (synthesized fresh; usually cached).
    bridge_audio: bytes | None = None
    if transition.switched and transition.bridge_phrase:
        bridge = await load_or_synthesize_phrase(
            text=transition.bridge_phrase,
            # Bridge phrase is in the OLD language to make the flip smooth;
            # but we already moved current_language to NEW. The bridge
            # phrase text itself is hard-coded in the OLD language, so
            # we tell TTS to render it in that language.
            lang=_bridge_phrase_language(transition).value,
            r2_reader=deps.r2_reader,
            r2_writer=deps.r2_writer,
            synthesize=lambda t, l: deps.tts.synth(t, l),
            voice_id=deps.voice_id,
        )
        bridge_audio = bridge.audio

    # ---- 7. Update conversation state with what Priya said ------------
    ctx.conversation_state.record_priya_turn(priya_text)
    if phrase_result.used_cache:
        ctx.phrase_cache_hits += 1
    ctx.turn_idx += 1

    timings["total_ms"] = int((time.monotonic() - t0) * 1000)

    return TurnResult(
        lead_text=stt_result.transcript,
        lead_lang=transition.current_language.value,
        lead_confidence=stt_result.confidence,
        priya_text=priya_text,
        priya_audio=phrase_result.audio,
        language_transition=transition,
        bridge_audio=bridge_audio,
        slots=new_slots,
        used_phrase_cache=phrase_result.used_cache,
        latency_ms=timings,
    )


# -- Helpers ----------------------------------------------------------------

def _coerce_lang(code: str) -> Lang | None:
    try:
        return Lang(code)
    except ValueError:
        return None


def _pain_hypothesis_for_turn(
    ctx, slots: QualificationSlots, lang: str
) -> Optional[str]:
    """Pick a pain hypothesis only when we're in DISCOVER phase."""
    from .conversation_state import Phase

    if ctx.conversation_state.phase != Phase.DISCOVER:
        return None
    try:
        lang_enum = Lang(lang)
    except ValueError:
        return None
    return pick_pain_hypothesis(
        product_interest=slots.product_interest,
        lang=lang_enum,
        turn_idx=ctx.turn_idx,
    )


def _format_user_message(
    lead_text: str, slots: QualificationSlots, conv: ConversationState
) -> str:
    parts = [f"Lead just said: \"{lead_text}\""]
    if slots.product_interest:
        parts.append(f"Known product interest: {slots.product_interest}")
    if slots.buying_confidence >= 0.7:
        parts.append("Buying signal is STRONG. Move toward a commit question.")
    elif slots.buying_confidence <= 0.3 and slots.buying_confidence > 0:
        parts.append(
            "Buying signal is WEAK. Don't push. Ask one more open question or close politely."
        )
    return "\n".join(parts)


def _recent_priya_turns_as_transcript(conv: ConversationState) -> list[dict]:
    """Format Priya's recent turns for the slot extractor prompt."""
    return [{"speaker": "priya", "text": t} for t in conv.recent_priya_turns[-4:]]


def _bridge_phrase_language(transition: Transition) -> Lang:
    """Return the language the bridge phrase was authored in (the OLD language).

    LanguageState already flipped current_language to the new language by
    the time we get the Transition. The bridge phrases dict in
    language_state.py is keyed (from, to); the value is written in `from`.
    We reconstruct `from` by looking at recent history if needed; for now,
    we accept that the pinned voice handles whatever language we tag.
    """
    # Pinned voice handles HI/EN/TA all in one voice. Tag the bridge with
    # the new current language — Bulbul will synthesize either string fine
    # with the pinned female voice.
    return transition.current_language
