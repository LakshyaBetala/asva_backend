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


# -- Outlier handling: garbled audio, fragments, dead-air guard --------------
# Regressions from call 56e606ca: wrong-script acks answered as content,
# "Budget is around" answered literally, an empty LLM reply = dead silence,
# and the intro's own echo answered with a cached "Got it.".

from voice_agent.sarvam_stt import STTResult as RealSTTResult
from voice_agent.streaming_orchestrator import (
    _is_backchannel,
    is_garbled_utterance,
    transcript_unfinished,
)


def test_transcript_unfinished_detects_dangling_fragments():
    assert transcript_unfinished("Budget is around")
    assert transcript_unfinished("मैं सोच रही हूँ क्या मैं।")  # dangling "मैं"
    assert transcript_unfinished("Anna Nagar mein")  # no terminal punct + "mein"


def test_transcript_unfinished_passes_complete_sentences():
    assert not transcript_unfinished("Budget twenty five thousand hai.")
    assert not transcript_unfinished("Kitna budget hai?")
    assert not transcript_unfinished("ठीक है।")  # bare ack, never "unfinished"


def test_native_script_acks_classify_as_backchannel():
    for text in ("अच्छा ठीक है।", "ઓકે.", "હા.", "ఓకే అండి.", "ம்."):
        assert _is_backchannel(text), text


def test_is_garbled_wrong_script_short_utterance():
    # Telugu/Gujarati junk on a Hindi call = inaudible audio, not language.
    assert is_garbled_utterance("ఏమిటో అది.", "hi-IN")
    assert is_garbled_utterance("ક્યાંક કંઈક.", "hi-IN")
    # Any Indic short burst on an English call is noise.
    assert is_garbled_utterance("क्या", "en-IN")


def test_is_garbled_never_fires_on_acks_or_home_script():
    assert not is_garbled_utterance("ઓકે.", "hi-IN")  # ack → backchannel path
    assert not is_garbled_utterance("महिंद्रा सिटी।", "hi-IN")  # home script
    assert not is_garbled_utterance("Saturday chalega sir", "hi-IN")


@pytest.mark.asyncio
async def test_garbled_utterance_gets_repeat_request_not_llm():
    ctx = _ctx()
    llm = FakeStreamingLLM()
    deps = _deps(llm=llm)
    events = []
    async for event in run_turn_streaming(
        ctx=ctx, audio_in=b"", deps=deps, prior_slots=QualificationSlots(),
        pre_transcribed=RealSTTResult(
            transcript="ఏమిటో అది.", language_code="te-IN",
            confidence=1.0, request_id="r1",
        ),
    ):
        events.append(event)

    complete = [e for e in events if isinstance(e, TurnCompleteEvent)][0]
    assert complete.lead_intent == "garbled"
    assert "clear" in complete.priya_full_text.lower()  # the repeat line
    assert llm.extract_calls == []  # no LLM respond/extract burned
    assert ctx.conversation_state.repeat_request_count == 1
    # The repeat prompt IS spoken.
    audio = [e for e in events if isinstance(e, AudioChunkEvent)]
    assert len(audio) == 1


@pytest.mark.asyncio
async def test_garbled_repeat_capped_at_two():
    ctx = _ctx()
    ctx.conversation_state.repeat_request_count = 2
    llm = FakeStreamingLLM()
    events = []
    async for event in run_turn_streaming(
        ctx=ctx, audio_in=b"", deps=_deps(llm=llm),
        prior_slots=QualificationSlots(),
        pre_transcribed=RealSTTResult(
            transcript="ఏమిటో అది.", language_code="te-IN",
            confidence=1.0, request_id="r1",
        ),
    ):
        events.append(event)
    complete = [e for e in events if isinstance(e, TurnCompleteEvent)][0]
    # Cap hit → falls through to the normal LLM turn (best effort).
    assert complete.lead_intent != "garbled"
    assert len(llm.extract_calls) == 1


@pytest.mark.asyncio
async def test_streaming_echo_is_skipped_silently():
    ctx = _ctx()
    ctx.conversation_state.record_priya_turn(
        "You were looking at properties in Chennai right"
    )
    events = []
    async for event in run_turn_streaming(
        ctx=ctx, audio_in=b"", deps=_deps(), prior_slots=QualificationSlots(),
        pre_transcribed=RealSTTResult(
            transcript="looking at properties in Chennai right",
            language_code="en-IN", confidence=1.0, request_id="r1",
        ),
    ):
        events.append(event)

    # Echo of Priya's own intro: say NOTHING, wait for the lead's real words.
    assert not [e for e in events if isinstance(e, AudioChunkEvent)]
    complete = [e for e in events if isinstance(e, TurnCompleteEvent)][0]
    assert complete.lead_intent == "silence"
    assert complete.priya_full_text == ""


