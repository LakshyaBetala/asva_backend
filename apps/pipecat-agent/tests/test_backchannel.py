"""Tests for passive-listener / backchannel handling."""
from __future__ import annotations

from voice_agent.conversation_state import ConversationState
from voice_agent.streaming_orchestrator import (
    _is_backchannel,
    classify_lead_intent,
    should_end_call,
)


def test_pure_acks_are_backchannels():
    for t in ["acha", "achha", "haan", "haan haan", "hmm", "ok", "okay",
              "theek hai", "thik hai", "ji haan", "haan ji", "ok sir",
              "sahi hai", "haan boliye"]:
        assert _is_backchannel(t) is True, t


def test_content_utterances_are_not_backchannels():
    for t in ["theek hai bhej do", "haan mujhe caustic soda chahiye",
              "500 kg per month", "nahi chahiye", "kaun bol raha hai",
              "acha to aap kya rate dete ho"]:
        assert _is_backchannel(t) is False, t


def test_lone_theek_hai_is_backchannel_not_close():
    """Regression: a lone 'theek hai'/'ok' used to hang up the call."""
    conv = ConversationState()
    assert classify_lead_intent("theek hai", conv) == "backchannel"
    assert classify_lead_intent("ok", conv) == "backchannel"
    # But a real close phrase still closes.
    assert classify_lead_intent("theek hai bhej do", conv) == "close"


def test_backchannel_never_ends_call():
    conv = ConversationState()
    conv.backchannel_count = 5
    assert should_end_call("backchannel", conv) is False


def test_abuse_still_detected_over_backchannel():
    conv = ConversationState()
    assert classify_lead_intent("chutiya", conv) == "abuse"
