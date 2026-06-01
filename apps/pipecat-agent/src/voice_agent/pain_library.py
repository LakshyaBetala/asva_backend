"""Pre-written pain-point hypotheses Priya can float in DISCOVER phase.

Why pre-written
---------------
Letting the LLM invent pain points on the fly produces generic ones
("delivery is hard, right?"). Real distributors and procurement leads
have *specific* pains: 45-60 day payment cycles, monsoon supply gaps,
batch quality variance. A hypothesis that names a real pain anchors
the lead's trust ("this person knows our industry") and pulls slot
data out faster than open questions.

The library is curated, not exhaustive. Each entry is one sentence,
language-localized, and ends in a soft probe ("aapke saath kuch aisa
hai?"). The pipeline picks ONE based on (product_category, language)
and passes it in the system prompt for DISCOVER turn.
"""
from __future__ import annotations

from .language_state import Lang


# Product categories used as keys. Map raw product_interest strings to
# these via _CATEGORY_KEYWORDS below.
class Category:
    SOLVENTS = "solvents"
    POLYMERS = "polymers"
    ACIDS = "acids"
    CAUSTICS = "caustics"
    AGROCHEMICALS = "agrochemicals"
    GENERIC = "generic"  # fallback


_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    Category.SOLVENTS: ["solvent", "acetone", "toluene", "ethanol", "methanol", "ipa", "mek"],
    Category.POLYMERS: ["polymer", "polyethylene", "polypropylene", "pvc", "resin", "plastic"],
    Category.ACIDS: ["acid", "sulfuric", "hcl", "hydrochloric", "nitric", "phosphoric"],
    Category.CAUSTICS: ["caustic", "naoh", "lye", "sodium hydroxide", "potassium hydroxide", "koh"],
    Category.AGROCHEMICALS: ["pesticide", "fungicide", "herbicide", "fertilizer", "agro"],
}