@pytest.mark.asyncio
async def test_empty_llm_reply_never_means_dead_air():
    ctx = _ctx()
    llm = FakeStreamingLLM(chunks=[""])  # LLM yields zero content
    events = []
    async for event in run_turn_streaming(
        ctx=ctx, audio_in=b"", deps=_deps(llm=llm),
        prior_slots=QualificationSlots(),
        pre_transcribed=RealSTTResult(
            transcript="Mahindra City mein dekh rahi hoon",
            language_code="hi-IN", confidence=1.0, request_id="r1",
        ),
    ):
        events.append(event)

    audio = [e for e in events if isinstance(e, AudioChunkEvent)]
    assert len(audio) == 1  # the continue-prompt fallback
    complete = [e for e in events if isinstance(e, TurnCompleteEvent)][0]
    assert complete.priya_full_text  # never an empty recorded turn


@pytest.mark.asyncio
async def test_fragment_recorded_with_cutoff_marker():
    ctx = _ctx()
    async for _ in run_turn_streaming(
        ctx=ctx, audio_in=b"", deps=_deps(), prior_slots=QualificationSlots(),
        pre_transcribed=RealSTTResult(
            transcript="Budget is around", language_code="hi-IN",
            confidence=1.0, request_id="r1",
        ),
    ):
        pass
    assert any(
        "cut off" in t for t in ctx.conversation_state.recent_lead_turns
    )


# -- Lead-question answer-first directive (tester feedback 2026-06-12) -------

class TestLeadQuestionDirective:
    """Tester: 'English is like Q&A — if [I] ask anything in between, it
    will ask its next question.' Lead questions must be answered first."""

    def test_lead_asked_question_detection(self):
        from voice_agent.streaming_orchestrator import _lead_asked_question

        assert _lead_asked_question("What is the price?")
        assert _lead_asked_question("ye kitna ka hai")  # no "?" — romanized Hindi
        assert _lead_asked_question("क्या ये ready to move है")  # Devanagari
        assert _lead_asked_question("evlo budget venum")  # romanized Tamil
        assert _lead_asked_question("நீங்க யாரு")  # Tamil script
        assert not _lead_asked_question("I am looking in Anna Nagar.")
        assert not _lead_asked_question("")

    def test_question_gets_answer_first_directive(self):
        from voice_agent.conversation_state import ConversationState
        from voice_agent.streaming_orchestrator import _format_user_message

        conv = ConversationState()
        conv.record_lead_turn("Aap kaun se builder ke saath kaam karte ho?")
        msg = _format_user_message(
            "Aap kaun se builder ke saath kaam karte ho?",
            QualificationSlots(),
            conv,
            lang="hi-IN",
            intent="normal",
        )
        assert "Answer THAT first" in msg

    def test_statement_gets_no_question_directive(self):
        from voice_agent.conversation_state import ConversationState
        from voice_agent.streaming_orchestrator import _format_user_message

        conv = ConversationState()
        conv.record_lead_turn("I am looking in Anna Nagar.")
        msg = _format_user_message(
            "I am looking in Anna Nagar.",
            QualificationSlots(),
            conv,
            lang="en-IN",
            intent="normal",
        )
        assert "Answer THAT first" not in msg


# -- Streaming TTS sentence emission (Bulbul v3 WS, 2026-06-12) ---------------

class TestSentenceAudioEvents:
    """One sentence becomes many raw-PCM events with a streaming TTS,
    one full-WAV event otherwise; cache hits short-circuit both."""

    @staticmethod
    def _deps(tts, cached=None):
        from types import SimpleNamespace

        puts = []

        class R2:
            async def get(self, key):
                return cached

            async def put(self, key, data, content_type):
                puts.append((key, data, content_type))

        r2 = R2()
        deps = SimpleNamespace(
            tts=tts, r2_reader=r2, r2_writer=r2, voice_id="test-voice"
        )
        return deps, puts

    def _run(self, deps):
        import asyncio
        from voice_agent.streaming_orchestrator import _sentence_audio_events

        async def go():
            stats: dict = {}
            events = [
                ev
                async for ev in _sentence_audio_events(
                    spoken="Endha area sir?",
                    lang="ta-IN",
                    deps=deps,
                    sentence_idx=0,
                    stats=stats,
                )
            ]
            return events, stats

        return asyncio.run(go())

    def test_streaming_tts_yields_raw_chunks_and_writes_back(self):
        from types import SimpleNamespace

        class StreamingTTS:
            sample_rate = 8000

            async def synth_stream(self, text, lang):
                yield b"\x01\x02" * 100
                yield b"\x03\x04" * 100

        deps, puts = self._deps(StreamingTTS())
        events, stats = self._run(deps)

        assert len(events) == 2
        assert all(ev.is_raw_pcm for ev in events)
        assert events[0].text == "Endha area sir?"  # sentence start marker
        assert events[1].text == ""  # continuation chunk
        assert stats["used_cache"] is False
        # Assembled WAV written back for next-call cache hits.
        assert len(puts) == 1
        assert puts[0][1][:4] == b"RIFF"

    def test_cache_hit_short_circuits_streaming(self):
        class StreamingTTS:
            sample_rate = 8000

            async def synth_stream(self, text, lang):
                raise AssertionError("must not synthesize on cache hit")
                yield b""

        deps, puts = self._deps(StreamingTTS(), cached=b"RIFFcachedwav")
        events, stats = self._run(deps)

        assert len(events) == 1
        assert events[0].used_cache is True
        assert events[0].is_raw_pcm is False
        assert stats["used_cache"] is True
        assert puts == []

    def test_non_streaming_tts_keeps_single_event_path(self):
        class RestTTS:
            async def synth(self, text, lang):
                return b"RIFFfakewav"

        deps, puts = self._deps(RestTTS())
        events, stats = self._run(deps)

        assert len(events) == 1
        assert events[0].is_raw_pcm is False
        assert events[0].audio == b"RIFFfakewav"


