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


_SUPPORTED_LANGS = ("en-IN", "hi-IN", "ta-IN", "mr-IN", "kn-IN", "te-IN")


# --- Locality knowledge ----------------------------------------------------
#
# Used for transcript normalization ("Bandar" → "Bandra West"), broker
# tenant onboarding (which metros they serve), and downstream filtering on
# the broker dashboard. Lowercased lookup → canonical English spelling.

LOCALITIES: dict[str, tuple[str, ...]] = {
    "Chennai": (
        "T. Nagar", "Adyar", "Mylapore", "Velachery", "Anna Nagar",
        "Besant Nagar", "Nungambakkam", "Kilpauk", "Egmore", "Pondy Bazaar",
        "Tambaram", "Porur", "Sholinganallur", "OMR", "ECR", "Perambur",
        "Vadapalani", "Saidapet", "Chromepet", "Pallikaranai", "Thoraipakkam",
        "Adambakkam", "Guindy", "Kodambakkam", "Ashok Nagar", "Thiruvanmiyur",
        "Madipakkam", "Medavakkam", "Navalur", "Kelambakkam", "Royapettah",
    ),
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
    # Chennai phonetic drifts (STT mishears these constantly on 8kHz lines).
    "te nagar": "T. Nagar", "tee nagar": "T. Nagar", "tnagar": "T. Nagar",
    "tinagar": "T. Nagar", "thyagaraya nagar": "T. Nagar", "t nagar": "T. Nagar",
    "adayar": "Adyar", "adyaar": "Adyar", "adiyar": "Adyar",
    "mylapur": "Mylapore", "mylaapore": "Mylapore", "mylai": "Mylapore",
    "velacheri": "Velachery", "velasseri": "Velachery", "velachary": "Velachery",
    "annanagar": "Anna Nagar", "anna nagar": "Anna Nagar",
    "besent nagar": "Besant Nagar", "besant nagar": "Besant Nagar",
    "nungabakkam": "Nungambakkam", "nungumbakkam": "Nungambakkam",
    "omr road": "OMR", "old mahabalipuram road": "OMR",
    "ecr road": "ECR", "east coast road": "ECR",
    "solinganallur": "Sholinganallur", "cholinganallur": "Sholinganallur",
    "tambram": "Tambaram", "thambaram": "Tambaram",
    "chrompet": "Chromepet", "chromepet": "Chromepet",
    "thiruvanmiyur": "Thiruvanmiyur", "tiruvanmiyur": "Thiruvanmiyur",
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
                f"Hi {{name}}, this is {agent} from {company}. "
                f"You were looking at properties in {tenant.city}, right? "
                f"Quick two minutes."
            )
        if lang == "hi-IN":
            return (
                f"Namaste {{name}} ji, main {agent}, {company} se. "
                f"Aap {tenant.city} mein property dekh rahe the na? "
                f"Bas do minute."
            )
        if lang == "ta-IN":
            return (
                f"Vanakkam {{name}} sir, naan {agent}, {company} la irundhu. "
                f"Neenga {tenant.city} la property paatheenga-la? "
                f"Rendu minute podhum."
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

        Deep behavior + locality→WhatsApp→visit scripts live in
        priya-real-estate.md. This overlay is the terse SURVIVAL kit
        that catches the LLM when it drifts mid-call. Includes the
        canonical WhatsApp-after-locality response in the active language
        so the LLM can copy it verbatim.
        """
        if lang == "en-IN":
            locality_script = (
                'WHEN LEAD NAMES A LOCALITY (e.g. "Adyar", "T. Nagar"), reply in this SHAPE '
                '(own words, fit the conversation):\n'
                '  ack locality -> "we have 2-3 fresh options in [locality], sending listings '
                'to this WhatsApp number" -> offer a CHOICE of two visit slots as a question.\n'
                'WHEN LEAD SAYS YES TO A SPECIFIC SLOT (only then), confirm in this shape:\n'
                '  "Done sir — [day] [time], [locality] site visit booked. Sending the '
                'confirmation to this WhatsApp number with our team\'s contact and exact '
                'address." Never announce a booking before their yes.\n'
            )
        elif lang == "ta-IN":
            locality_script = (
                'WHEN LEAD NAMES A LOCALITY (e.g. "Adyar", "T. Nagar"), reply in this SHAPE '
                '(own words, fit the conversation):\n'
                '  ack locality -> "[locality] la namba kitta 2-3 fresh options irukku, listings '
                'indha WhatsApp number ku anuppuren" -> offer a CHOICE of two visit slots as a question.\n'
                'WHEN LEAD SAYS YES TO A SPECIFIC SLOT (only then), confirm in this shape:\n'
                '  "Done sir, [day] [time], [locality] site visit confirm. Indha WhatsApp '
                'number-ku confirmation anuppuren — address-um namma team contact-um." '
                'Never announce a booking before their yes.\n'
            )
        else:  # hi-IN
            locality_script = (
                'WHEN LEAD NAMES A LOCALITY (e.g. "Adyar", "T. Nagar"), reply in this SHAPE '
                '(own words, fit the conversation):\n'
                '  ack locality -> "[locality] mein humare paas 2-3 fresh options hain, listings '
                'iss WhatsApp number pe bhej rahi hoon" -> offer a CHOICE of two visit slots as a question.\n'
                'WHEN LEAD SAYS YES TO A SPECIFIC SLOT (only then), confirm in this shape:\n'
                '  "Done sir, [day] [time], [locality] site visit confirm. Iss WhatsApp number '
                'pe confirmation bhej rahi hoon — address aur hamari team ka contact." '
                'Never announce a booking before their yes.\n'
            )
        return (
            "<broker_focus>\n"
            "GOAL: book a site visit + send WhatsApp confirmation. NOT selling. NOT quoting prices.\n"
            "\n"
            "ABSOLUTE RULES — VIOLATION = CALL FAIL:\n"
            "1. NEVER state a number, price, rate, area, or amount the lead did NOT say first.\n"
            "   Do NOT 'summarise back' an invented price ('so you want a 72.1 lakh flat'). NEVER.\n"
            "   If you don't know the budget, ASK once — don't guess, don't infer.\n"
            "   EXCEPTION — the lead's OWN numbers: when they name a budget ('60-70 lakh'),\n"
            "   MIRROR it back warmly and confirm options exist in that band:\n"
            "   'Achha, 60-70 ke range mein achhe options hain humare paas sir.' Then next question.\n"
            "2. NEVER invent specific inventory ('Building XYZ has a flat for you'). Talk in ranges only.\n"
            "3. NEVER promise legal / loan / RERA / OC verification on call — broker confirms.\n"
            "4. STAY in lead's language. If transcript has Devanagari → reply Hindi. Tamil script → "
            "   reply Tamil. ASCII English → reply English. Flip ONLY on explicit triggers "
            "   ('speak in english', 'hindi mein bolo', 'tamil-la pesunga').\n"
            "5. QUALIFY IN ORDER, one question per turn: intent (buy/rent) -> locality -> BHK -> "
            "   budget. Acknowledge the lead's answer by name before the next question. Then "
            "   PROPOSE a visit slot as a question (choice of two). Confirm the booking ONLY "
            "   after the lead says yes to a specific slot. Don't ask timeline / loan / school "
            "   unless lead raises them.\n"
            "6. Write the company + area names as plain normal words — the voice layer "
            "handles pronunciation. NEVER insert dashes or single spaces between letters "
            "('B-H-K', 'X Y Z') — the TTS literally says 'B dash H dash K'. 'BHK' stays 'BHK'.\n"
            "7. HARD LIMIT: maximum TWO sentences per reply. Total reply <=20 words. "
            "   Last sentence must be a question. Then STOP — wait for lead. NEVER fire 3-5 "
            "   sentences in a row, NEVER list options unsolicited.\n"
            "8. NEVER infer meaning from one-word lead replies ('Recorded' / 'Okay' / 'Yes' / 'Hmm'). "
            "   Just ask the next short question: 'Sorry sir, buy ya rent?'\n"
            "9. NEVER list localities for the lead ('we have T. Nagar, Adyar, Velachery...'). "
            "   Just ask: 'Which area in Chennai?' Let THEM name one. Then mirror it back.\n"
            "10. If lead names a locality you don't recognize, do NOT correct them. Just say "
            "    'Got it sir, [repeat what they said]. We have a few options there...' and continue "
            "    with the WhatsApp+visit close. Better to roll with it than confuse them.\n"
            "11. Plain punctuation only — periods and commas. NO ellipsis '...' (TTS reads as glitch). "
            "    NO em-dashes (TTS ignores them).\n"
            "\n"
            "SAY-IT-RIGHT — write each word in the spelling the voice reads correctly:\n"
            "- Keep 'lakh' and 'crore' as-is ('eighty lakh', 'one point two crore'). "
            "Write 'sqft' as 'square feet'. 'BHK' stays 'BHK', 'EMI' stays 'EMI', 'RERA' as 'Rera'.\n"
            "- Chennai areas, write plainly as spoken: 'Tee Nagar' (NOT 'T. Nagar' / 'T-Nagar'), "
            "Adyar, Mylapore, Velachery, Anna Nagar, Besant Nagar, Nungambakkam, Tambaram, "
            "Porur, Guindy, Saidapet, OMR, ECR.\n"
            "- One normal word per name. A dash or mid-word space is read aloud as 'dash' / a pause.\n"
            "\n"
            + locality_script +
            "</broker_focus>"
        )


BRAIN = _RealEstateBrain()
