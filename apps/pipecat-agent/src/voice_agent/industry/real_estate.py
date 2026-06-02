"""Real estate industry brain — for broker tenants.

The MVP vertical. Brokers in Mumbai/Bangalore/Pune/Hyderabad pay ₹150-300
per Magicbricks/99acres lead and convert under 2%. The agent's job is
NOT to "qualify" in the corporate sense — it's to *book a site visit*
on the broker's calendar within the call, because a booking is the only
thing a broker will pay ₹8k/month for.

Languages: brokers operate in Hindi + English primarily, with regional
overlays. Tamil is intentionally NOT supported here — brokers don't
work Tamil Nadu (the SPC tenant has Tamil because it's Chennai-based).
Marathi/Kannada/Telugu cover Mumbai/Blr/Hyd respectively and are
written in deliberately English-loanword-heavy phrasing so Sarvam's
Bulbul model pronounces proper nouns and the brand name cleanly. The
native-language phrasing is conservative and should get a native-speaker
pass before being used at scale outside the bilingual MVP demos.

Slot schema is intentionally narrow: budget, locality, BHK, timeline,
and the actual slot they agree to. Anything more is conversational
overhead that loses the booking.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_agent.tenant_config import TenantConfig


_SUPPORTED_LANGS = ("en-IN", "hi-IN", "mr-IN", "kn-IN", "te-IN")


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
        if lang == "mr-IN":
            # Mumbai brokers — Marathi with English loanwords for crisp TTS.
            return (
                f"Namaskar {{name}} ji, mi {agent}, {company} madhun bolat aahe. "
                f"Tumhi property baddal vichar kelat — don minit bolu shakto ka?"
            )
        if lang == "kn-IN":
            # Bangalore brokers — Kannada w/ English property terms.
            return (
                f"Namaskara {{name}} avare, naanu {agent}, {company} inda "
                f"matadtha iddini. Property bagge interest ittu antha "
                f"thilkonde — ondu nimisha matadabahuda?"
            )
        if lang == "te-IN":
            # Hyderabad brokers — Telugu w/ English property terms.
            return (
                f"Namaskaram {{name}} garu, nenu {agent}, {company} nundi. "
                f"Meeru property gurinchi interest chupincharu — oka "
                f"nimisham maatladagalama?"
            )
        raise ValueError(
            f"real_estate brain does not support lang={lang!r}; "
            f"supported: {_SUPPORTED_LANGS}"
        )

    def slot_schema(self) -> dict[str, str]:
        return {
            "budget_range": "INR budget band (e.g. 80L-1.2Cr, 2-3Cr)",
            "locality": "preferred neighbourhood (e.g. Bandra, Powai, Whitefield, Hitech City)",
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
