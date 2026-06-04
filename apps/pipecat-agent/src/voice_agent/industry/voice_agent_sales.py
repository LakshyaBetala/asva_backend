"""Voice-agent-sales brain — Almmatix selling Almmatix to brokers.

This is the meta-brain. Priya here is NOT a tool a broker hires. Priya
IS the product, calling the broker to pitch them on hiring Priya.

Deep playbook lives in priya-voice-agent-sales.md:
- 5 broker types (HOT / INTERESTED-BUT-BUSY / SKEPTIC / PRICE-FOCUSED / REJECT)
- 18 canonical objection answers
- 3 ROI hooks (lead conversion / cost vs callers / time-to-call)
- 60-second opening sequence with built-in close
- North India dialect tuning (Delhi/Gurgaon/Punjab broker vibe)

Slot schema is narrow: this brain has ONE close (book a 15-minute demo
with the human team). Everything else is conversational context the
human team reads from the recording before the demo call.

Languages: Hindi primary (North India focus), English for premium
brokers, Punjabi for Punjab/Chandigarh. Tamil/Marathi explicitly NOT
supported — different brain (real_estate) handles those geographies.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_agent.tenant_config import TenantConfig


_SUPPORTED_LANGS = ("en-IN", "hi-IN", "pa-IN")


@dataclass(frozen=True)
class _VoiceAgentSalesBrain:
    industry_key: str = "voice_agent_sales"

    def intro_template(self, lang: str, tenant: TenantConfig) -> str:
        agent = tenant.agent_name
        # company_name is Almmatix; tenant.city is where the brand is based.

        if lang == "hi-IN":
            return (
                f"Haan {{name}} ji, namaste! Main {agent} bol rahi hoon "
                f"Almmatix se. Aapka real estate ka kaam hai na sir — "
                f"do minute baat ho sakti hai?"
            )
        if lang == "en-IN":
            return (
                f"Hi {{name}}, this is {agent} from Almmatix. You're in "
                f"real estate, right sir? Got two minutes — quick idea "
                f"on how to convert more of your Magicbricks-99acres leads."
            )
        if lang == "pa-IN":
            # Punjabi with English real-estate terms; conservative phrasing
            # for the Bulbul pa-IN voice. Native pass recommended at scale.
            return (
                f"Sat sri akal {{name}} ji, Main {agent} aan Almmatix ton. "
                f"Tusi real estate de kaam wich ho na ji — do minute "
                f"gal ho sakdi hai?"
            )
        raise ValueError(
            f"voice_agent_sales brain does not support lang={lang!r}; "
            f"supported: {_SUPPORTED_LANGS}"
        )

    def slot_schema(self) -> dict[str, str]:
        """One close: a 15-minute demo slot. Everything else is context."""
        return {
            "broker_focus": "what they sell — resale / new project / rental / mixed",
            "current_caller_count": "how many tele-callers they have today (0 / 1-2 / 3+)",
            "monthly_lead_volume": "approx leads/month from MB/99acres/walk-ins",
            "primary_pain": (
                "their named pain — slow_response / low_conversion / high_caller_cost / "
                "no_followup / quality_inconsistent"
            ),
            "objection_raised": "which objection they pushed back with (skeptic-of-AI / price / data-security / already-have-callers / etc.)",
            "demo_slot": "ISO-8601 datetime they agreed to for the 15-min demo (THE CLOSE)",
            "decision_role": "owner / partner / manager / employee — affects close pressure",
            "metro": "Delhi / Gurgaon / Noida / Lucknow / Chandigarh / Jaipur / other",
        }

    def required_to_close(self) -> tuple[str, ...]:
        """Only one slot truly required — the demo booking."""
        return ("demo_slot",)

    def pain_overlay(self, lang: str) -> str:
        """Per-turn reinforcement — survives long contexts to anchor the close."""
        return (
            "<almmatix_sales_focus>\n"
            "GOAL: Book a 15-min demo with founder Laksh Betala on the broker's "
            "Google Calendar. The Meet link is automatic.\n"
            "YOU ARE the product — every word is the demo. Natural, not robotic.\n"
            "If broker named ANY pain — drop ONE matching value point, close on slot.\n"
            "PRICING: NEVER quote a rupee number. Always defer with the canonical line "
            "— '4 plans hain usage ke hisaab se, Laksh demo mein aapke volume ke "
            "hisaab se exact number aur free pilot dikha denge'.\n"
            "If broker asks 'AI hai?' — yes, confidently, then turn it into value.\n"
            "If 4 minutes elapsed without a slot — one tentative close, then exit.\n"
            "ALLOWED TRUST SIGNALS: 'early-access cohort', 'pilot batch', "
            "'founder-onboarded', 'bootstrapped Indian startup', 'Bangalore-based', "
            "'Indian cloud infrastructure'.\n"
            "NEVER invent: paid-user counts, profit/revenue numbers, founder bio "
            "beyond 'Laksh Betala, technology background', guaranteed ROI %, "
            "features that don't ship today (CRM sync, public API, Salesforce). "
            "Defer everything else to 'Laksh demo mein dikha dega'.\n"
            "</almmatix_sales_focus>"
        )


BRAIN = _VoiceAgentSalesBrain()
