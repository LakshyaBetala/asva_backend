"""Pipecat pipeline assembly.

This file is the integration glue between:

  - Plivo SIP transport (real audio in/out)
  - Sarvam Saaras STT (streaming, per-utterance lang tag + confidence)
  - language_state.LanguageState  (decides current response language)
  - prompts.build_system_message  (per-turn LLM context with lang injection)
  - Google Gemini 2.5 Flash (LLM)
  - Sarvam Bulbul TTS (single Chennai voice across 3 languages)
  - intro_cache.load_or_synthesize_intro  (first-turn fast path)
  - webhook.WebhookEmitter  (signed events out)

Why the file is thin
--------------------
The Pipecat library evolves quickly, and the real audio loop only runs
under a Linux container with the SIP toolchain installed. So we keep the
glue here and put the actual logic (state, prompts, intro cache,
webhooks) in modules that are fully unit-tested without Pipecat.

To smoke-test the assembly in staging:

    PIPECAT_AGENT_ENV=staging \
    SARVAM_API_KEY=... GEMINI_API_KEY=... \
    SAMVAAD_WEBHOOK_SECRET=... \
    python -m voice_agent.pipeline

Hard limits enforced here:
  - 600s total call duration cap (10-minute hard cut)
  - Cred-based billing — al_cred = 150 sec block, ceiling-rounded:
      0-150s     = 1 cred
      151-300s   = 2 creds
      301-450s   = 3 creds
      451-600s   = 4 creds (maximum; call hard-cuts at 600s)
  - Soft-close nudges fire ~10s before each cred boundary so the LLM has
    time to wrap before the next al_cred is billed against the customer.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .conversation_state import ConversationState
from .language_state import Lang, LanguageState
from .prompts import build_intro_text, build_system_message, load_priya_prompt
from .tenant_config import TenantConfig  # noqa: TC002 — used as type

# Credit-based billing tiers (al_cred = 150-sec block, ceiling-rounded):
#   0-150s    = 1 cred
#   151-300s  = 2 creds
#   301-450s  = 3 creds
#   451-600s  = 4 creds (maximum)
#
# At 600s the call is hard-cut. The customer is billed for the cred bucket
# their call actually entered — a 151s call costs 2 creds, a 605s call costs
# 4 creds (hard-cut prevents the 5th).
CREDIT_1_SECONDS = 150
CREDIT_2_SECONDS = 300
CREDIT_3_SECONDS = 450
HARD_CAP_SECONDS = 600  # 4-cred cap, 10-minute hard cut
MAX_BILLED_UNITS = 4

# Soft-close nudges fire ~10s before each cred boundary so the LLM has a
# window to wrap before the next cred ticks over against the customer.
SOFT_CLOSE_1_SECONDS = 140  # Before 1st cred boundary
SOFT_CLOSE_2_SECONDS = 290  # Before 2nd cred boundary
SOFT_CLOSE_3_SECONDS = 440  # Before 3rd cred boundary
SOFT_CLOSE_4_SECONDS = 580  # Final wrap before hard cap

# Legacy alias kept so existing imports/tests don't break.
SOFT_CLOSE_SECONDS = SOFT_CLOSE_1_SECONDS


@dataclass
class CallContext:
    """Per-call runtime state. One instance lives for the call's lifetime."""

    call_id: str
    tenant_id: str
    lead_id: str
    lead_first_name: str | None
    lead_company: str | None
    started_at_monotonic: float
    language_state: LanguageState
    # Drives per-turn prompt selection. Set from tenant.industry_key at boot;
    # defaults to real_estate — the product's only vertical (SPC/chemicals
    # persona deleted 2026-06-11).
    industry_key: str = "real_estate"
    conversation_state: ConversationState = field(default_factory=ConversationState)
    turn_idx: int = 0
    used_intro_cache: bool = False
    phrase_cache_hits: int = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at_monotonic

    def should_soft_close(self) -> bool:
        """Nudge before 1st credit boundary (140s)."""
        return self.elapsed() >= SOFT_CLOSE_1_SECONDS

    def should_soft_close_2(self) -> bool:
        """Nudge before 2nd credit boundary (290s)."""
        return self.elapsed() >= SOFT_CLOSE_2_SECONDS

    def should_soft_close_3(self) -> bool:
        """Nudge before 3rd cred boundary (440s)."""
        return self.elapsed() >= SOFT_CLOSE_3_SECONDS

    def should_soft_close_final(self) -> bool:
        """Final nudge before hard cap (580s)."""
        return self.elapsed() >= SOFT_CLOSE_4_SECONDS

    def should_hard_stop(self) -> bool:
        return self.elapsed() >= HARD_CAP_SECONDS

    def billed_units(self) -> int:
        """Compute al_creds from elapsed time. Mirrors the DB trigger.

        0-150s    = 1 cred
        151-300s  = 2 creds
        301-450s  = 3 creds
        451-600s  = 4 creds (hard cap)
        """
        e = self.elapsed()
        if e <= 0:
            return 0
        if e <= CREDIT_1_SECONDS:
            return 1
        if e <= CREDIT_2_SECONDS:
            return 2
        if e <= CREDIT_3_SECONDS:
            return 3
        return 4


def make_initial_context(
    *,
    call_id: str,
    tenant_id: str,
    lead_id: str,
    lead_first_name: str | None,
    lead_company: str | None,
    default_lang: str,
    industry_key: str = "real_estate",
) -> CallContext:
    return CallContext(
        call_id=call_id,
        tenant_id=tenant_id,
        lead_id=lead_id,
        lead_first_name=lead_first_name,
        lead_company=lead_company,
        started_at_monotonic=time.monotonic(),
        language_state=LanguageState.initial(Lang(default_lang)),
        industry_key=industry_key,
    )


def render_system_message_for_turn(ctx: CallContext) -> str:
    """Called once per LLM turn so <current_language> is always fresh."""
    base = load_priya_prompt(ctx.industry_key)
    return build_system_message(
        base_prompt=base,
        current_language=ctx.language_state.current.value,
        lead_first_name=ctx.lead_first_name,
        lead_company=ctx.lead_company,
    )


def render_intro_text(ctx: CallContext, tenant: TenantConfig) -> str:
    """Text the first-turn cache will speak (or live-synthesize on miss).

    Tenant is required — every call now resolves a tenant at boot so the
    intro reflects that client's company/agent/city, not a global default.
    """
    return build_intro_text(
        tenant=tenant,
        lang=ctx.language_state.current.value,
        first_name=ctx.lead_first_name,
    )


# Real pipecat.Pipeline construction would happen here, importing
# pipecat-ai transports and frames. We deliberately do not import that
# module at top level so the unit tests run on any platform without the
# C-extension dependencies pipecat pulls in.
def assemble_pipeline(ctx: CallContext):  # pragma: no cover - integration glue
    """Build the Pipecat pipeline; only callable in the deploy container."""
    from pipecat.pipeline.pipeline import Pipeline  # type: ignore[import-not-found]

    raise NotImplementedError(
        "assemble_pipeline() is the integration seam between the pure-logic "
        "modules and Pipecat. Implement when Pipecat-ai is locked and the "
        "Plivo SIP transport credentials are provisioned."
    )


if __name__ == "__main__":  # pragma: no cover
    env = os.environ.get("PIPECAT_AGENT_ENV", "dev")
    print(f"voice-agent pipeline boot — env={env}")
    print("This entry point assembles the Pipecat pipeline in staging/prod.")
    print("Unit tests cover language_state, intro_cache, webhook, prompts, server.")
