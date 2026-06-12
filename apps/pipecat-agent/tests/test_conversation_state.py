"""Tests for conversation_state.py — phase machine + anti-AI sound enforcement."""
from __future__ import annotations

import pytest

from voice_agent.conversation_state import (
    EXTENSION_CONFIDENCE_FLOOR,
    FILLER_AUDIT_WINDOW,
    ConversationState,
    Phase,
    system_prompt_addendum,
)


class TestPhaseAdvancement:
    def test_starts_in_greeting(self):
        s = ConversationState()
        assert s.phase == Phase.GREETING

    def test_advances_through_phases_with_time(self):
        s = ConversationState()
        assert s.advance_phase_if_due(elapsed_sec=4.0, buying_confidence=0.5) == Phase.GREETING
        assert s.advance_phase_if_due(elapsed_sec=20.0, buying_confidence=0.5) == Phase.CONNECT
        assert s.advance_phase_if_due(elapsed_sec=60.0, buying_confidence=0.5) == Phase.DISCOVER
        assert s.advance_phase_if_due(elapsed_sec=100.0, buying_confidence=0.5) == Phase.QUALIFY
        assert s.advance_phase_if_due(elapsed_sec=160.0, buying_confidence=0.5) == Phase.CLOSE

    def test_never_goes_backwards(self):
        s = ConversationState()
        s.advance_phase_if_due(elapsed_sec=100.0, buying_confidence=0.5)
        assert s.phase == Phase.QUALIFY
        # Time travels backwards (shouldn't in real calls but defend anyway).
        assert s.advance_phase_if_due(elapsed_sec=10.0, buying_confidence=0.5) == Phase.QUALIFY
        assert s.phase == Phase.QUALIFY

    def test_extension_only_when_buying_confidence_high(self):
        s = ConversationState()
        s.advance_phase_if_due(elapsed_sec=160.0, buying_confidence=0.4)  # CLOSE
        # 200s with low confidence → stays in CLOSE (or moves to CLOSE)
        assert s.advance_phase_if_due(elapsed_sec=200.0, buying_confidence=0.4) == Phase.CLOSE
        # Same point with high confidence enters EXTENSION
        s2 = ConversationState()
        s2.advance_phase_if_due(elapsed_sec=160.0, buying_confidence=0.5)
        assert s2.advance_phase_if_due(elapsed_sec=200.0, buying_confidence=EXTENSION_CONFIDENCE_FLOOR) == Phase.EXTENSION

    def test_extension_sticks_once_entered(self):
        """Once in EXTENSION, confidence drop doesn't kick us out."""
        s = ConversationState()
        s.advance_phase_if_due(elapsed_sec=160.0, buying_confidence=0.7)
        s.advance_phase_if_due(elapsed_sec=200.0, buying_confidence=0.7)
        assert s.phase == Phase.EXTENSION
        # Confidence drops mid-extension — phase remains.
        assert s.advance_phase_if_due(elapsed_sec=250.0, buying_confidence=0.3) == Phase.EXTENSION


class TestAcknowledgmentTracking:
    def test_records_leading_ack(self):
        s = ConversationState()
        s.record_priya_turn("Got it. So you handle 500kg per month?")
        assert "got it" in s.used_acknowledgments

    def test_records_hindi_ack(self):
        s = ConversationState()
        s.record_priya_turn("Achha, aur delivery times kaise hain?")
        assert "achha" in s.used_acknowledgments

    def test_ignores_non_leading_ack(self):
        s = ConversationState()
        s.record_priya_turn("So you handle 500kg, got it.")
        # "got it" appears but not at start — we only track leading acks.
        assert "got it" not in s.used_acknowledgments

    def test_prompt_addendum_includes_used_acks(self):
        s = ConversationState()
        s.record_priya_turn("Got it. Question one.")
        s.record_priya_turn("Achha. Question two.")
        prompt = system_prompt_addendum(s)
        assert "got it" in prompt
        assert "achha" in prompt
        assert "used_acks" in prompt


