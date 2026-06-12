"""Tests for pain_library.py — pain hypothesis selection (real-estate vertical)."""
from __future__ import annotations

from voice_agent.language_state import Lang
from voice_agent.pain_library import (
    PAIN_HYPOTHESES,
    Category,
    categorize_product,
    pick_pain_hypothesis,
)


class TestCategorizeProduct:
    CASES = [
        ("2 BHK Adyar, buy", Category.BUY),
        ("3 bhk flat Velachery", Category.BUY),
        ("independent house Anna Nagar", Category.BUY),
        ("villa purchase OMR", Category.BUY),
        # Rent must win even when BHK/flat words are present.
        ("2 BHK for rent T. Nagar", Category.RENT),
        ("15k-30k for rent", Category.RENT),
        ("flat on lease Porur", Category.RENT),
        ("kiraye ka makaan", Category.RENT),
        ("investment plot ECR", Category.INVESTMENT),
        ("good rental yield apartment", Category.INVESTMENT),
        ("steel sheets", Category.GENERIC),
        (None, Category.GENERIC),
        ("", Category.GENERIC),
    ]

    def test_categories(self):
        for text, expected in self.CASES:
            assert categorize_product(text) == expected, text

    def test_rent_beats_buy_keywords(self):
        # "bhk" alone is BUY; with a rent signal the rent intent dominates.
        assert categorize_product("2 bhk") == Category.BUY
        assert categorize_product("2 bhk rental") == Category.RENT


class TestPickPainHypothesis:
    def test_buy_hindi(self):
        out = pick_pain_hypothesis(product_interest="2 BHK Adyar, buy", lang=Lang.HI)
        assert out in PAIN_HYPOTHESES[(Category.BUY, Lang.HI)]

    def test_rent_english(self):
        out = pick_pain_hypothesis(product_interest="flat for rent", lang=Lang.EN)
        assert out in PAIN_HYPOTHESES[(Category.RENT, Lang.EN)]

    def test_investment_tamil(self):
        out = pick_pain_hypothesis(product_interest="investment plot", lang=Lang.TA)
        assert out in PAIN_HYPOTHESES[(Category.INVESTMENT, Lang.TA)]

    def test_unknown_product_falls_back_to_generic(self):
        out = pick_pain_hypothesis(product_interest="rare element X", lang=Lang.HI)
        assert out in PAIN_HYPOTHESES[(Category.GENERIC, Lang.HI)]

    def test_deterministic_on_turn_idx(self):
        out1 = pick_pain_hypothesis(product_interest="2 bhk buy", lang=Lang.HI, turn_idx=0)
        out2 = pick_pain_hypothesis(product_interest="2 bhk buy", lang=Lang.HI, turn_idx=0)
        assert out1 == out2

        out3 = pick_pain_hypothesis(product_interest="2 bhk buy", lang=Lang.HI, turn_idx=1)
        assert out3 in PAIN_HYPOTHESES[(Category.BUY, Lang.HI)]

    def test_handles_none_product(self):
        out = pick_pain_hypothesis(product_interest=None, lang=Lang.EN)
        assert out in PAIN_HYPOTHESES[(Category.GENERIC, Lang.EN)]

    def test_all_categories_have_all_three_languages(self):
        """No silent gaps. Every category must have HI, EN, TA hypotheses."""
        for cat in [Category.BUY, Category.RENT, Category.INVESTMENT, Category.GENERIC]:
            for lang in [Lang.HI, Lang.EN, Lang.TA]:
                hypotheses = PAIN_HYPOTHESES.get((cat, lang))
                assert hypotheses, f"Missing hypotheses for ({cat}, {lang.value})"
                assert all(h.strip() for h in hypotheses), f"Empty string in ({cat}, {lang.value})"

    def test_hypotheses_end_with_probe(self):
        """Every hypothesis should end with a soft probe (question mark)
        so the lead has a natural place to respond."""
        for (cat, lang), hypotheses in PAIN_HYPOTHESES.items():
            for h in hypotheses:
                assert h.rstrip().endswith("?"), \
                    f"Hypothesis in ({cat}, {lang.value}) missing probe: {h!r}"

    def test_no_chemical_vocabulary_remains(self):
        """Call 43ea487c regression: chemical-SPC copy leaked into a live
        real-estate call ('Current supplier la enna problem irukku sir?')."""
        banned = ("supplier", "solvent", "acid", "caustic", "polymer",
                  "pesticide", "moq", "distributor", "quote")
        for (cat, lang), hypotheses in PAIN_HYPOTHESES.items():
            for h in hypotheses:
                low = h.lower()
                for word in banned:
                    assert word not in low, f"({cat}, {lang.value}): {h!r}"
