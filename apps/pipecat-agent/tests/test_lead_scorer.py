"""Unit tests for the post-call hot/warm/cold scorer."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from voice_agent.lead_scorer import (
    LeadScore,
    _coerce_score,
    _fallback_score,
    _format_transcript,
    score_call,
)


def test_format_transcript_skips_empty_turns():
    out = _format_transcript([
        {"speaker": "lead", "text": "hello"},
        {"speaker": "priya", "text": "  "},
        {"speaker": "lead", "text": "send me a quote"},
    ])
    assert "lead: hello" in out
    assert "send me a quote" in out
    assert "priya: " not in out  # empty priya turn skipped


def test_coerce_score_clamps_and_defaults_invalid_class():
    raw = {
        "classification": "boiling",
        "score_0_100": 250,
        "reason": "x" * 800,
        "summary": "y",
        "next_action": "buy_now",
    }
    out = _coerce_score(raw, {})
    assert out.classification == "cold"  # invalid class -> cold
    assert out.score == 100  # clamped
    assert len(out.reason) <= 500
    assert out.next_action == "followup_30d"  # invalid action -> default


def test_coerce_score_accepts_valid_inputs():
    raw = {
        "classification": "hot",
        "score_0_100": 92,
        "reason": "asked for quote with volume",
        "summary": "lead engaged on ethanol, asked for quote, 50 ton/month",
        "next_action": "human_callback_today",
    }
    out = _coerce_score(raw, {"product_interest": "ethanol"})
    assert out.classification == "hot"
    assert out.score == 92
    assert out.next_action == "human_callback_today"
    assert out.extracted == {"product_interest": "ethanol"}


def test_fallback_score_hot_when_confidence_high():
    out = _fallback_score(
        {"buying_confidence": 0.85, "product_interest": "ipa"},
        reason="test",
    )
    assert out.classification == "hot"
    assert out.next_action == "human_callback_today"


def test_fallback_score_hot_when_pain_plus_timeline():
    out = _fallback_score(
        {"pain_point": "supplier delays", "timeline_days": 14, "buying_confidence": 0.5},
        reason="test",
    )
    assert out.classification == "hot"


def test_fallback_score_warm_when_signal_no_confidence():
    out = _fallback_score(
        {"product_interest": "ethanol", "buying_confidence": 0.45},
        reason="test",
    )
    assert out.classification == "warm"
    assert out.next_action == "followup_3d"


def test_fallback_score_cold_when_no_signal():
    out = _fallback_score({"buying_confidence": 0.0}, reason="test")
    assert out.classification == "cold"
    assert out.next_action == "followup_30d"


def test_score_call_returns_fallback_on_empty_transcript():
    out = asyncio.run(score_call(
        transcript_turns=[],
        slots={"product_interest": "ipa"},
        api_key="fake",
    ))
    assert "Heuristic fallback" in out.reason


def test_score_call_strips_markdown_fences():
    fake_resp = AsyncMock(
        return_value=type("R", (), {
            "text": "```json\n{\"classification\":\"hot\",\"score_0_100\":88,"
                    "\"reason\":\"r\",\"summary\":\"s\","
                    "\"next_action\":\"send_quote\"}\n```",
        })()
    )
    with patch("voice_agent.lead_scorer.gemini_generate", new=fake_resp):
        out = asyncio.run(score_call(
            transcript_turns=[{"speaker": "lead", "text": "send quote"}],
            slots={},
            api_key="fake",
        ))
    assert out.classification == "hot"
    assert out.score == 88
    assert out.next_action == "send_quote"


def test_score_call_uses_fallback_on_bad_json():
    fake_resp = AsyncMock(
        return_value=type("R", (), {"text": "I think this lead is hot honestly"})()
    )
    with patch("voice_agent.lead_scorer.gemini_generate", new=fake_resp):
        out = asyncio.run(score_call(
            transcript_turns=[{"speaker": "lead", "text": "ok bye"}],
            slots={"buying_confidence": 0.1},
            api_key="fake",
        ))
    assert "Heuristic fallback" in out.reason
    assert out.classification == "cold"


def test_score_call_uses_fallback_on_gemini_error():
    fake_resp = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("voice_agent.lead_scorer.gemini_generate", new=fake_resp):
        out = asyncio.run(score_call(
            transcript_turns=[{"speaker": "lead", "text": "ok"}],
            slots={"buying_confidence": 0.8},
            api_key="fake",
        ))
    assert "Heuristic fallback" in out.reason
    assert out.classification == "hot"  # heuristic still classifies from slots
