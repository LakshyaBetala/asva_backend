"""Pre-written pain-point hypotheses Priya can float in DISCOVER phase.

Why pre-written
---------------
Letting the LLM invent pain points on the fly produces generic ones
("finding a house is hard, right?"). Real property leads have *specific*
pains: listings that look nothing like the photos, owner preferences
killing rental options, possession delays on under-construction. A
hypothesis that names a real pain anchors the lead's trust ("this person
knows the market") and pulls slot data out faster than open questions.

The library is curated, not exhaustive. Each entry is 1-2 short
sentences, language-localized, and ends in a soft probe ("aapke saath
aisa hua hai?"). The pipeline picks ONE based on (category, language)
and passes it in the system prompt for DISCOVER turns. None of the
entries name a price or number — Priya never invents figures.

The chemical-SPC version of this library moved with the SPC persona
removal (2026-06-11); this file serves the real-estate vertical only.
"""
from __future__ import annotations

from .language_state import Lang


# Lead-intent categories used as keys. Map raw product_interest strings
# (e.g. "2 BHK Adyar, buy" / "15k-30k for rent") to these via
# _CATEGORY_KEYWORDS below.
class Category:
    RENT = "rent"
    INVESTMENT = "investment"
    BUY = "buy"
    GENERIC = "generic"  # fallback when intent isn't extracted yet


# Order matters: "good rental yield" must read as INVESTMENT, not RENT,
# and "2 BHK for rent" must read as RENT, not BUY — so the check order is
# INVESTMENT, then RENT, then BUY.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    Category.INVESTMENT: ["invest", "yield", "resale"],
    Category.RENT: ["rent", "rental", "lease", "kiraya", "kiraye", "vadagai"],
    Category.BUY: [
        "buy", "bhk", "flat", "apartment", "villa", "plot",
        "house", "ghar", "veedu", "purchase",
    ],
}


# Hypotheses: (category, lang) -> list of full sentences.
# Each ends with a soft probe so the lead can confirm or deny without losing face.
PAIN_HYPOTHESES: dict[tuple[str, Lang], list[str]] = {
    # BUY
    (Category.BUY, Lang.HI): [
        "Achha, zyaadatar log bolte hain photos mein flat ek jaisa dikhta hai aur visit pe alag nikalta hai. Aapke saath aisa hua hai?",
        "Ji, budget ke andar sahi area mein ready options milna sabse bada challenge hota hai. Aapko ab tak kaise options mile hain?",
        "Under-construction mein possession date ka bharosa nahi hota — delay common hai. Aap ready-to-move dekh rahe hain ya under-construction?",
    ],
    (Category.BUY, Lang.EN): [
        "Most buyers tell us the flat looks great in photos but feels different on the actual visit. Has that been your experience?",
        "Finding the right area within budget is usually the hardest part. How have the options been so far?",
        "With under-construction, possession delays are the big worry. Are you looking at ready-to-move or under-construction?",
    ],
    (Category.BUY, Lang.TA): [
        "Photos la nalla irukkum, aana site visit la vera maathiri irukkum-nu romba per solraanga. Ungalukku andha experience irukka?",
        "Budget-kulla nalla area-la option kedaikiradhu dhaan kashtam-nu solraanga. Ungalukku ippo varaikkum options eppadi irundhuchu?",
        "Under-construction na possession delay dhaan periya worry. Neenga ready-to-move paakareengala, illa under-construction-aa?",
    ],

    # RENT
    (Category.RENT, Lang.HI): [
        "Rent mein aksar owner ki preferences se options atak jaati hain — family-only, veg-only. Aapko aisi dikkat aayi hai?",
        "Ji, deposit aur agreement ki terms pe hi zyaadatar deals atakti hain. Aapke liye sabse important kya hai?",
    ],
    (Category.RENT, Lang.EN): [
        "With rentals, owner preferences like family-only or veg-only knock out half the options. Have you run into that?",
        "Deposit and agreement terms are where most rental deals get stuck. What matters most for you?",
    ],
    (Category.RENT, Lang.TA): [
        "Rent-la owner preference problem perusu — family-only, veg-only nu options kammi aagidum. Ungalukku andha problem vandhirukka?",
        "Advance um agreement terms um dhaan rent deals la main issue. Ungalukku edhu important?",
    ],

    # INVESTMENT
    (Category.INVESTMENT, Lang.HI): [
        "Investment ke liye sabse bada sawaal hota hai — rental yield ya appreciation. Aapka focus kya hai?",
        "Achha, investment property mein resale aur tenant milne ki tension rehti hai. Aap kis area mein soch rahe hain?",
    ],
    (Category.INVESTMENT, Lang.EN): [
        "For investment buyers the big question is rental yield versus appreciation. Which matters more to you?",
        "With investment property, resale and finding tenants are the usual worries. Which area are you considering?",
    ],
    (Category.INVESTMENT, Lang.TA): [
        "Investment-na rental yield-aa, appreciation-aa nu dhaan main question. Ungaloda focus edhu?",
        "Investment property la resale um tenant kedaikiradhum dhaan tension. Neenga endha area la yosikireenga?",
    ],

    # GENERIC fallback when we don't know buy/rent yet (early DISCOVER).
    (Category.GENERIC, Lang.HI): [
        "Achha, zyaadatar log bolte hain ki sahi area mein budget fit nahi hota. Aap kaunsa area dekh rahe hain?",
        "Ji, listings photos mein achhi lagti hain par visit pe alag nikalti hain — yeh sabse common complaint hai. Aapka experience kaisa raha?",
    ],
    (Category.GENERIC, Lang.EN): [
        "Most people tell us the hardest part is finding the right area within budget. Which areas are you looking at?",
        "The most common complaint we hear is listings looking nothing like the photos on visit. What has your experience been?",
    ],
    (Category.GENERIC, Lang.TA): [
        "Romba per sollura problem — nalla area-la budget fit aagala nu. Neenga endha area paakareenga?",
        "Photos la nalla irukkum, aana neryla paatha vera maathiri irukkum — idhu dhaan common complaint. Ungaloda experience eppadi?",
    ],
}


def categorize_product(product_text: str | None) -> str:
    """Map a free-form product_interest string to one of our categories.

    Returns Category.GENERIC if nothing matches. Lowercase + substring match.
    """
    if not product_text:
        return Category.GENERIC
    lower = product_text.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return cat
    return Category.GENERIC


def pick_pain_hypothesis(
    *,
    product_interest: str | None,
    lang: Lang,
    turn_idx: int = 0,
) -> str:
    """Choose one pain hypothesis to float in DISCOVER phase.

    Deterministic on (category, lang, turn_idx) so the same call always
    picks the same one — useful for testing and for not flip-flopping.
    Falls back to generic + lang, then to English generic, then to a
    safe empty string (LLM will improvise).
    """
    cat = categorize_product(product_interest)
    candidates = PAIN_HYPOTHESES.get((cat, lang))
    if not candidates:
        candidates = PAIN_HYPOTHESES.get((Category.GENERIC, lang))
    if not candidates:
        candidates = PAIN_HYPOTHESES.get((Category.GENERIC, Lang.EN))
    if not candidates:
        return ""
    return candidates[turn_idx % len(candidates)]
