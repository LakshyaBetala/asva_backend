"""Real estate industry brain — for broker tenants.

The MVP vertical. Brokers in Mumbai/Bangalore/Pune/Hyderabad pay ₹150-300
per Magicbricks/99acres lead and convert under 2%. The agent's job is
NOT to "qualify" in the corporate sense — it's to *book a site visit*
on the broker's calendar within the call, because a booking is the only
thing a broker will pay ₹8k/month for.

The deep behavior (lead-type playbook, objection answers, never-quote-
price rule, end-of-call checklist) lives in
`packages/shared/src/prompts/priya-real-estate.md` and is loaded by
prompts.load_priya_prompt("real_estate"). This module owns the
*structured* parts: slot schema, locality knowledge, pain overlay
distilled into the LLM's per-turn addendum.

Languages: brokers operate in Hindi + English primarily, with regional
overlays. Tamil is intentionally NOT supported (Tamil is the SPC tenant
only — brokers don't work Tamil Nadu).
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_agent.tenant_config import TenantConfig


_SUPPORTED_LANGS = ("en-IN", "hi-IN", "mr-IN", "kn-IN", "te-IN")


# --- Locality knowledge ----------------------------------------------------
#
# Used for transcript normalization ("Bandar" → "Bandra West"), broker
# tenant onboarding (which metros they serve), and downstream filtering on
# the broker dashboard. Lowercased lookup → canonical English spelling.

LOCALITIES: dict[str, tuple[str, ...]] = {
    "Mumbai": (
        "Bandra West", "Bandra East", "Khar", "Santacruz West", "Santacruz East",
        "Juhu", "Andheri West", "Andheri East", "Powai", "Vikhroli", "Mulund",
        "Goregaon West", "Goregaon East", "Malad West", "Malad East", "Borivali",
        "Thane West", "Thane East", "Worli", "Lower Parel", "Dadar West",
        "Dadar East", "Matunga", "Chembur", "Ghatkopar", "Kandivali", "Vasai",
        "Virar", "Navi Mumbai", "Vashi", "Kharghar",
    ),
    "Pune": (
        "Koregaon Park", "Kalyani Nagar", "Viman Nagar", "Wakad", "Baner",
        "Aundh", "Hinjewadi", "Kothrud", "Magarpatta", "Hadapsar", "Kharadi",
        "Pimpri", "Chinchwad", "Wagholi", "Undri", "Pisoli", "Balewadi",
    ),
    "Bangalore": (
        "Whitefield", "HSR Layout", "Koramangala", "Indiranagar", "JP Nagar",
        "Jayanagar", "Banashankari", "Hebbal", "Yelahanka", "Sarjapur Road",
        "Marathahalli", "Bellandur", "Electronic City", "Bannerghatta Road",
        "Kanakapura Road", "BTM Layout", "RT Nagar", "Rajajinagar", "Malleshwaram",
        "Frazer Town", "Cox Town", "Old Airport Road",
    ),
    "Hyderabad": (
        "Banjara Hills", "Jubilee Hills", "Hitech City", "Madhapur", "Kondapur",
        "Gachibowli", "Kukatpally", "Miyapur", "Manikonda", "Begumpet",
        "Secunderabad", "Ameerpet", "SR Nagar", "Tolichowki", "Mehdipatnam",
        "Uppal", "LB Nagar",
    ),
}


# Common phonetic transcription drifts → canonical spelling. Used by the
# transcript normalizer to repair STT confusions before slot extraction.
LOCALITY_ALIASES: dict[str, str] = {
    "bandar": "Bandra West", "bandara": "Bandra West", "vandre": "Bandra West",
    "pooway": "Powai", "pavai": "Powai", "powae": "Powai",
    "andheri west": "Andheri West", "andheri east": "Andheri East",
    "kankubadi": "Kanakapura Road",
    "white field": "Whitefield", "whitfield": "Whitefield",
    "hsr": "HSR Layout", "h s r": "HSR Layout",
    "hi tech city": "Hitech City", "high tech city": "Hitech City",
    "jubli hills": "Jubilee Hills", "jubily hills": "Jubilee Hills",
    "banjara": "Banjara Hills", "banzara hills": "Banjara Hills",
    "gachi bowli": "Gachibowli", "gatchi bowli": "Gachibowli",
    "koramangla": "Koramangala", "koregaon": "Koregaon Park",
    "vakad": "Wakad", "hinjwadi": "Hinjewadi", "hinjawadi": "Hinjewadi",
    "kalyani": "Kalyani Nagar", "viman": "Viman Nagar",
    "indra nagar": "Indiranagar", "indira nagar": "Indiranagar",
}


def canonical_locality(raw: str) -> str | None:
    """Map a fuzzy / misspelled locality mention to its canonical name.

    Returns None if no confident match — caller should keep the raw string
    so the broker can correct manually rather than mis-routing a lead.
    """
    lower = raw.strip().lower()
    if not lower:
        return None
    if lower in LOCALITY_ALIASES:
        return LOCALITY_ALIASES[lower]
    for metro_localities in LOCALITIES.values():
        for canonical in metro_localities:
            if lower == canonical.lower():
                return canonical
    return None


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
            return (
                f"Namaskar {{name}} ji, mi {agent}, {company} madhun bolat aahe. "
                f"Tumhi property baddal vichar kelat — don minit bolu shakto ka?"
            )
        if lang == "kn-IN":
            return (
                f"Namaskara {{name}} avare, naanu {agent}, {company} inda "
                f"matadtha iddini. Property bagge interest ittu antha "
                f"thilkonde — ondu nimisha matadabahuda?"
            )
        if lang == "te-IN":
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
        """Broker-grade qualification slots, in extraction-priority order.

        intent + budget + locality + bhk + slot is sufficient to book.
        purpose + loan_status are bonus signals for the broker's dashboard
        but should NOT block the close — never withhold a booking because
        these are missing.
        """
        return {
            "intent": "buy / rent / not_sure_yet",
            "budget_range": "INR band, e.g. '80L-1.2Cr' or '15k-30k for rent'",
            "locality": "neighbourhood; canonical English spelling (e.g. 'Bandra West')",
            "bhk": "1 / 2 / 3 / 4+ BHK",
            "possession_timeline": "ready_to_move / 6mo / 12mo / 24mo under_construction",
            "purpose": "self_use / investment / family / mixed",
            "loan_status": "pre_approved / will_apply / cash_buyer / unknown",
            "family_size": "number of people who'll live there (drives BHK fit)",
            "amenity_must_have": "free-text — parking, gym, security, pet_friendly, veg_society",
            "school_zone": "child's school name OR area if school-driven",
            "site_visit_slot": "ISO-8601 datetime they agreed to (THE CLOSE)",
            "source_channel": "magicbricks / 99acres / referral / walk_in / unknown",
        }

    def required_to_close(self) -> tuple[str, ...]:
        """Minimum slots needed to put a booking on the broker's calendar."""
        return ("intent", "budget_range", "locality", "bhk", "site_visit_slot")

    def pain_overlay(self, lang: str) -> str:
        """Per-turn reinforcement appended after the base prompt.

        Deep behavior lives in priya-real-estate.md (loaded as base_prompt).
        This overlay is a *terse* reminder that survives long contexts and
        catches the LLM when it drifts mid-call. Kept under ~12 lines so it
        does not blow out the per-turn context budget.
        """
        return (
            "<broker_focus>\n"
            "GOAL: book a site visit. Not selling property. Not quoting price.\n"
            "If lead names a slot (Saturday 4pm) — confirm + repeat back + end call.\n"
            "If lead asks price — defer: 'Broker uncle site pe exact rate confirm karenge.'\n"
            "If lead has named budget + locality + BHK — propose a slot NOW.\n"
            "After 4 minutes without a slot — try ONE tentative slot, then end.\n"
            "Never invent inventory. Never name competing platforms first.\n"
            "</broker_focus>"
        )


BRAIN = _RealEstateBrain()
