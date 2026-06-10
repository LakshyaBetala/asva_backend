"""Per-turn qualification slot extractor.

Runs in parallel with the response LLM call on every lead turn. Reads the
recent transcript, returns a structured QualificationSlots object with
8 fields + a per-slot 0..1 confidence map. The CRM lead panel renders
these live as the call progresses.

Design notes
------------
- This is a SEPARATE Gemini call from the response generator. Parallel
  execution keeps response latency unaffected.
- Slots are MERGED with the prior state, not replaced. Each new turn
  only updates slots the LLM is more confident about now than before.
- The LLM gets structured-output instructions (JSON schema in prompt);
  we parse + validate with Pydantic.
- On parse failure we keep the prior state — never corrupt slots on a
  bad LLM response.
- Buying confidence is the most important slot for live scoring. It's
  inferred from tone + commit words (e.g., "send quote", "let me check
  with my partner", "we'll think about it").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional


class BuyingFrequency(str, Enum):
    ONE_OFF = "one_off"
    MONTHLY = "monthly"
    AD_HOC = "ad_hoc"
    UNKNOWN = "unknown"


class DecisionRole(str, Enum):
    OWNER = "owner"
    PROCUREMENT = "procurement"
    ENGINEER = "engineer"
    ASSISTANT = "assistant"
    UNKNOWN = "unknown"


@dataclass
class QualificationSlots:
    """All 8 slots. None means 'not extracted yet'."""

    product_interest: Optional[str] = None
    volume_monthly_kg: Optional[int] = None
    buying_frequency: BuyingFrequency = BuyingFrequency.UNKNOWN
    current_supplier: Optional[str] = None
    pain_point: Optional[str] = None
    decision_role: DecisionRole = DecisionRole.UNKNOWN
    timeline_days: Optional[int] = None
    buying_confidence: float = 0.0

    # 0..1 confidence per slot. Used by CRM to dim uncertain slots.
    slot_confidence: dict[str, float] = field(default_factory=dict)

    def to_db_row(self, *, call_id: str, tenant_id: str, lead_id: str, turn_idx: int) -> dict:
        """Shape matches the qualification_slots table schema."""
        return {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "product_interest": self.product_interest,
            "volume_monthly_kg": self.volume_monthly_kg,
            "buying_frequency": self.buying_frequency.value,
            "current_supplier": self.current_supplier,
            "pain_point": self.pain_point,
            "decision_role": self.decision_role.value,
            "timeline_days": self.timeline_days,
            "buying_confidence": round(self.buying_confidence, 2),
            "slot_confidence": self.slot_confidence,
            "last_turn_idx": turn_idx,
        }

    def live_temperature(self, *, turn_idx: int = 0) -> str:
        """Live hot/warm/cold/unknown classification using only what's known now.

        Why this exists
        ---------------
        `score()` requires `spc_catalog` membership AND a decision_role —
        both rare in the first 4-5 turns, so it returns "cold" for everyone
        early on. The LLM then never gets a strong "this is hot, CLOSE" signal
        when the lead has actually given clear buying intent.

        This is the permissive live version:
          hot      → buying_confidence ≥ 0.7  OR  (pain + timeline ≤ 30d)
          warm     → at least one of: product_interest / current_supplier /
                     pain_point / volume / timeline   AND  buying_confidence ≥ 0.4
          cold     → 3+ turns elapsed and we still know nothing useful
          unknown  → too early to tell (first 2-3 turns, no signal yet)
        """
        if self.buying_confidence >= 0.7:
            return "hot"
        if (
            self.pain_point
            and self.timeline_days is not None
            and self.timeline_days <= 30
        ):
            return "hot"
        has_any_slot = (
            self.product_interest
            or self.volume_monthly_kg
            or self.current_supplier
            or self.pain_point
            or self.timeline_days is not None
        )
        if has_any_slot and self.buying_confidence >= 0.4:
            return "warm"
        # has_any_slot with low confidence is NOT auto-warm: the LLM
        # often fills product_interest from a passing mention. Require
        # at least 0.3 buying_confidence to count as warm.
        if has_any_slot and self.buying_confidence >= 0.3:
            return "warm"
        if turn_idx >= 3:
            return "cold"
        return "unknown"

    def score(self, spc_catalog: frozenset[str]) -> str:
        """Compute Hot/Warm/Cold from slots. Mirrors the scoring rule in spec section 4.3."""
        in_catalog = (
            self.product_interest is not None
            and any(term.lower() in self.product_interest.lower() for term in spc_catalog)
        )

        is_decision_maker = self.decision_role in {DecisionRole.OWNER, DecisionRole.PROCUREMENT}

        if (
            self.buying_confidence >= 0.7
            and self.timeline_days is not None
            and self.timeline_days <= 30
            and is_decision_maker
            and in_catalog
        ):
            return "hot"

        if (
            self.buying_confidence >= 0.5
            and in_catalog
            and (
                (self.timeline_days is not None and self.timeline_days <= 60)
                or self.current_supplier is not None
            )
        ):
            return "warm"

        return "cold"


# Prompt the LLM responds to. Structured-output via JSON-schema hint.
EXTRACTION_PROMPT = """\
You are extracting structured lead qualification data from a live real-estate
site-visit call transcript. The lead is a property buyer/renter; the agent
(Priya) is a broker booking a site visit.
Output ONLY valid JSON matching the schema below. No prose, no markdown fences.