class TestRecentTurnsBuffer:
    def test_keeps_last_window_of_turns_verbatim(self):
        # Window widened 4 -> 8 (2026-06-11) so a full qualification arc
        # stays in the LLM's rolling transcript.
        from voice_agent.conversation_state import RECENT_TURNS_WINDOW

        s = ConversationState()
        for i in range(RECENT_TURNS_WINDOW + 2):
            s.record_priya_turn(f"Turn number {i}")
        assert len(s.recent_priya_turns) == RECENT_TURNS_WINDOW
        assert s.recent_priya_turns[0] == "Turn number 2"
        assert s.recent_priya_turns[-1] == f"Turn number {RECENT_TURNS_WINDOW + 1}"

    def test_prompt_warns_against_paraphrasing(self):
        s = ConversationState()
        s.record_priya_turn("So you mainly buy solvents.")
        prompt = system_prompt_addendum(s)
        assert "So you mainly buy solvents." in prompt
        assert "DIFFERENT" in prompt


class TestFillerAudit:
    def test_passes_when_recent_turns_have_fillers(self):
        s = ConversationState()
        s.record_priya_turn("Haan ji, samjha.")
        s.record_priya_turn("Achha, that's interesting.")
        s.record_priya_turn("Okay, so what about pricing?")
        assert s.filler_audit_failing() is False

    def test_fails_when_recent_turns_have_no_fillers(self):
        s = ConversationState()
        s.record_priya_turn("Please share your monthly volume.")
        s.record_priya_turn("And the timeline for purchase.")
        s.record_priya_turn("Who handles procurement on your side?")
        assert s.filler_audit_failing() is True

    def test_no_audit_before_window_filled(self):
        s = ConversationState()
        # Only 2 turns — audit window is 3, so we don't judge yet.
        s.record_priya_turn("Please share your monthly volume.")
        s.record_priya_turn("And the timeline for purchase.")
        assert s.filler_audit_failing() is False

    def test_prompt_nudges_when_audit_failing(self):
        s = ConversationState()
        for _ in range(FILLER_AUDIT_WINDOW):
            s.record_priya_turn("Please share more details about your operation.")
        prompt = system_prompt_addendum(s)
        assert "filler" in prompt.lower()


class TestCloseLoop:
    def test_force_end_after_three_unanswered_close_attempts(self):
        s = ConversationState()
        s.note_close_attempt(lead_extended=False)
        s.note_close_attempt(lead_extended=False)
        assert s.should_force_end() is False
        s.note_close_attempt(lead_extended=False)
        assert s.should_force_end() is True

    def test_lead_engagement_resets_counter(self):
        s = ConversationState()
        s.note_close_attempt(lead_extended=False)
        s.note_close_attempt(lead_extended=False)
        s.note_close_attempt(lead_extended=True)  # lead said something substantive
        assert s.consecutive_close_attempts == 0
        assert s.should_force_end() is False


class TestPhaseDirectives:
    @pytest.mark.parametrize("phase,expected_substring", [
        (Phase.CONNECT, "renting"),
        (Phase.DISCOVER, "must-have"),
        (Phase.QUALIFY, "budget"),
        (Phase.CLOSE, "close"),
        (Phase.EXTENSION, "close"),
    ])
    def test_addendum_includes_phase_directive(self, phase: Phase, expected_substring: str):
        s = ConversationState(phase=phase)
        prompt = system_prompt_addendum(s)
        assert expected_substring in prompt


class TestNativeTamilScriptMode:
    def test_native_pin_active_on_sarvam_stack(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "sarvam")
        monkeypatch.delenv("TTS_NATIVE_TA", raising=False)
        s = ConversationState()
        prompt = system_prompt_addendum(s, language="ta-IN")
        assert "TAMIL SCRIPT" in prompt
        assert "ROMAN SCRIPT ONLY" not in prompt

    def test_roman_tanglish_on_other_stacks(self, monkeypatch):
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        s = ConversationState()
        prompt = system_prompt_addendum(s, language="ta-IN")
        assert "TANGLISH" in prompt
        assert "ROMAN SCRIPT ONLY" in prompt

    def test_native_ta_kill_switch(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "sarvam")
        monkeypatch.setenv("TTS_NATIVE_TA", "0")
        s = ConversationState()
        prompt = system_prompt_addendum(s, language="ta-IN")
        assert "TANGLISH" in prompt

    def test_hindi_gets_colloquial_pin(self, monkeypatch):
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        s = ConversationState()
        prompt = system_prompt_addendum(s, language="hi-IN")
        assert "COLLOQUIAL HINGLISH" in prompt
