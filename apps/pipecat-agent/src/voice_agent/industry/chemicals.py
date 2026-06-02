"""Chemicals industry brain (SPC tenant — frozen behavior).

This module captures the *current* Priya-for-SPC behavior as one industry
preset. Pre-tenant-config, these strings lived directly in prompts.py
and pain_library.py. Now they live here and are dispatched only when
`tenant.industry_key == "chemicals"`.

Do not change this module's outputs without coordinating with the SPC
tenant — they are an active client and changes to qualification slots
or intro text alter their live agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_agent.tenant_config import TenantConfig


@dataclass(frozen=True)
class _ChemicalsBrain:
    industry_key: str = "chemicals"

    def intro_template(self, lang: str, tenant: TenantConfig) -> str:
        agent = tenant.agent_name
        company = tenant.company_name
        city = tenant.city
        if lang == "en-IN":
            return (
                f"Hi {{name}}, this is {agent} from {company}, {city}. "
                f"Got two minutes?"
            )
        if lang == "hi-IN":
            return (
                f"Haan {{name}} ji, namaste! Main {agent}, {company} "
                f"{city} se. Do minute baat ho sakti hai?"
            )
        if lang == "ta-IN":
            # Spellings tuned for Sarvam Bulbul Tamil pronunciation.
            return (
                f"Vanakkam {{name}} sir, naan {agent}, {company} "
                f"{city}-la irundhu. Rendu nimisham pesalama?"
            )
        raise ValueError(
            f"chemicals brain does not support lang={lang!r}; "
            f"supported: ('en-IN', 'hi-IN', 'ta-IN')"
        )

    def slot_schema(self) -> dict[str, str]:
        return {
            "company_line": "what industry the lead's company operates in (pharma/paints/adhesives/etc)",
            "current_supplier": "the lead's current chemicals supplier",
            "monthly_volume": "approx monthly volume in tonnes/kg",
            "product_interest": "which SPC product they need (PSF, masterbatch, etc)",
            "decision_role": "is the lead the buyer, or who is",
        }

    def pain_overlay(self, lang: str) -> str:
        # Pain library is large enough that it lives in pain_library.py; the
        # overlay here is the short addendum to the base system prompt.
        # The full library is loaded by the LLM caller via that module.
        return (
            "You are selling polymer/chemical raw materials. Common objections: "
            "(1) price vs current supplier — answer with quality/consistency, "
            "(2) MOQ concerns — flexible MOQs available, "
            "(3) lead time worries — Chennai factory + pan-India dispatch. "
            "Never quote a number; the human team confirms pricing."
        )


BRAIN = _ChemicalsBrain()