# Hypotheses: (category, lang) -> list of full sentences.
# Each ends with a soft probe so the lead can confirm or deny without losing face.
PAIN_HYPOTHESES: dict[tuple[str, Lang], list[str]] = {
    # SOLVENTS
    (Category.SOLVENTS, Lang.HI): [
        "Acha, hum jo doosre distributors ke saath kaam karte hain, unme se kai bolte hain solvent ka quality monsoon mein inconsistent ho jaata hai. Aapke saath kuch aisa hai?",
        "Ji, aksar bada problem yeh hota hai ki bulk solvent ka payment cycle 45-60 din ka hota hai. Aapke supplier kya credit terms dete hain?",
        "Haan, solvents mein purity ka grade-mismatch bahut common hai — batch ke saath certificate aata hai par actual purity alag. Aapke saath dikkat aati hai?",
    ],
    (Category.SOLVENTS, Lang.EN): [
        "I see — many distributors we work with mention that solvent quality becomes inconsistent during monsoon. Does that happen with your current supplier?",
        "One thing we often hear is the 45-60 day payment terms on bulk solvents are tight for cashflow. What's your experience?",
        "Purity grade mismatches — certificate says one thing, actual batch is different — is something I hear a lot. Is that an issue for you?",
    ],
    (Category.SOLVENTS, Lang.TA): [
        "Naanga vera distributors-kitta paatha, solvent quality monsoon time-la inconsistent-aa irukku-nu solraanga. Ungalukku kooda andha problem irukka?",
        "Solvent supplier-kitta payment cycle 45-60 days irukku-nu kooduthal-aa kekkaren — ungalukku cashflow-la dikkat aagudha?",
        "Purity grade-la mismatch — certificate-la oru maathiri, batch-la innoru maathiri — andha problem ungalukku irukkudha?",
    ],

    # POLYMERS
    (Category.POLYMERS, Lang.HI): [
        "Polymer industry mein sabse common dard delivery delay hai — peak season mein 2-3 hafte late ho jaata hai. Aapke saath kuch aisa hota hai?",
        "Ji, polymer ka MOQ aksar zyaada hota hai jab aap chhoti quantity chahte ho. Aapko bhi yeh issue aata hai?",
        "Acha, polymer ke grade-mismatch ka problem common hai — film grade ki jagah injection grade aa jaata hai. Aapko aisa kuch hua hai?",
    ],
    (Category.POLYMERS, Lang.EN): [
        "Polymer delivery delays during peak season — 2-3 weeks late — is the most common pain we hear. Does that hit you too?",
        "Many buyers struggle with high MOQs when they need a smaller batch. Is that a friction point for you?",
        "Grade mismatch — film grade arriving when you ordered injection grade — is surprisingly common. Have you faced it?",
    ],
    (Category.POLYMERS, Lang.TA): [
        "Polymer delivery delay peak season-la 2-3 weeks late aagiradhu pol-aa irukku — ungalukku andha problem irukka?",
        "Polymer-kku MOQ atikam-aa irukku, chinna batch venum-naa difficult-aa irukku — ungalukku andha issue irukka?",
        "Grade mismatch — order panniyathu film grade, vandhirukku injection grade — andha problem ungalukku vandhuruka?",
    ],

    # ACIDS
    (Category.ACIDS, Lang.HI): [
        "Acid supply mein safety documentation ka jhanjhat bahut hota hai — har shipment ke saath fresh paperwork. Aapke saath kya situation hai?",
        "Ji, acid concentration ka stability problem common hai — invoice mein 98% likha, actual 96%. Aapko bhi yeh dikkat aati hai?",
        "Haan, acid ke transport mein leakage ka risk hota hai, insurance claim mein time lagta hai. Aapke pichle saal mein kuch hua tha?",
    ],
    (Category.ACIDS, Lang.EN): [
        "Acid procurement always comes with safety documentation hassles — fresh paperwork every shipment. What's your process?",
        "Concentration stability is the quiet pain — invoice says 98%, real batch is 96%. Have you seen that?",
        "Transport leakage incidents — and the insurance claim cycle that follows — is one we hear a lot. Has that hit you?",
    ],
    (Category.ACIDS, Lang.TA): [
        "Acid supply-la safety documentation problem konjam atikam-aa irukku — ovvoru shipment-kkum fresh paperwork. Ungalukku eppadi?",
        "Acid concentration stability problem-aa irukku — invoice-la 98% nu sollirukku, actual-la 96%. Andha problem ungalukku vandhirukka?",
        "Acid transport-la leakage incident, insurance claim-kku romba time aagudhu — andha experience ungalukku irukka?",
    ],

    # CAUSTICS
    (Category.CAUSTICS, Lang.HI): [
        "Caustic ka MOQ aksar truck-load mein hota hai, jo chhote players ke liye difficult hai. Aapko kya quantity chahiye hota hai?",
        "Acha, caustic flakes vs liquid ka conversion mein consistency ka issue aata hai. Aapko kaunsi form chahiye?",
        "Ji, caustic ke supply mein seasonal fluctuation hoti hai — Diwali ke baad shortage. Aapne face kiya hai?",
    ],
    (Category.CAUSTICS, Lang.EN): [
        "Caustic MOQs are usually a truckload — tough for smaller operations. What quantity fits your operation?",
        "Caustic flakes vs liquid: consistency in conversion is a quiet problem. Which form do you prefer?",
        "Post-Diwali caustic shortages hit a lot of buyers. Has that hurt your operations?",
    ],
    (Category.CAUSTICS, Lang.TA): [
        "Caustic-kku MOQ truckload-aa irukku, chinna operation-kku kashtam — ungalukku enna quantity venum?",
        "Caustic flakes vs liquid conversion-la consistency problem — ungalukku endha form preferable?",
        "Diwali-kku aprum caustic shortage romba peruku-kku problem-aa irukku — ungalukku andha experience irukka?",
    ],

    # AGROCHEMICALS
    (Category.AGROCHEMICALS, Lang.HI): [
        "Agro mein season-end stock clearance ka pressure bahut hota hai. Aapke saath kya planning hoti hai?",
        "Ji, formulation grade consistency ka issue common hai — har batch mein efficacy alag. Aapko bhi face hua hai?",
        "Acha, agro license aur paperwork ka burden bahut hota hai naye supplier ke saath. Aapke supplier change karne mein dikkat aati hai?",
    ],
    (Category.AGROCHEMICALS, Lang.EN): [
        "Season-end stock clearance pressure in agro is brutal. How do you plan around it?",
        "Formulation grade efficacy varying batch to batch — has that been your experience?",
        "License and paperwork burden when switching agro suppliers — does that slow you down?",
    ],
    (Category.AGROCHEMICALS, Lang.TA): [
        "Agro-la season-end stock clearance pressure romba irukku — ungalukku planning eppadi?",
        "Formulation grade efficacy batch-kku batch difference irukku — andha problem ungalukku irukka?",
        "Agro license, paperwork burden supplier-a maathara veaikku problem aagudha?",
    ],

    # GENERIC fallback when we can't categorize the product yet.
    (Category.GENERIC, Lang.HI): [
        "Acha, hum jo distributors ke saath kaam karte hain, unme se kai payment terms tight hone ka bolte hain. Aapke saath kuch aisa hai?",
        "Ji, delivery timelines aksar challenge hota hai. Aapke current supplier kaisa perform karte hain?",
    ],
    (Category.GENERIC, Lang.EN): [
        "Many distributors we work with mention payment terms get tight. Does that match your experience?",
        "Delivery timelines are often a challenge — how does your current supplier handle them?",
    ],
    (Category.GENERIC, Lang.TA): [
        "Naanga vera distributors-kitta paatha, payment terms tight-aa irukku-nu solraanga. Ungalukku andha problem irukka?",
        "Delivery timeline aksar challenge-aa irukku — ungaloda current supplier eppadi handle pannaranga?",
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
