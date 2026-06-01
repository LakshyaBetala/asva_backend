"""Tests for cost_guard.py — daily cap, runaway watchdog, balance check."""
from __future__ import annotations

import time

import pytest

from voice_agent.cost_guard import (
    CallCostInputs,
    HARD_CAP_SECONDS,
    RUNAWAY_GRACE_SECONDS,
    check_runaway,
    estimate_call_cost_inr,
    evaluate_sarvam_balance,
    project_next_call_cost_inr,
    would_exceed_daily_cap,
)


class TestEstimateCost:
    def test_basic_180s_call(self):
        inp = CallCostInputs(
            lead_speak_seconds=60,
            priya_speak_seconds=60,
            turn_count=20,
            phrase_cache_hits=0,
            duration_seconds=180,
        )
        cost = estimate_call_cost_inr(inp)
        # Expected ~₹3 STT + ~₹3 TTS + ~₹5.40 Plivo + ~₹0.30 Gemini + ₹0.20 infra ≈ ₹11.90
        assert 11.0 < cost < 13.0

    def test_cache_hits_reduce_cost(self):
        no_cache = CallCostInputs(60, 60, 20, 0, 180)
        with_cache = CallCostInputs(60, 60, 20, 15, 180)
        assert estimate_call_cost_inr(with_cache) < estimate_call_cost_inr(no_cache)

    def test_short_hangup_is_cheap(self):
        inp = CallCostInputs(
            lead_speak_seconds=5,
            priya_speak_seconds=8,
            turn_count=2,
            phrase_cache_hits=0,
            duration_seconds=25,
        )
        assert estimate_call_cost_inr(inp) < 2.50

    def test_cache_savings_clamped_to_zero(self):
        """If cache hits exceed TTS minutes, savings can't make cost negative."""
        inp = CallCostInputs(
            lead_speak_seconds=10,
            priya_speak_seconds=2,
            turn_count=1,
            phrase_cache_hits=200,  # absurd
            duration_seconds=15,
        )
        assert estimate_call_cost_inr(inp) >= 0


class TestDailyCap:
    def test_fresh_day_does_not_exceed(self):
        exceed, total, headroom = would_exceed_daily_cap(
            spent_today_inr=0.0,
            daily_cap_inr=600.0,
        )
        assert exceed is False
        assert total < 600.0
        assert headroom == 600.0

    def test_near_cap_blocks_next_call(self):
        exceed, total, headroom = would_exceed_daily_cap(
            spent_today_inr=595.0,
            daily_cap_inr=600.0,
        )
        assert exceed is True

    def test_partial_day_allows(self):
        exceed, total, headroom = would_exceed_daily_cap(
            spent_today_inr=200.0,
            daily_cap_inr=600.0,
        )
        assert exceed is False
        assert headroom == 400.0

    def test_projected_180s_unit_in_reasonable_range(self):
        """A 180s call should project at ~₹10-13. Validates our model isn't broken."""
        cost = project_next_call_cost_inr(expected_duration_sec=180.0)
        assert 8.0 < cost < 14.0


class TestRunaway:
    def test_ok_within_hard_cap(self):
        start = time.monotonic()
        d = check_runaway(started_at_monotonic=start, now=start + 100)
        assert d.should_terminate is False
        assert d.reason == "ok"

    def test_hard_cap_triggers_at_360s(self):
        start = time.monotonic()
        d = check_runaway(started_at_monotonic=start, now=start + HARD_CAP_SECONDS + 1)
        assert d.should_terminate is True
        assert d.reason == "hard_cap"

    def test_runaway_triggers_past_grace(self):
        start = time.monotonic()
        d = check_runaway(
            started_at_monotonic=start,
            now=start + HARD_CAP_SECONDS + RUNAWAY_GRACE_SECONDS + 1,
        )
        assert d.should_terminate is True
        assert d.reason == "runaway"

    def test_exactly_at_cap_terminates(self):
        start = time.monotonic()
        d = check_runaway(started_at_monotonic=start, now=start + HARD_CAP_SECONDS)
        assert d.should_terminate is True


class TestBalanceAlert:
    def test_healthy_balance_no_alert(self):
        b = evaluate_sarvam_balance(
            credit_remaining_inr=500,
            credit_total_inr=1000,
        )
        assert b.raise_alert is False
        assert b.pct_remaining == 50.0

    def test_low_balance_alerts(self):
        b = evaluate_sarvam_balance(
            credit_remaining_inr=100,
            credit_total_inr=1000,
        )
        assert b.raise_alert is True
        assert b.pct_remaining == 10.0
        assert "top up" in b.message.lower()

    def test_zero_total_alerts(self):
        """API failed to return total: alert defensively."""
        b = evaluate_sarvam_balance(
            credit_remaining_inr=0,
            credit_total_inr=0,
        )
        assert b.raise_alert is True
