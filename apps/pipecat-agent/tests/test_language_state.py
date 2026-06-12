"""Tests for the language state machine.

These tests encode the exact scenarios that caused naive auto-detect
agents to fail on Indian calls. If any of these tests start failing,
real calls will start dying.
"""
from __future__ import annotations

import pytest

from voice_agent.language_state import (
    Lang,
    LanguageState,
    STTUtterance,
    get_response_language_hint,
)


def utt(text: str, lang: Lang | None, conf: float = 0.9, code_mixed: bool = False) -> STTUtterance:
    return STTUtterance(text=text, lang=lang, confidence=conf, is_code_mixed=code_mixed)


# ---------------------------------------------------------------------------
# The bug we are protecting against: one-word reply mis-flipping state.
# ---------------------------------------------------------------------------

class TestNoFlipOnBackchannel:
    def test_haan_alone_does_not_flip_english_to_hindi(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("haan", Lang.HI, conf=0.95))
        assert t.switched is False
        assert state.current == Lang.EN

    def test_okay_alone_does_not_flip_hindi_to_english(self):
        state = LanguageState.initial(Lang.HI)
        t = state.update(utt("okay", Lang.EN, conf=0.95))
        assert t.switched is False
        assert state.current == Lang.HI

    def test_sari_alone_does_not_flip_english_to_tamil(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("sari", Lang.TA, conf=0.95))
        assert t.switched is False
        assert state.current == Lang.EN


# ---------------------------------------------------------------------------
# Low STT confidence is ignored.
# ---------------------------------------------------------------------------

class TestLowConfidenceIgnored:
    def test_low_confidence_full_utterance_does_not_count(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("haan ji bilkul sahi baat hai", Lang.HI, conf=0.6))
        assert t.switched is False
        assert state.current == Lang.EN

    def test_lang_none_does_not_count(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("indistinct mumble", lang=None, conf=0.4))
        assert t.switched is False


# ---------------------------------------------------------------------------
# Hysteresis: 2 full utterances flip (stickier — single misdetect can't drift).
# Marker-token overrides bypass hysteresis when morphology is unambiguous.
# ---------------------------------------------------------------------------

class TestHysteresisFlip:
    def test_two_full_hindi_utterances_flip_from_english(self):
        state = LanguageState.initial(Lang.EN)
        t1 = state.update(utt("haan main Sunil bol raha hoon Brilliant Paints se", Lang.HI))
        assert t1.switched is False  # first full utterance just pends
        t2 = state.update(utt("hum bulk mein chemicals lete hain pharma ke liye", Lang.HI))
        assert t2.switched is True
        assert t2.trigger == "hysteresis"
        assert state.current == Lang.HI

    def test_bridge_phrase_en_to_hi(self):
        state = LanguageState.initial(Lang.EN)
        state.update(utt("hum naya supplier dhoond rahe hain", Lang.HI))
        t = state.update(utt("paint manufacturing karte hain hum log", Lang.HI))
        assert t.bridge_phrase == "Bilkul, Hindi mein baat karte hain."

    def test_bridge_phrase_hi_to_en(self):
        state = LanguageState.initial(Lang.HI)
        state.update(utt("we are looking for new suppliers actually", Lang.EN))
        t = state.update(utt("can you share the pricing details please", Lang.EN))
        assert t.bridge_phrase == "Sure, let's talk in English."

    def test_alternating_short_utterances_never_flip(self):
        """The classic 'haan'-'no'-'haan' bug must not cause a flip."""
        state = LanguageState.initial(Lang.EN)
        for _ in range(10):
            state.update(utt("haan", Lang.HI))
            state.update(utt("no", Lang.EN))
        assert state.current == Lang.EN

    def test_pending_resets_when_lead_returns_to_current(self):
        state = LanguageState.initial(Lang.EN)
        state.update(utt("haan main Sunil bol raha hoon", Lang.HI))
        assert state.current == Lang.EN  # 1 full utterance pends but doesn't flip
        state.update(utt("yes I work in procurement here", Lang.EN))
        assert state.current == Lang.EN  # returning to EN resets pending


# ---------------------------------------------------------------------------
# Explicit trigger phrases bypass hysteresis.
# ---------------------------------------------------------------------------

class TestExplicitTrigger:
    def test_speak_in_english_flips_immediately(self):
        state = LanguageState.initial(Lang.HI)
        t = state.update(utt("can we speak english please", Lang.EN))
        assert t.switched is True
        assert t.trigger == "explicit"
        assert state.current == Lang.EN

    def test_hindi_mein_bolo_flips_immediately(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("aap Hindi mein bolo bhai", Lang.EN))
        assert t.switched is True
        assert t.trigger == "explicit"
        assert state.current == Lang.HI

    def test_tamil_la_pesunga_flips_immediately(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("Tamil-la pesunga please", Lang.EN))
        assert t.switched is True
        assert t.trigger == "explicit"
        assert state.current == Lang.TA

    def test_trigger_matching_current_language_is_noop(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("yes can we speak in english", Lang.EN))
        assert t.switched is False


# ---------------------------------------------------------------------------
# Code-mixed (Hinglish, Tanglish) does NOT trigger a flip.
# ---------------------------------------------------------------------------

