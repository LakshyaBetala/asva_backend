"""Real estate industry brain — for broker tenants.

The MVP vertical. Brokers in Mumbai/Bangalore/Pune/Hyderabad pay ₹150-300
per Magicbricks/99acres lead and convert under 2%. The agent's job is
NOT to "qualify" in the corporate sense — it's to *book a site visit*
on the broker's calendar within the call, because a booking is the only
thing a broker will pay ₹8k/month for.

Slot schema is intentionally narrow: budget, locality, BHK, timeline,
and the actual slot they agree to. Anything more is conversational
overhead that loses the booking.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_agent.tenant_config import TenantConfig


@dataclass(frozen=True)
class _RealEstateBrain:
    industry_key: str = "real_estate"

    def intro_template(self, lang: str, tenant: TenantConfig) -> str:
        agent = tenant.agent_name
        company = tenant.company_name
        if lang == "en-IN":
            return (
                f"Hi {{name}}, this is {agent} from {company}. You'd shown "
                f"interest in property options — do you have a quick minute "
                f"to find one that fits?"
            )
        if lang == "hi-IN":
            return (
                f"Haan {{name}} ji, namaste! Main {agent}, {company} se. "
                f"Aapne property dekhne mein interest dikhaya tha — ek "
                f"minute baat kar sakte hain?"
            )
        # ta-IN
        return (
            f"Vanakkam {{name}} sir, naan {agent}, {company}-la irundhu. "
            f"Property paaka interest irundhuchu-nu therinjichi — oru "
            f"nimisham pesalama?"
        )

    def slot_schema(self) -> dict[str, str]:
        return {
            "budget_range": "INR budget band (e.g. 80L-1.2Cr, 2-3Cr)",
            "locality": "preferred neighbourhood (e.g. Bandra, Powai, Whitefield)",
            "bhk": "1 / 2 / 3 / 4+ BHK",
            "possession_timeline": "ready-to-move vs 6mo / 12mo / 24mo under-construction",
            "site_visit_slot": "ISO-8601 datetime they agreed to for a visit",
        }

    def pain_overlay(self, lang: str) -> str:
        return (
            "You are a real-estate appointment setter, not a salesperson. "
            "Your ONLY goal is to book a site visit on the broker's calendar. "
            "Do not quote prices, do not promise discounts, do not negotiate. "
            "Common objections and the canonical answer: "
            "(1) 'Just exploring' — offer a no-obligation 20-min visit this Saturday. "
            "(2) 'Too expensive' — ask budget, mention 'options across budgets'. "
            "(3) 'Will think and call back' — propose a tentative slot anyway, "
            "    say 'I'll hold it for 24h, cancel if it doesn't suit'. "
            "(4) 'I already have a broker' — ask if they've seen the new "
            "    inventory this week; offer one fresh option. "
            "Once they pick a day+time, REPEAT it back to confirm, then end the call."
        )


BRAIN = _RealEstateBrain()
