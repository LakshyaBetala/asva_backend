"""Tests for the per-turn orchestrator.

We inject simple fakes for every adapter so the orchestrator's logic
(STT → LangState → Phase → LLM × 2 in parallel → TTS via phrase cache)
is verified in isolation. No network, no Pipecat, no Plivo.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from voice_agent.language_state import Lang
from voice_agent.pipeline import make_initial_context
from voice_agent.qualification import (
    BuyingFrequency,
    DecisionRole,
    QualificationSlots,
)
from voice_agent.turn_orchestrator import TurnDependencies, run_turn


@dataclass
class FakeSTTResult:
    transcript: str
    language_code: str
    confidence: float


class FakeSTT:
    def __init__(self, transcript: str, lang: str = "en-IN", confidence: float = 0.95):
        self.transcript = transcript
        self.lang = lang
        self.confidence = confidence
        self.calls: list[bytes] = []

    async def transcribe(self, audio: bytes) -> FakeSTTResult:
        self.calls.append(audio)
        return FakeSTTResult(self.transcript, self.lang, self.confidence)


class FakeTTS:
    def __init__(self) -> None:
        self.synth_calls: list[tuple[str, str]] = []

    async def synth(self, text: str, lang: str) -> bytes:
        self.synth_calls.append((text, lang))
        return f"AUDIO[{text}|{lang}]".encode()


class FakeLLM:
    def __init__(self, response: str = "Got it, what's your monthly volume?"):
        self.response = response
        self.respond_calls: list[tuple[str, str]] = []
        self.extract_calls: list[str] = []

    async def respond(self, system_message: str, user_message: str) -> str:
        self.respond_calls.append((system_message, user_message))
        return self.response

    async def extract(self, prompt: str) -> str:
        self.extract_calls.append(prompt)
        # Return a tiny JSON with elevated buying_confidence so the
        # extractor merges it in.
        return (
            '{"product_interest": "toluene", '
            '"buying_confidence": 0.65, '
            '"buying_frequency": "monthly", '
            '"decision_role": "procurement", '
            '"slot_confidence": {"product_interest": 0.9, "buying_frequency": 0.8, '
            '"decision_role": 0.8}}'
        )


class FakeR2:
    """Combined reader+writer in-memory store for tests."""

    def __init__(self, preload: dict[str, bytes] | None = None) -> None:
        self.store: dict[str, bytes] = dict(preload or {})
        self.gets: list[str] = []
        self.puts: list[str] = []

    async def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        return self.store.get(key)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        self.puts.append(key)
        self.store[key] = body


def _make_ctx():
    return make_initial_context(
        call_id="c1",
        tenant_id="t1",
        lead_id="l1",
        lead_first_name="Suresh",
        lead_company="Acme Chemicals",
        default_lang="hi-IN",
    )


def _deps(stt: FakeSTT, tts: FakeTTS, llm: FakeLLM, r2: FakeR2) -> TurnDependencies:
    return TurnDependencies(stt=stt, tts=tts, llm=llm, r2_reader=r2, r2_writer=r2)


@pytest.mark.asyncio
async def test_turn_returns_priya_audio_and_text():
    ctx = _make_ctx()
    stt = FakeSTT("Aap kya monthly volume karte ho?", lang="hi-IN")
    tts = FakeTTS()
    llm = FakeLLM(response="Haan ji, hum 5-7 days mein deliver karte hain.")
    r2 = FakeR2()

    result = await run_turn(
        ctx=ctx,
        audio_in=b"LEAD-AUDIO",
        deps=_deps(stt, tts, llm, r2),
        prior_slots=QualificationSlots(),
    )

    assert result.lead_text == "Aap kya monthly volume karte ho?"
    assert result.priya_text.startswith("Haan ji")
    assert b"AUDIO[" in result.priya_audio
    assert result.lead_lang == "hi-IN"


@pytest.mark.asyncio
async def test_turn_runs_slot_extractor_and_response_in_parallel():
    """Slot extractor LLM call must NOT block the response LLM call."""
    ctx = _make_ctx()
    stt = FakeSTT("We buy 500kg toluene monthly", lang="en-IN")
    tts = FakeTTS()
    llm = FakeLLM(response="Got it, 500kg monthly. What's your timeline?")
    r2 = FakeR2()

    result = await run_turn(
        ctx=ctx,
        audio_in=b"LEAD",
        deps=_deps(stt, tts, llm, r2),
        prior_slots=QualificationSlots(),
    )

    assert len(llm.respond_calls) == 1
    assert len(llm.extract_calls) == 1
    # Extractor merged the new fields.
    assert result.slots.product_interest == "toluene"
    assert result.slots.buying_confidence == 0.65
    assert result.slots.buying_frequency == BuyingFrequency.MONTHLY
    assert result.slots.decision_role == DecisionRole.PROCUREMENT


@pytest.mark.asyncio
async def test_turn_increments_turn_idx_and_records_priya_turn():
    ctx = _make_ctx()
    assert ctx.turn_idx == 0
    assert ctx.conversation_state.recent_priya_turns == []

    await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(FakeSTT("hello"), FakeTTS(), FakeLLM("Hi there"), FakeR2()),
        prior_slots=QualificationSlots(),
    )

    assert ctx.turn_idx == 1
    assert ctx.conversation_state.recent_priya_turns == ["Hi there"]


@pytest.mark.asyncio
async def test_turn_uses_phrase_cache_when_audio_present_in_r2():
    """If R2 already has the synthesized audio for Priya's text, skip live TTS."""
    ctx = _make_ctx()
    # Pre-warm R2 with the exact phrase Priya will say.
    from voice_agent.phrase_cache import phrase_r2_key

    priya_line = "Theek hai."
    key = phrase_r2_key(text=priya_line, lang="hi-IN")
    r2 = FakeR2(preload={key: b"CACHED-PRIYA"})

    tts = FakeTTS()
    llm = FakeLLM(response=priya_line)

    result = await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(FakeSTT("haan", lang="hi-IN"), tts, llm, r2),
        prior_slots=QualificationSlots(),
    )

    assert result.used_phrase_cache is True
    assert result.priya_audio == b"CACHED-PRIYA"
    assert tts.synth_calls == []  # never called
    assert ctx.phrase_cache_hits == 1