class TestCodeMixedNoFlip:
    def test_hinglish_keeps_current_language(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(
            utt("bhai actually toluene ka pricing kya hai", Lang.HI, code_mixed=True)
        )
        assert t.switched is False
        assert state.current == Lang.EN

    def test_tanglish_with_clear_markers_does_flip(self):
        """When STT flags code-mixed but the text has unambiguous Tamil
        morphology ("naan"), the marker override wins — we WANT to flip so
        Priya mirrors the lead. Matches the product requirement: 'if it
        switched in tamil and the client continues in tamil let it be tamil'."""
        state = LanguageState.initial(Lang.EN)
        t = state.update(
            utt("naan procurement head parppen pricing details venum", Lang.TA, code_mixed=True)
        )
        assert t.switched is True
        assert state.current == Lang.TA


# ---------------------------------------------------------------------------
# End-to-end realistic conversation flows.
# ---------------------------------------------------------------------------

class TestRealisticFlows:
    def test_call_starts_english_drifts_hindi_correctly(self):
        """Lead picks up in English, then moves to Hindi. Hysteresis=2 means
        two full Hindi utterances are required."""
        state = LanguageState.initial(Lang.EN)
        state.update(utt("yes hello", Lang.EN))  # short, no effect
        t1 = state.update(utt("ji main Sunil bol raha hoon", Lang.HI))
        assert t1.switched is False  # first full pending
        t2 = state.update(utt("paint manufacturing karte hain hum", Lang.HI))
        assert t2.switched is True
        assert state.current == Lang.HI

    def test_call_stays_english_when_lead_only_dropped_filler_words(self):
        """Lead's main turns are English, with intermittent 'haan' / 'achha'
        fillers — the agent must stay in English."""
        state = LanguageState.initial(Lang.EN)
        utts = [
            ("we manufacture adhesives", Lang.EN),
            ("haan", Lang.HI),
            ("we need polyvinyl acetate roughly 8 tonnes monthly", Lang.EN),
            ("achha", Lang.HI),
            ("can you send pricing within 24 hours", Lang.EN),
        ]
        for text, lang in utts:
            state.update(utt(text, lang))
        assert state.current == Lang.EN

    def test_double_switch_en_to_hi_to_ta(self):
        """Lead switches twice in a call (rare but real).

        Tamil flips fast here because the second utterance has Tamil markers
        ('pesunga', 'naan') that trigger the marker-override path.
        """
        state = LanguageState.initial(Lang.EN)
        # Flip to Hindi — needs two full Hindi utterances.
        state.update(utt("hum bulk mein kharidte hain", Lang.HI))
        t1 = state.update(utt("pharma chemicals chahiye monthly basis pe", Lang.HI))
        assert t1.switched and state.current == Lang.HI
        # Tamil markers ("pesunga") trigger override → instant flip even with hysteresis=2.
        t2 = state.update(utt("naan finance head dhaan procurement head Ramesh-kitta pesunga", Lang.TA))
        assert t2.switched and state.current == Lang.TA


def test_response_hint_returns_current():
    state = LanguageState.initial(Lang.EN)
    assert get_response_language_hint(state) == Lang.EN
    state.current = Lang.TA
    assert get_response_language_hint(state) == Lang.TA


# ---------------------------------------------------------------------------
# Script-override gating: streaming STT hallucinates a random script for
# one-word backchannels (call 56e606ca: "ம்." for "hmm" flipped an English
# call into Tanglish). A single foreign-script ack must NEVER flip state;
# a full foreign-script sentence still flips instantly.
# ---------------------------------------------------------------------------

class TestScriptOverrideGating:
    def test_tamil_script_bare_ack_does_not_flip(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("ம்.", Lang.TA, conf=1.0))
        assert t.switched is False
        assert state.current == Lang.EN

    def test_devanagari_bare_ack_does_not_flip(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("अच्छा ठीक है।", Lang.HI, conf=1.0))
        assert t.switched is False
        assert state.current == Lang.EN

    def test_gujarati_ack_does_not_flip(self):
        # Gujarati isn't a supported Lang at all — must be a clean no-op.
        state = LanguageState.initial(Lang.HI)
        t = state.update(utt("ઓકે.", None, conf=1.0))
        assert t.switched is False
        assert state.current == Lang.HI

    def test_full_tamil_script_sentence_still_flips_instantly(self):
        state = LanguageState.initial(Lang.HI)
        t = state.update(utt("எனக்கு அண்ணா நகர்ல வீடு வேணும்", Lang.TA, conf=1.0))
        assert t.switched is True
        assert state.current == Lang.TA

    def test_full_devanagari_sentence_still_flips_instantly(self):
        state = LanguageState.initial(Lang.EN)
        t = state.update(utt("मुझे किराये पे दो बीएचके चाहिए", Lang.HI, conf=1.0))
        assert t.switched is True
        assert state.current == Lang.HI


class TestIsBareAck:
    def test_multi_script_acks(self):
        from voice_agent.language_state import is_bare_ack
        for text in ("ம்.", "ஓகே", "ઓકે.", "હા.", "ఓకే అండి.", "अच्छा ठीक है।",
                     "hmm", "ok ok", "haan ji"):
            assert is_bare_ack(text), text

    def test_content_is_not_an_ack(self):
        from voice_agent.language_state import is_bare_ack
        for text in ("ठीक है, Saturday chalega", "Budget is around",
                     "महिंद्रा सिटी।", "Anna Nagar mein"):
            assert not is_bare_ack(text), text