Fields you must output (use null for not-yet-known):

{
  "product_interest": string|null,        // what they want: BHK + locality + buy/rent, e.g. "2 BHK Adyar, buy"
  "volume_monthly_kg": integer|null,      // NOT USED for real estate — always null
  "buying_frequency": "one_off"|"monthly"|"ad_hoc"|"unknown",  // real estate is "one_off"
  "current_supplier": string|null,        // other broker they're already working with, if any
  "pain_point": string|null,              // their key requirement / must-have (ready-to-move, parking, school nearby, budget cap)
  "decision_role": "owner"|"procurement"|"engineer"|"assistant"|"unknown",  // "owner"=decides themselves, "assistant"=needs family's ok, else "unknown"
  "timeline_days": integer|null,          // when they want possession / to move in (days)
  "buying_confidence": number,            // 0..1, how close they are to booking a site visit
  "slot_confidence": {                    // 0..1 per slot you populated
    "product_interest": number,
    "timeline_days": number,
    ...
  }
}

Rules:
1. If a slot value is the same as before, set its slot_confidence equal to or higher than before.
2. Buying_confidence 0.9+ requires a clear commitment: agreed to a site visit, "haan dikhaiye", "send me the address".
3. Buying_confidence 0.0-0.3 = polite refusal, "just browsing", "we'll think about it".
4. Buying_confidence 0.4-0.6 = engaged but non-committal (shared locality/BHK but no visit agreed yet).
5. Never make up a value you're <0.4 confident in. Use null.
6. NEVER invent a budget, price, area, or BHK the lead did not actually say.

