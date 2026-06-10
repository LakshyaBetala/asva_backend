"""Industry brain registry.

An IndustryBrain owns the *vertical-specific* parts of a call:

- Qualification slot schema (what we're trying to extract from the lead)
- Pain-point overlay (industry-specific objections and answers)
- Intro template per language (industry-flavoured first line)
- End-of-call hook (book a calendar slot, fire a WhatsApp, write a CRM
  note — whatever closes the loop for this vertical)

Brains are dispatched by `tenant.industry_key` at call start.
Add a new vertical = add a module here + register it below.
"""

from __future__ import annotations

from typing import Protocol

from voice_agent.tenant_config import TenantConfig


class IndustryBrain(Protocol):
    """Contract every industry module must satisfy."""

    industry_key: str

    def intro_template(self, lang: str, tenant: TenantConfig) -> str:
        """Return the opening line in the given language for this industry."""
        ...

    def slot_schema(self) -> dict[str, str]:
        """Map slot_name → one-line description of what to extract.

        Example for real_estate:
            {
                "budget_range": "lead's budget band in INR",
                "locality": "preferred neighbourhood",
                "bhk": "1/2/3 BHK preference",
                "possession_timeline": "ready-to-move vs under-construction",
                "site_visit_slot": "ISO-8601 datetime they agreed to",
            }
        """
        ...

    def pain_overlay(self, lang: str) -> str:
        """Industry-specific objection-handling addendum to the base prompt."""
        ...


from voice_agent.industry import real_estate as _real_estate
from voice_agent.industry import voice_agent_sales as _voice_agent_sales

_BRAINS: dict[str, IndustryBrain] = {
    _real_estate.BRAIN.industry_key: _real_estate.BRAIN,
    _voice_agent_sales.BRAIN.industry_key: _voice_agent_sales.BRAIN,
}


class IndustryNotFound(LookupError):
    """Raised when tenant.industry_key isn't registered."""


def get_brain(industry_key: str) -> IndustryBrain:
    brain = _BRAINS.get(industry_key)
    if brain is None:
        raise IndustryNotFound(
            f"industry_key={industry_key!r} not in registry "
            f"(known: {sorted(_BRAINS.keys())})"
        )
    return brain
