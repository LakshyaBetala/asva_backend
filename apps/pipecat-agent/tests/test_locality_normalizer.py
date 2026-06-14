"""Romanized locality drift repair for noisy 8kHz STT (broker vertical).

The lead names a real neighbourhood; the phone line drifts the spelling and
the LLM otherwise echoes a wrong area back (call logs: Kilpauk → wrong
locality). canonical_locality + normalize_localities snap known drifts and
tight unambiguous typos to the gazetteer spelling, and — critically — leave
everything else untouched.
"""
from __future__ import annotations

from voice_agent.industry.real_estate import (
    canonical_locality,
    normalize_localities,
)


class TestCanonicalLocality:
    def test_exact_gazetteer_and_alias(self):
        assert canonical_locality("Kilpauk") == "Kilpauk"
        assert canonical_locality("koramangla") == "Koramangala"
        assert canonical_locality("velacheri") == "Velachery"
        assert canonical_locality("hi tech city") == "Hitech City"

    def test_fuzzy_one_edit_repairs_new_drift(self):
        # Not in the alias map — repaired by the unambiguous edit-1 fallback.
        assert canonical_locality("kilpak") == "Kilpauk"   # deletion
        assert canonical_locality("gilpauk") == "Kilpauk"  # substitution
        assert canonical_locality("mathunga") == "Matunga"

    def test_fuzzy_rejects_short_and_unknown(self):
        # < 6 chars never fuzzy-matched (collision risk with real words).
        assert canonical_locality("powa") is None
        assert canonical_locality("khar2") is None
        # Genuinely unknown locality → keep raw (return None).
        assert canonical_locality("zxqwerty") is None

    def test_does_not_invent_for_common_words(self):
        for w in ("ignore", "number", "budget", "rental", "please", "monthly"):
            assert canonical_locality(w) is None


class TestNormalizeLocalities:
    def test_repairs_kilpauk_in_sentence(self):
        assert normalize_localities("I want a 2 BHK in kilpak for rent") == (
            "I want a 2 BHK in Kilpauk for rent"
        )

    def test_multiword_and_direction(self):
        assert normalize_localities("flat in bandar west") == "flat in Bandra West"
        assert normalize_localities("flat in bandar east") == "flat in Bandra East"
        assert normalize_localities("show me anna nagar options") == (
            "show me Anna Nagar options"
        )
        assert normalize_localities("hsr layout 3 bhk") == "HSR Layout 3 bhk"

    def test_multiple_localities_one_turn(self):
        assert normalize_localities("kilpak and koramangla both") == (
            "Kilpauk and Koramangala both"
        )

    def test_no_directional_duplication(self):
        # Canonical already carries the direction → don't repeat it.
        assert "West West" not in normalize_localities("bandar west")
        assert normalize_localities("bandra west please") == "Bandra West please"

    def test_leaves_non_localities_untouched(self):
        for s in (
            "I want to ignore the broker and just rent",
            "please send me the number and budget",
            "hello can you hear me",
            "thirty thousand rupees monthly",
        ):
            assert normalize_localities(s) == s

    def test_native_script_passes_through(self):
        # Tamil/Devanagari locality drift is out of scope (broker vertical is
        # romanized); native-script text must be returned unchanged.
        s = "கில்பாக் la oru veedu venum"
        assert normalize_localities(s) == s

    def test_empty_and_no_words(self):
        assert normalize_localities("") == ""
        assert normalize_localities("123 456") == "123 456"