Prior extracted slots (merge intelligently — only update slots you're more confident about now):
{PRIOR_SLOTS_JSON}

Transcript so far (most recent last):
{TRANSCRIPT_BLOCK}
"""


# A callable that takes (prompt) and returns the LLM's text response.
# Real implementation calls Gemini; tests inject a stub.
LlmCall = Callable[[str], Awaitable[str]]


async def extract_slots(
    *,
    transcript: list[dict],
    prior_slots: QualificationSlots,
    llm: LlmCall,
) -> QualificationSlots:
    """Extract / update qualification slots from the current transcript.

    On LLM/parse failure, returns prior_slots unchanged. We never corrupt
    state on a bad response.
    """
    transcript_block = "\n".join(
        f"{turn.get('speaker', '?')}: {turn.get('text', '')}" for turn in transcript[-12:]
    )
    prior_json = json.dumps(_slots_to_dict(prior_slots), ensure_ascii=False)

    prompt = (
        EXTRACTION_PROMPT
        .replace("{PRIOR_SLOTS_JSON}", prior_json)
        .replace("{TRANSCRIPT_BLOCK}", transcript_block)
    )

    try:
        raw = await llm(prompt)
    except Exception:
        return prior_slots

    parsed = _parse_llm_json(raw)
    if parsed is None:
        return prior_slots

    return _merge(prior_slots, parsed)


def _slots_to_dict(s: QualificationSlots) -> dict:
    return {
        "product_interest": s.product_interest,
        "volume_monthly_kg": s.volume_monthly_kg,
        "buying_frequency": s.buying_frequency.value,
        "current_supplier": s.current_supplier,
        "pain_point": s.pain_point,
        "decision_role": s.decision_role.value,
        "timeline_days": s.timeline_days,
        "buying_confidence": s.buying_confidence,
        "slot_confidence": s.slot_confidence,
    }


def _parse_llm_json(raw: str) -> dict | None:
    """Tolerant JSON parser — handles markdown fences the model sometimes adds."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Strip leading ```json\n and trailing ```
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _merge(prior: QualificationSlots, new: dict) -> QualificationSlots:
    """Merge new LLM output into prior slots.

    Rule: a slot updates only when the new confidence is >= prior confidence.
    Prevents the LLM from overwriting a well-known volume_monthly_kg with
    a guess on a later turn.
    """
    out = QualificationSlots(
        product_interest=prior.product_interest,
        volume_monthly_kg=prior.volume_monthly_kg,
        buying_frequency=prior.buying_frequency,
        current_supplier=prior.current_supplier,
        pain_point=prior.pain_point,
        decision_role=prior.decision_role,
        timeline_days=prior.timeline_days,
        buying_confidence=prior.buying_confidence,
        slot_confidence=dict(prior.slot_confidence),
    )

    new_conf = new.get("slot_confidence") or {}
    if not isinstance(new_conf, dict):
        new_conf = {}

    def _update_if_more_confident(field_name: str, new_val, parser=lambda x: x):
        prior_c = prior.slot_confidence.get(field_name, 0.0)
        nc = float(new_conf.get(field_name, 0.0) or 0.0)
        if new_val is None:
            return
        if nc < prior_c:
            return
        try:
            setattr(out, field_name, parser(new_val))
        except (ValueError, TypeError):
            return
        out.slot_confidence[field_name] = nc

    _update_if_more_confident("product_interest", new.get("product_interest"), lambda x: str(x) if x is not None else None)
    _update_if_more_confident("volume_monthly_kg", new.get("volume_monthly_kg"), int)
    _update_if_more_confident("current_supplier", new.get("current_supplier"), lambda x: str(x) if x is not None else None)
    _update_if_more_confident("pain_point", new.get("pain_point"), lambda x: str(x) if x is not None else None)
    _update_if_more_confident("timeline_days", new.get("timeline_days"), int)

    # Enum slots have their own merge logic.
    bf = new.get("buying_frequency")
    if bf and bf != BuyingFrequency.UNKNOWN.value:
        try:
            out.buying_frequency = BuyingFrequency(bf)
            out.slot_confidence["buying_frequency"] = float(new_conf.get("buying_frequency", 0.7) or 0.7)
        except ValueError:
            pass

    dr = new.get("decision_role")
    if dr and dr != DecisionRole.UNKNOWN.value:
        try:
            out.decision_role = DecisionRole(dr)
            out.slot_confidence["decision_role"] = float(new_conf.get("decision_role", 0.7) or 0.7)
        except ValueError:
            pass

    # Buying confidence: take the NEW value. It's tone-driven and reflects
    # the current moment, not a cumulative claim.
    bc = new.get("buying_confidence")
    if isinstance(bc, (int, float)):
        out.buying_confidence = max(0.0, min(1.0, float(bc)))

    return out
