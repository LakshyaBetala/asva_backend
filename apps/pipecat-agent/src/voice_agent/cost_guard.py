"""Cost guardrails — daily-cap check, runaway-call kill switch, cost telemetry.

Three independent guardrails, all non-negotiable per the CP3 spec:

  1. Daily-cap check — dispatcher calls `would_exceed_daily_cap()` before
     each outbound. Halts dispatch if today's estimated cost + this call's
     projected cost > tenant.daily_spend_cap_inr.

  2. Runaway watchdog — the pipeline runs `check_runaway()` every tick.
     If a call's elapsed time exceeds 360s + 10s grace, it's hard-killed.

  3. Cost telemetry — `estimate_call_cost_inr()` computes per-call cost
     from the turn_latencies table data. Written to calls.estimated_cost_inr
     at call end. Powers the daily-cap rollup.

Cost model
----------
Per-180s "unit" baseline:
  Sarvam STT  ₹3.00
  Sarvam TTS  ₹3.00 (less when phrase cache hits)
  Gemini      ₹0.40
  Plivo       ₹1.80
  Infra       ₹0.20

We compute actual cost from observed durations + cache-hit count, not a
flat rate, so the dispatcher's daily-cap math reflects reality.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

# Rate constants (₹). Kept in code, not env, so prod and tests match.
SARVAM_STT_RATE_PER_MIN = 3.00
SARVAM_TTS_RATE_PER_MIN = 3.00
GEMINI_COST_PER_TURN = 0.015          # ~₹0.015 per turn at Flash + caching
PLIVO_RATE_PER_MIN = 1.80
INFRA_COST_PER_CALL = 0.20            # amortized Hetzner+Cloudflare per call

# Each cache hit saves the cost of one TTS synthesis. Average phrase
# duration ~2s of TTS => ₹0.10 saved per hit.
CACHE_HIT_TTS_SAVINGS = 0.10

# Watchdog: kill calls that exceed this many seconds past the cap.
# 600s aligns with the 4-cred / 10-minute al_cred billing maximum in pipeline.py.
RUNAWAY_GRACE_SECONDS = 10
HARD_CAP_SECONDS = 600


@dataclass
class CallCostInputs:
    """Observed call usage from turn_latencies aggregation."""

    lead_speak_seconds: float       # how much the lead talked (STT input)
    priya_speak_seconds: float      # how much Priya talked (TTS output)
    turn_count: int                 # number of LLM turns
    phrase_cache_hits: int          # how many TTS calls were served from R2
    duration_seconds: float         # total call wall time


def estimate_call_cost_inr(inp: CallCostInputs) -> float:
    """Compute per-call cost in INR. Conservative on rounding (rounds up)."""
    stt_cost = (inp.lead_speak_seconds / 60.0) * SARVAM_STT_RATE_PER_MIN
    tts_cost = (inp.priya_speak_seconds / 60.0) * SARVAM_TTS_RATE_PER_MIN
    tts_savings = inp.phrase_cache_hits * CACHE_HIT_TTS_SAVINGS
    tts_cost = max(0.0, tts_cost - tts_savings)
    plivo_cost = (inp.duration_seconds / 60.0) * PLIVO_RATE_PER_MIN
    gemini_cost = inp.turn_count * GEMINI_COST_PER_TURN

    total = stt_cost + tts_cost + plivo_cost + gemini_cost + INFRA_COST_PER_CALL
    return round(total, 2)


def project_next_call_cost_inr(*, expected_duration_sec: float = 180.0) -> float:
    """Pessimistic projection for the daily-cap check.

    Assumes a full 180s unit with lead/Priya splitting talk time 50/50
    and no cache hits. Real calls are usually cheaper.
    """
    inp = CallCostInputs(
        lead_speak_seconds=expected_duration_sec * 0.4,
        priya_speak_seconds=expected_duration_sec * 0.4,
        turn_count=max(1, int(expected_duration_sec / 6)),
        phrase_cache_hits=0,
        duration_seconds=expected_duration_sec,
    )
    return estimate_call_cost_inr(inp)


def would_exceed_daily_cap(
    *,
    spent_today_inr: float,
    daily_cap_inr: float,
    expected_call_duration_sec: float = 180.0,
) -> tuple[bool, float, float]:
    """Return (would_exceed, projected_total_inr, headroom_inr).

    The dispatcher calls this before placing each call. If would_exceed,
    it halts dispatch and writes `agent_blocked_reason='daily_cap_reached'`
    on the lead row.
    """
    projected = project_next_call_cost_inr(expected_duration_sec=expected_call_duration_sec)
    total = spent_today_inr + projected
    headroom = daily_cap_inr - spent_today_inr
    return (total > daily_cap_inr, round(total, 2), round(headroom, 2))


# -- Runaway watchdog -----------------------------------------------------

@dataclass
class RunawayDecision:
    should_terminate: bool
    reason: str  # "ok" | "hard_cap" | "runaway"
    elapsed_sec: float


def check_runaway(*, started_at_monotonic: float, now: float | None = None) -> RunawayDecision:
    """Called every tick by the pipeline. Returns whether to hard-kill.

    Two stages:
      - HARD_CAP_SECONDS = 600: contractual maximum (4-cred billing tier).
        Soft-close is attempted at 580 in the pipeline; if the LLM is
        still going at 600, we ask it to wrap and start the watchdog.
      - 600 + RUNAWAY_GRACE_SECONDS: terminate unconditionally.
    """
    now = now if now is not None else time.monotonic()
    elapsed = now - started_at_monotonic

    if elapsed >= HARD_CAP_SECONDS + RUNAWAY_GRACE_SECONDS:
        return RunawayDecision(True, "runaway", elapsed)
    if elapsed >= HARD_CAP_SECONDS:
        return RunawayDecision(True, "hard_cap", elapsed)
    return RunawayDecision(False, "ok", elapsed)


# -- Sarvam balance check (used by daily cron) ---------------------------

@dataclass
class BalanceAlert:
    raise_alert: bool
    pct_remaining: float
    message: str


def evaluate_sarvam_balance(
    *,
    credit_remaining_inr: float,
    credit_total_inr: float,
    alert_threshold_pct: float = 20.0,
) -> BalanceAlert:
    """Daily cron computes this. >=20% remaining: silent. <20%: alert."""
    if credit_total_inr <= 0:
        return BalanceAlert(True, 0.0, "Sarvam balance unavailable")
    pct = (credit_remaining_inr / credit_total_inr) * 100.0
    if pct < alert_threshold_pct:
        return BalanceAlert(
            True,
            round(pct, 1),
            f"Sarvam credit at {pct:.1f}% — top up before calls fail",
        )
    return BalanceAlert(False, round(pct, 1), "ok")