# -- Echo-ack dropper (call 2b674c4c) -----------------------------------------

def test_echo_ack_detection():
    from voice_agent.streaming_orchestrator import _is_echo_ack

    # llama echoing the lead's answer back as its ack — all from 2b674c4c.
    assert _is_echo_ack("Right, Annanagar.", "Annanagar Annanagar Hello")
    assert _is_echo_ack("two BHK.", "2 BHK please")
    assert _is_echo_ack("fifteen to twentyk.", "15 to 20k")
    assert _is_echo_ack("For rent.", "I was looking to rent")


def test_echo_ack_keeps_real_acks_and_content():
    from voice_agent.streaming_orchestrator import _is_echo_ack

    assert not _is_echo_ack("Got it.", "15 to 20k")
    assert not _is_echo_ack("Theek hai.", "సరే ఓకే.")  # no Latin lead words
    assert not _is_echo_ack("Saturday confirmed sir.", "Saturday")
    # Long sentences are never "acks" even with overlap.
    assert not _is_echo_ack(
        "So two BHK in Annanagar for fifteen to twenty thousand rent.",
        "2 BHK Annanagar 15 to 20k",
    )
    assert not _is_echo_ack("", "anything")


# -- Native-script canned lines (pronunciation, 2026-06-13) -------------------

def test_canned_lines_native_on_sarvam_stack(monkeypatch):
    from voice_agent.streaming_orchestrator import _continue_line, _repeat_line

    monkeypatch.setenv("TTS_PROVIDER", "sarvam")
    monkeypatch.delenv("TTS_NATIVE_HI", raising=False)
    monkeypatch.delenv("TTS_NATIVE_TA", raising=False)
    assert "आवाज़" in _repeat_line("hi-IN")
    assert "சொல்லுங்க" in _repeat_line("ta-IN")
    assert "बोलिए" in _continue_line("hi-IN")
    # English untouched.
    assert _repeat_line("en-IN").startswith("Sorry")


def test_canned_lines_roman_on_other_stacks(monkeypatch):
    from voice_agent.streaming_orchestrator import _repeat_line

    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    assert _repeat_line("hi-IN").startswith("Sorry sir, awaaz")
    assert _repeat_line("ta-IN").startswith("Sorry sir, line clear-aa")


# -- Visit-slot memory (call be21ced9: Saturday asked 4x) ---------------------

class TestVisitSlotMemory:
    @staticmethod
    def _conv_with_priya(line):
        from voice_agent.conversation_state import ConversationState

        conv = ConversationState()
        conv.record_priya_turn(line)
        return conv

    def test_day_answer_after_slot_offer_is_captured(self):
        from voice_agent.streaming_orchestrator import _lead_chose_visit_slot

        conv = self._conv_with_priya("Site visit Saturday या Sunday?")
        assert _lead_chose_visit_slot("सैटरडे सुबह।", conv)
        assert _lead_chose_visit_slot("Sure, I can visit on Saturday.", conv)
        assert _lead_chose_visit_slot("సాటర్డే సుదా.", conv)  # Telugu-script STT

    def test_day_word_without_slot_offer_is_ignored(self):
        from voice_agent.streaming_orchestrator import _lead_chose_visit_slot

        conv = self._conv_with_priya("Aap kaunsa area dekh rahe hain?")
        assert not _lead_chose_visit_slot("Saturday ko free hoon", conv)

    def test_chosen_slot_injects_confirm_directive(self):
        from voice_agent.streaming_orchestrator import _format_user_message

        conv = self._conv_with_priya("Site visit Saturday ya Sunday?")
        conv.visit_slot_text = "सैटरडे सुबह।"
        msg = _format_user_message(
            "haan", QualificationSlots(), conv, lang="hi-IN", intent="normal"
        )
        assert "ALREADY chose the site-visit slot" in msg
        assert "सैटरडे सुबह" in msg


def test_long_number_echo_is_dropped():
    from voice_agent.streaming_orchestrator import _is_echo_ack

    assert _is_echo_ack(
        "thirty five se forty five hazaar tak.",
        "budget thirty five to forty five thousand",
    )
