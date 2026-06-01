"""Tests for pipeline-level orchestration helpers (pure logic only).

The full Pipecat assembly is integration-tested on staging, not here.
"""
from __future__ import annotations

import time

import pytest

from voice_agent.language_state import Lang
from voice_agent.pipeline import (
    HARD_CAP_SECONDS,
    SOFT_CLOSE_SECONDS,
    SOFT_CLOSE_1_SECONDS,
    make_initial_context,
    render_intro_text,
    render_system_message_for_turn,
)


def _ctx(lang: str = "en-IN", name: str | None = "Ravi", company: str | None = "Acme"):
    return make_initial_context(
        call_id="c1",
        tenant_id="t1",
        lead_id="L1",
        lead_first_name=name,
        lead_company=company,
        default_lang=lang,
    )


def test_initial_context_starts_in_default_language():
    ctx = _ctx(lang="hi-IN")
    assert ctx.language_state.current == Lang.HI
    assert ctx.turn_idx == 0
    assert ctx.used_intro_cache is False


def test_system_message_reflects_current_language_after_switch():
    ctx = _ctx(lang="en-IN")
    msg1 = render_system_message_for_turn(ctx)
    assert "en-IN" in msg1

    # Simulate state machine flipping to Hindi
    ctx.language_state.current = Lang.HI
    msg2 = render_system_message_for_turn(ctx)
    assert "hi-IN" in msg2
    assert "en-IN" not in msg2.split("\n")[0]


def test_intro_text_uses_first_name_and_default_language():
    ctx = _ctx(lang="en-IN", name="Ravi")
    txt = render_intro_text(ctx)
    assert "Hi Ravi" in txt


def test_intro_text_falls_back_when_name_unusable():
    ctx = _ctx(lang="hi-IN", name="Unknown")
    txt = render_intro_text(ctx)
    assert "Unknown" not in txt
    assert "Priya" in txt


def test_soft_close_and_hard_stop_thresholds():
    ctx = _ctx()
    # Just-created context: nowhere near the caps.
    assert ctx.should_soft_close() is False
    assert ctx.should_hard_stop() is False

    # Fast-forward by mutating the start time.
    ctx.started_at_monotonic = time.monotonic() - SOFT_CLOSE_SECONDS - 1
    assert ctx.should_soft_close() is True
    assert ctx.should_hard_stop() is False

    ctx.started_at_monotonic = time.monotonic() - HARD_CAP_SECONDS - 1
    assert ctx.should_hard_stop() is True


def test_hard_cap_is_600_seconds_per_al_cred_billing():
    """600s hard cap supports 4-cred al_cred billing.

      0-150s    = 1 cred
      151-300s  = 2 creds
      301-450s  = 3 creds
      451-600s  = 4 creds (max)
    """
    assert HARD_CAP_SECONDS == 600
    assert SOFT_CLOSE_SECONDS == SOFT_CLOSE_1_SECONDS


def test_billed_units_match_al_cred_billing():
    """4-tier al_cred billing. Mirrors DB trigger."""
    import time as _t
    from voice_agent.pipeline import make_initial_context

    ctx = make_initial_context(
        call_id="c1", tenant_id="t1", lead_id="L1",
        lead_first_name=None, lead_company=None, default_lang="en-IN",
    )
    ctx.started_at_monotonic = _t.monotonic() - 100
    assert ctx.billed_units() == 1

    ctx.started_at_monotonic = _t.monotonic() - 149
    assert ctx.billed_units() == 1

    ctx.started_at_monotonic = _t.monotonic() - 200
    assert ctx.billed_units() == 2

    ctx.started_at_monotonic = _t.monotonic() - 299
    assert ctx.billed_units() == 2

    ctx.started_at_monotonic = _t.monotonic() - 350
    assert ctx.billed_units() == 3

    ctx.started_at_monotonic = _t.monotonic() - 449
    assert ctx.billed_units() == 3

    ctx.started_at_monotonic = _t.monotonic() - 500
    assert ctx.billed_units() == 4

    ctx.started_at_monotonic = _t.monotonic() - 600
    assert ctx.billed_units() == 4


def test_four_stage_soft_close():
    """140s, 290s, 440s, 580s soft-closes match the four al_cred boundaries."""
    import time as _t
    from voice_agent.pipeline import (
        make_initial_context,
        SOFT_CLOSE_1_SECONDS,
        SOFT_CLOSE_2_SECONDS,
        SOFT_CLOSE_3_SECONDS,
        SOFT_CLOSE_4_SECONDS,
    )

    ctx = make_initial_context(
        call_id="c1", tenant_id="t1", lead_id="L1",
        lead_first_name=None, lead_company=None, default_lang="en-IN",
    )
    ctx.started_at_monotonic = _t.monotonic() - (SOFT_CLOSE_1_SECONDS + 1)
    assert ctx.should_soft_close() is True
    assert ctx.should_soft_close_2() is False
    assert ctx.should_soft_close_3() is False
    assert ctx.should_soft_close_final() is False

    ctx.started_at_monotonic = _t.monotonic() - (SOFT_CLOSE_2_SECONDS + 1)
    assert ctx.should_soft_close_2() is True
    assert ctx.should_soft_close_3() is False

    ctx.started_at_monotonic = _t.monotonic() - (SOFT_CLOSE_3_SECONDS + 1)
    assert ctx.should_soft_close_3() is True
    assert ctx.should_soft_close_final() is False

    ctx.started_at_monotonic = _t.monotonic() - (SOFT_CLOSE_4_SECONDS + 1)
    assert ctx.should_soft_close_final() is True
    assert ctx.should_hard_stop() is False
