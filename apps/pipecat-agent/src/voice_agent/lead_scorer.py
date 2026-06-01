"""Post-call lead scorer.

Fires once when the call ends. Takes the full transcript + the final
QualificationSlots and asks Gemini Flash to produce a structured
classification for the CRM. Persisted via insert_lead_score.

This is the system of record for hot/warm/cold in the CRM. The in-call
live_temperature() in qualification.py is a UI hint for the agent during
the call; this is the authoritative post-call verdict.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from voice_agent.gemini_llm import generate as gemini_generate

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

SCORING_PROMPT = """\
You are scoring a B2B sales call for Supreme Petrochemicals, Chennai.
The agent (Priya) made a Tamil/Hindi/English outbound cold call.

Output ONLY valid JSON, no prose, no markdown:

{
  "classification": "hot" | "warm" | "cold" | "dead",
  "score_0_100": integer,
  "reason": string (one sentence, why this classification),
  "summary": string (2-3 sentences, what happened on the call),
  "next_action": string (one concrete action for the human team)
}

Rules for classification:
  hot   = explicit buying signal (asked for quote, gave volume + timeline <= 30d,
          named decision-maker, said "send sample/proforma")
  warm  = engaged, qualified as a real buyer, but no immediate ask
          (knows the product, has supplier history, may buy in 1-3 months)
  cold  = answered but no real interest signal / wrong fit / brushed off
  dead  = abused, hung up immediately, wrong number, DND, language barrier

Score rubric (0-100):
  90-100 = hot, must call back today
  70-89  = warm, follow-up within 3 days
  40-69  = cold, monthly nurture
  0-39   = dead, do-not-call

next_action options (pick one):
  - "human_callback_today" — hot, time-sensitive
  - "send_quote" — they asked for quote/pricing
  - "send_proforma" — they asked for proforma invoice
  - "send_sample" — they asked for samples
  - "followup_3d" — warm, schedule follow-up in 3 days
  - "followup_30d" — cold, schedule monthly nurture
  - "dnc" — dead, mark do-not-call

Extracted slots (Priya's understanding at call end):
{SLOTS_JSON}

Full transcript (lead = customer, priya = agent):
{TRANSCRIPT_BLOCK}
"""


@dataclass(frozen=True)
class LeadScore:
    classification: str  # hot | warm | cold | dead
    score: int           # 0..100
    reason: str
    summary: str
    next_action: str
    extracted: dict[str, Any]


_VALID_CLASSIFICATIONS = {"hot", "warm", "cold", "dead"}
_VALID_ACTIONS = {
    "human_callback_today", "send_quote", "send_proforma",
    "send_sample", "followup_3d", "followup_30d", "dnc",
}


def _format_transcript(turns: list[dict[str, str]]) -> str:
    """turns = [{'speaker': 'lead'|'priya', 'text': '...'}, ...]"""
    lines = []
    for t in turns:
        spk = t.get("speaker", "lead")
        txt = (t.get("text") or "").strip()
        if not txt:
            continue
        lines.append(f"{spk}: {txt}")
    return "\n".join(lines)


def _build_prompt(*, transcript_turns: list[dict[str, str]], slots: dict[str, Any]) -> str:
    return (
        SCORING_PROMPT
        .replace("{SLOTS_JSON}", json.dumps(slots, ensure_ascii=False))
        .replace("{TRANSCRIPT_BLOCK}", _format_transcript(transcript_turns))
    )


def _coerce_score(raw: dict[str, Any], slots: dict[str, Any]) -> LeadScore:
    cls = str(raw.get("classification", "cold")).lower().strip()
    if cls not in _VALID_CLASSIFICATIONS:
        cls = "cold"
    score = int(raw.get("score_0_100") or 0)
    score = max(0, min(100, score))
    action = str(raw.get("next_action", "followup_30d")).lower().strip()
    if action not in _VALID_ACTIONS:
        action = "followup_30d"
    return LeadScore(
        classification=cls,
        score=score,
        reason=str(raw.get("reason") or "").strip()[:500],
        summary=str(raw.get("summary") or "").strip()[:1000],
        next_action=action,
        extracted=slots,
    )


def _fallback_score(slots: dict[str, Any], reason: str) -> LeadScore:
    """If Gemini fails or returns garbage, derive a heuristic score from slots
    so the CRM still gets a row. Never let scoring failure block the call."""
    bc = float(slots.get("buying_confidence") or 0.0)
    has_signal = bool(
        slots.get("product_interest") or slots.get("current_supplier")
        or slots.get("pain_point")
    )
    timeline = slots.get("timeline_days")
    if bc >= 0.7 or (slots.get("pain_point") and timeline and timeline <= 30):
        cls, sc, act = "hot", 80, "human_callback_today"
    elif has_signal and bc >= 0.4:
        cls, sc, act = "warm", 60, "followup_3d"
    elif has_signal:
        cls, sc, act = "warm", 50, "followup_3d"
    else:
        cls, sc, act = "cold", 25, "followup_30d"
    return LeadScore(
        classification=cls, score=sc,
        reason=f"Heuristic fallback ({reason})",
        summary="LLM scorer unavailable — used slot-based heuristic.",
        next_action=act, extracted=slots,
    )


async def score_call(
    *,
    transcript_turns: list[dict[str, str]],
    slots: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> LeadScore:
    """One-shot scoring. Returns a LeadScore even if the LLM fails — the
    CRM must always get a verdict, even if it's heuristic."""
    if not transcript_turns:
        return _fallback_score(slots, "empty transcript")

    prompt = _build_prompt(transcript_turns=transcript_turns, slots=slots)
    try:
        resp = await gemini_generate(
            system_message="You are a strict JSON-only B2B sales call scorer for Tamil/Hindi/English calls.",
            user_message=prompt,
            api_key=api_key,
            model=model,
            generation_config={"temperature": 0.2, "maxOutputTokens": 500},
        )
    except Exception as exc:
        logger.warning("lead_scorer Gemini call failed: %s", exc)
        return _fallback_score(slots, f"gemini error: {type(exc).__name__}")

    text = resp.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("lead_scorer non-JSON response: %s", text[:200])
        return _fallback_score(slots, "bad JSON")

    return _coerce_score(parsed, slots)
