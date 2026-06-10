"""Tests for the streaming turn orchestrator."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import pytest

from voice_agent.pipeline import make_initial_context
from voice_agent.qualification import QualificationSlots
from voice_agent.streaming_orchestrator import (
    AudioChunkEvent,
    StreamingDependencies,
    TurnCompleteEvent,
    apply_pronunciation_pack,
    prepare_for_tts,
    run_turn_streaming,
    split_sentences,
)


# -- Sentence splitting tests -----------------------------------------------

def test_split_hindi_with_danda():
    text = "नमस्ते सुरेश जी। मैं प्रिया हूँ। कैसे हैं?"
    assert split_sentences(text) == ["नमस्ते सुरेश जी।", "मैं प्रिया हूँ।", "कैसे हैं?"]


def test_split_english():
    text = "Got it. What's your monthly volume? We can help."
    assert split_sentences(text) == ["Got it.", "What's your monthly volume?", "We can help."]


def test_split_single_sentence_returns_as_is():
    assert split_sentences("Haan ji, toluene supply karte hain") == [
        "Haan ji, toluene supply karte hain"
    ]


def test_split_empty_returns_empty():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_split_hindi_question_mark():
    text = "Aapka volume kitna hai? Hum bulk mein dete hain."
    assert len(split_sentences(text)) == 2


# -- Pronunciation pack tests ------------------------------------------------

def test_apply_pronunciation_pack_substitutes_whole_words():
    pack = {"Almmatix": "All-matix", "Betala": "Beh-ta-la"}
    out = apply_pronunciation_pack("Main Laksh Betala se hoon, Almmatix se.", pack)
    assert out == "Main Laksh Beh-ta-la se hoon, All-matix se."


def test_apply_pronunciation_pack_respects_word_boundaries():
    # "demo" must not replace inside "demolish".
    pack = {"demo": "deh-mo"}
    out = apply_pronunciation_pack("Quick demo of demolish flow.", pack)
    assert out == "Quick deh-mo of demolish flow."


def test_apply_pronunciation_pack_prefers_longer_match():
    # "Laksh Betala" beats "Laksh" alone when both keys are present.
    pack = {"Laksh": "Luck", "Laksh Betala": "Laksh Beh-ta-la"}
    out = apply_pronunciation_pack("Hello Laksh Betala.", pack)
    assert out == "Hello Laksh Beh-ta-la."


def test_apply_pronunciation_pack_empty_pack_is_noop():
    assert apply_pronunciation_pack("Hello world", {}) == "Hello world"
    assert apply_pronunciation_pack("Hello world", None) == "Hello world"


def test_prepare_for_tts_pipes_pack_then_pacing():
    # Pack substitution applies to mid-sentence words. (Leading bare acks
    # are stripped by the name-echo sanitiser by design, so the pack is
    # exercised on a locality, not on the ack.)
    pack = {"Velachery": "Vela-cheri"}
    out = prepare_for_tts("Velachery la nalla options irukku.", "ta-IN", pack)
    assert "Vela-cheri" in out
    assert "Velachery" not in out


def test_sanitize_keeps_short_bare_ack_drops_canned_fallback():
    # A reply that is ONLY a short ack is spoken as-is — never replaced by
    # the old canned "didn't catch that / buy or rent?" line (which fired
    # mid-call ignoring context and re-asked answered questions).
    out = prepare_for_tts("Haan ji.", "hi-IN")
    assert out == "Haan ji."
    assert "didn't catch" not in out


def test_spell_numbers_for_tts():
    from voice_agent.streaming_orchestrator import spell_numbers_for_tts
    assert spell_numbers_for_tts("2000 square feet") == "two thousand square feet"
    assert spell_numbers_for_tts("80,00,000 budget") == "eighty lakh budget"
    assert "one point five" in spell_numbers_for_tts("1.5 crore")
    # Phone numbers (10+ digits) and times stay untouched.
    assert spell_numbers_for_tts("9876543210") == "9876543210"
    assert "4:30" in spell_numbers_for_tts("at 4:30 pm")


# -- Fake adapters -----------------------------------------------------------

@dataclass
class FakeSTTResult:
    transcript: str
    language_code: str
    confidence: float


class FakeSTT:
    def __init__(self, transcript="haan ji", lang="hi-IN"):
        self.transcript = transcript
        self.lang = lang

    async def transcribe(self, audio: bytes) -> FakeSTTResult:
        return FakeSTTResult(self.transcript, self.lang, 0.95)


class FakeTTS:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def synth(self, text: str, lang: str) -> bytes:
        self.calls.append((text, lang))
        return f"AUDIO[{text}]".encode()


class FakeStreamingLLM:
    """Yields chunks that form complete sentences."""

    def __init__(self, chunks: list[str] | None = None):
        self.chunks = chunks or [
            "Haan ji, toluene ",
            "supply karte hain. ",
            "Monthly kitna ",
            "chahiye?"
        ]
        self.extract_calls: list[str] = []

    async def stream_respond(self, system_message: str, user_message: str) -> AsyncIterator[str]:
        for chunk in self.chunks:
            yield chunk

    async def extract(self, prompt: str) -> str:
        self.extract_calls.append(prompt)
        return '{"product_interest": "toluene", "buying_confidence": 0.6}'


class FakeR2:
    def __init__(self, preload: dict[str, bytes] | None = None):
        self.store = dict(preload or {})

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        self.store[key] = body


def _ctx():
    return make_initial_context(
        call_id="c1", tenant_id="t1", lead_id="l1",
        lead_first_name="Suresh", lead_company="Acme",
        default_lang="hi-IN",
    )


def _deps(stt=None, tts=None, llm=None, r2=None):
    r = r2 or FakeR2()
    return StreamingDependencies(
        stt=stt or FakeSTT(),
        tts=tts or FakeTTS(),
        llm=llm or FakeStreamingLLM(),
        r2_reader=r,
        r2_writer=r,
    )


# -- Streaming orchestrator tests -------------------------------------------

@pytest.mark.asyncio
async def test_yields_audio_chunks_then_complete_event():
    events = []
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x", deps=_deps(), prior_slots=QualificationSlots()
    ):
        events.append(event)

    audio_events = [e for e in events if isinstance(e, AudioChunkEvent)]
    complete_events = [e for e in events if isinstance(e, TurnCompleteEvent)]

    assert len(audio_events) >= 1
    assert len(complete_events) == 1
    assert complete_events[0].priya_full_text
    assert complete_events[0].slots is not None


@pytest.mark.asyncio
async def test_two_sentences_yield_two_audio_chunks():
    llm = FakeStreamingLLM(chunks=[
        "Haan ji. ",
        "Toluene supply karte hain."
    ])
    events = []
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x", deps=_deps(llm=llm),
        prior_slots=QualificationSlots(),
    ):
        events.append(event)

    audio_events = [e for e in events if isinstance(e, AudioChunkEvent)]
    assert len(audio_events) == 2
    assert audio_events[0].sentence_idx == 0
    assert audio_events[1].sentence_idx == 1


@pytest.mark.asyncio
async def test_single_sentence_yields_one_chunk():
    llm = FakeStreamingLLM(chunks=["Haan ji, volume batayie"])
    events = []
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x", deps=_deps(llm=llm),
        prior_slots=QualificationSlots(),
    ):
        events.append(event)

    audio_events = [e for e in events if isinstance(e, AudioChunkEvent)]
    assert len(audio_events) == 1


@pytest.mark.asyncio
async def test_slot_extraction_runs_in_parallel():
    llm = FakeStreamingLLM()
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x", deps=_deps(llm=llm),
        prior_slots=QualificationSlots(),
    ):
        pass

    assert len(llm.extract_calls) == 1


@pytest.mark.asyncio
async def test_latency_timings_include_first_sentence():
    events = []
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x", deps=_deps(), prior_slots=QualificationSlots()
    ):
        events.append(event)

    complete = [e for e in events if isinstance(e, TurnCompleteEvent)][0]
    assert "stt_ms" in complete.latency_ms
    assert "llm_first_sentence_ms" in complete.latency_ms
    assert "total_ms" in complete.latency_ms


@pytest.mark.asyncio
async def test_turn_idx_increments_and_priya_turn_recorded():
    ctx = _ctx()
    assert ctx.turn_idx == 0

    async for _ in run_turn_streaming(
        ctx=ctx, audio_in=b"x", deps=_deps(), prior_slots=QualificationSlots()
    ):
        pass

    assert ctx.turn_idx == 1
    assert len(ctx.conversation_state.recent_priya_turns) == 1


@pytest.mark.asyncio
async def test_phrase_cache_hit_skips_tts():
    from voice_agent.phrase_cache import phrase_r2_key

    sentence = "Haan ji."
    key = phrase_r2_key(text=sentence, lang="hi-IN")
    r2 = FakeR2(preload={key: b"CACHED"})

    llm = FakeStreamingLLM(chunks=["Haan ji."])
    tts = FakeTTS()

    events = []
    async for event in run_turn_streaming(
        ctx=_ctx(), audio_in=b"x",
        deps=_deps(llm=llm, tts=tts, r2=r2),
        prior_slots=QualificationSlots(),
    ):
        events.append(event)

    audio = [e for e in events if isinstance(e, AudioChunkEvent)]
    assert audio[0].audio == b"CACHED"
    assert audio[0].used_cache is True
    assert tts.calls == []  # TTS never called
