"""Tests for pain_library.py — pain hypothesis selection."""
from __future__ import annotations

import pytest

from voice_agent.language_state import Lang
from voice_agent.pain_library import (
    PAIN_HYPOTHESES,
    Category,
    categorize_product,
    pick_pain_hypothesis,
)


class TestCategorize:
    @pytest.mark.parametrize("text,expected", [
        ("acetone bulk", Category.SOLVENTS),
        ("Industrial grade toluene", Category.SOLVENTS),
        ("LDPE polymer", Category.POLYMERS),
        ("PVC granules", Category.POLYMERS),
        ("sulfuric acid 98%", Category.ACIDS),
        ("hydrochloric acid", Category.ACIDS),
        ("caustic soda flakes", Category.CAUSTICS),
        ("NaOH", Category.CAUSTICS),
        ("pesticide formulation", Category.AGROCHEMICALS),
        ("organic fertilizer", Category.AGROCHEMICALS),
        ("steel sheets", Category.GENERIC),
        (None, Category.GENERIC),
        ("", Category.GENERIC),
    ])
    def test_categorize(self, text, expected):
        assert categorize_product(text) == expected


class TestPickHypothesis:
    def test_returns_solvent_hindi_for_acetone(self):
        out = pick_pain_hypothesis(product_interest="acetone", lang=Lang.HI)
        assert out  # non-empty
        assert out in PAIN_HYPOTHESES[(Category.SOLVENTS, Lang.HI)]

    def test_returns_polymer_english(self):
        out = pick_pain_hypothesis(product_interest="LDPE polymer", lang=Lang.EN)
        assert out in PAIN_HYPOTHESES[(Category.POLYMERS, Lang.EN)]

    def test_returns_tamil_for_acid(self):
        out = pick_pain_hypothesis(product_interest="sulfuric acid", lang=Lang.TA)
        assert out in PAIN_HYPOTHESES[(Category.ACIDS, Lang.TA)]

    def test_generic_fallback_for_unknown_product(self):
        out = pick_pain_hypothesis(product_interest="rare element X", lang=Lang.HI)
        assert out in PAIN_HYPOTHESES[(Category.GENERIC, Lang.HI)]

    def test_deterministic_on_turn_idx(self):
        out1 = pick_pain_hypothesis(product_interest="acetone", lang=Lang.HI, turn_idx=0)
        out2 = pick_pain_hypothesis(product_interest="acetone", lang=Lang.HI, turn_idx=0)
        assert out1 == out2
        # Different turn_idx may pick different hypothesis.
        out3 = pick_pain_hypothesis(product_interest="acetone", lang=Lang.HI, turn_idx=1)
        # Either way, both must be in the right bucket.
        assert out3 in PAIN_HYPOTHESES[(Category.SOLVENTS, Lang.HI)]

    def test_handles_none_product(self):
        out = pick_pain_hypothesis(product_interest=None, lang=Lang.EN)
        assert out in PAIN_HYPOTHESES[(Category.GENERIC, Lang.EN)]

    def test_all_categories_have_all_three_languages(self):
        """No silent gaps. Every category must have HI, EN, TA hypotheses."""
        for cat in [Category.SOLVENTS, Category.POLYMERS, Category.ACIDS,
                    Category.CAUSTICS, Category.AGROCHEMICALS, Category.GENERIC]:
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