@pytest.mark.asyncio
async def test_turn_synthesizes_when_phrase_not_in_cache():
    ctx = _make_ctx()
    r2 = FakeR2()
    tts = FakeTTS()

    result = await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(FakeSTT("haan"), tts, FakeLLM("Achha, batayie."), r2),
        prior_slots=QualificationSlots(),
    )

    assert result.used_phrase_cache is False
    assert tts.synth_calls and tts.synth_calls[0][0] == "Achha, batayie."
    # Write-back must have queued; let it run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(r2.puts) >= 1


@pytest.mark.asyncio
async def test_turn_emits_bridge_audio_on_explicit_language_switch():
    """If the lead says 'speak in English', Priya plays a Hindi-to-English bridge."""
    ctx = _make_ctx()  # starts in hi-IN
    stt = FakeSTT("Can we speak in english please", lang="en-IN", confidence=0.95)

    result = await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(stt, FakeTTS(), FakeLLM("Sure, of course."), FakeR2()),
        prior_slots=QualificationSlots(),
    )

    assert result.language_transition.switched is True
    assert result.language_transition.trigger == "explicit"
    assert result.bridge_audio is not None


@pytest.mark.asyncio
async def test_turn_does_not_emit_bridge_when_no_switch():
    ctx = _make_ctx()
    stt = FakeSTT("haan ji", lang="hi-IN")

    result = await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(stt, FakeTTS(), FakeLLM("Achha."), FakeR2()),
        prior_slots=QualificationSlots(),
    )

    assert result.language_transition.switched is False
    assert result.bridge_audio is None


@pytest.mark.asyncio
async def test_turn_records_latency_metrics():
    ctx = _make_ctx()
    result = await run_turn(
        ctx=ctx,
        audio_in=b"x",
        deps=_deps(FakeSTT("ok"), FakeTTS(), FakeLLM("Got it."), FakeR2()),
        prior_slots=QualificationSlots(),
    )

    assert "stt_ms" in result.latency_ms
    assert "llm_ms" in result.latency_ms
    assert "tts_ms" in result.latency_ms
    assert "total_ms" in result.latency_ms
    assert result.latency_ms["total_ms"] >= 0
