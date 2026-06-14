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

import re
from dataclasses import dataclass

from voice_agent.conversation_state import (
    native_hindi_script_enabled,
    native_tamil_script_enabled,
)
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
        "Vepery",
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
    "bandar west": "Bandra West", "bandar east": "Bandra East",
    "bandara west": "Bandra West", "bandara east": "Bandra East",
    "vandre west": "Bandra West", "vandre east": "Bandra East",
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
    "kilpak": "Kilpauk", "kil pauk": "Kilpauk", "gilpauk": "Kilpauk",
    "kilpaak": "Kilpauk", "vepary": "Vepery", "veppery": "Vepery",
}


# Single lowercase→canonical lookup (gazetteer + hand-curated drift aliases).
_LOC_CANON_BY_LOWER: dict[str, str] = {}
for _names in LOCALITIES.values():
    for _c in _names:
        _LOC_CANON_BY_LOWER.setdefault(_c.lower(), _c)
for _alias, _canon in LOCALITY_ALIASES.items():
    _LOC_CANON_BY_LOWER.setdefault(_alias, _canon)

# Single-token lower forms eligible for the fuzzy fallback. Multiword names
# ("anna nagar") are matched only by exact alias/gazetteer — fuzzing a span
# invites ambiguity. min length 6 keeps short names ("omr", "powai", "khar")
# off the fuzzy path where a one-edit slip could collide with a real word.
_LOC_FUZZY_POOL: tuple[str, ...] = tuple(
    sorted(low for low in _LOC_CANON_BY_LOWER if " " not in low and "." not in low)
)
_LOC_FUZZY_MIN_LEN = 6


def _edit_distance_le1(a: str, b: str) -> bool:
    """True iff Levenshtein(a, b) <= 1. Cheap single-pass check (no matrix)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if a == b:
        return True
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:  # one substitution → tails must match
        return a[i + 1:] == b[i + 1:]
    if la < lb:  # one insertion into a
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i:]  # one deletion from a


def canonical_locality(raw: str) -> str | None:
    """Map a fuzzy / misspelled locality mention to its canonical name.

    Exact gazetteer/alias hit first; then a *tight, unambiguous* edit-
    distance-1 fallback for single tokens (>=6 chars) so new 8kHz STT
    drifts ("kilpak" → "Kilpauk") repair without enumerating every variant.
    Returns None when there's no confident match OR the fuzzy hit is
    ambiguous — caller keeps the raw string rather than mis-routing a lead.
    """
    lower = raw.strip().lower()
    if not lower:
        return None
    if lower in _LOC_CANON_BY_LOWER:
        return _LOC_CANON_BY_LOWER[lower]
    if " " not in lower and len(lower) >= _LOC_FUZZY_MIN_LEN:
        hits = {
            _LOC_CANON_BY_LOWER[c]
            for c in _LOC_FUZZY_POOL
            if _edit_distance_le1(lower, c)
        }
        if len(hits) == 1:
            return next(iter(hits))
    return None


_LOC_WORD_RE = re.compile(r"[A-Za-z][A-Za-z.]*")


def normalize_localities(text: str) -> str:
    """Repair *romanized* locality drift from the 8kHz STT before anything
    reads the transcript (slot extraction, the LLM message, history). The
    lead said "Kilpauk"; a noisy line drifts it ("kilpak") — left alone the
    LLM may echo a wrong neighbourhood back (call logs: Kilpauk → wrong
    area). Scans ASCII word spans (2-grams then 1-grams) and snaps known
    drifts + tight unambiguous typos to the gazetteer spelling.

    Limits, by design: only ROMAN-script tokens — native-script (Tamil/
    Devanagari) locality drift is NOT covered (that's the SPC tenant, not
    the broker vertical this serves). Non-locality words are untouched.
    """
    if not text:
        return text
    matches = list(_LOC_WORD_RE.finditer(text))
    if not matches:
        return text
    out: list[str] = []
    last = 0
    i = 0
    n = len(matches)
    while i < n:
        m = matches[i]
        replaced: str | None = None
        span_start, span_end, consumed = m.start(), m.end(), 1
        if i + 1 < n:  # try a 2-gram first (adjacent, whitespace-only gap)
            m2 = matches[i + 1]
            if text[m.end():m2.start()].strip() == "":
                cand = canonical_locality(f"{m.group(0)} {m2.group(0)}")
                if cand:
                    replaced, span_end, consumed = cand, m2.end(), 2
        if replaced is None:
            cand = canonical_locality(m.group(0))
            if cand:
                replaced = cand
        if replaced is not None:
            # Drop a redundant trailing direction word the canonical already
            # carries ("bandar west" → alias "Bandra West", then a stray
            # "west" would double it).
            nxt = i + consumed
            if nxt < n and text[span_end:matches[nxt].start()].strip() == "":
                if matches[nxt].group(0).lower() == replaced.rsplit(" ", 1)[-1].lower():
                    span_end, consumed = matches[nxt].end(), consumed + 1
            out.append(text[last:span_start])
            out.append(replaced)
            last = span_end
        i += consumed
    out.append(text[last:])
    return "".join(out)


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
                f"Can I take two quick minutes?"
            )
        if lang == "hi-IN":
            # Native Devanagari hits Bulbul's Hindi phonemes; romanized text
            # is read with English letter-phonetics (rated 5/10 by testers).
            # The agent/company names stay Roman — the pronunciation pack
            # owns those.
            if native_hindi_script_enabled():
                return (
                    f"नमस्ते {{name}} जी, मैं {agent}, {company} से बात कर रही हूँ. "
                    f"आप {tenant.city} में property देख रहे थे ना? "
                    f"दो मिनट बात कर सकते हैं?"
                )
            return (
                f"Namaste {{name}} ji, main {agent}, {company} se baat kar rahi hoon. "
                f"Aap {tenant.city} mein property dekh rahe the na? "
                f"Do minute baat kar sakte hain?"
            )
        if lang == "ta-IN":
            if native_tamil_script_enabled():
                return (
                    f"வணக்கம் {{name}} sir, நான் {agent}, {company}-ல இருந்து பேசுறேன். "
                    f"நீங்க {tenant.city}-ல property பாத்தீங்க-ல? "
                    f"ரெண்டு நிமிஷம் பேசலாமா sir?"
                )
            return (
                f"Vanakkam {{name}} sir, naan {agent}, {company} la irundhu pesuren. "
                f"Neenga {tenant.city} la property paatheenga-la? "
                f"Rendu nimisham pesalaamaa sir?"
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
        """Per-turn drift-catcher appended after the base prompt.

        Deliberately TINY: the full playbook lives in priya-real-estate.md
        (sent as the system prompt). This used to duplicate ~1K tokens of
        those rules every turn — at ~7.3K tokens/turn two turns in one
        minute blew Groq's 12K TPM free limit (call 866614ad). Keep only
        what the model demonstrably drops mid-call.
        """
        return (
            "<broker_focus>\n"
            "Drift check, every reply: max 2 short sentences, end with a "
            "question or next step; ack in 2-4 words, never restate the "
            "lead's words; never a number the lead didn't say first (mirror "
            "THEIR budget back warmly); rent lead gets monthly-rent budget "
            "question, never lakhs/crores; once intent+locality+BHK known, "
            "next turn = WhatsApp listings + choice of two visit slots; "
            "confirm a booking ONLY after their yes to a specific time. "
            "Plain words for names (BHK not B-H-K, Tee Nagar not T-Nagar); "
            "periods and commas only, no ellipsis or dashes.\n"
            "</broker_focus>"
        )


BRAIN = _RealEstateBrain()
