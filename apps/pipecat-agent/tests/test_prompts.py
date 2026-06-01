"""Tests for prompt assembly + intro-text parity with TS layer."""
from __future__ import annotations

from voice_agent.prompts import (
    build_intro_text,
    build_system_message,
    is_usable_first_name,
    load_priya_prompt,
)


class TestIsUsableFirstName:
    def test_accepts_normal_names(self):
        assert is_usable_first_name("Ravi") is True
        assert is_usable_first_name("Su") is True

    def test_rejects_placeholders(self):
        for bad in ("Unknown", "NA", "N/A", "Test", "", None, "R"):
            assert is_usable_first_name(bad) is False


class TestBuildIntroText:
    def test_english_with_name(self):
        out = build_intro_text(lang="en-IN", first_name="Ravi")
        assert "Hi Ravi" in out
        assert "Supreme Petrochemicals" in out

    def test_hindi_with_name(self):
        out = build_intro_text(lang="hi-IN", first_name="Sunil")
        assert "Sunil" in out
        assert "Supreme Petrochemicals" in out

    def test_tamil_with_name(self):
        out = build_intro_text(lang="ta-IN", first_name="Karthik")
        assert "Karthik" in out

    def test_unusable_name_falls_back(self):
        out = build_intro_text(lang="en-IN", first_name="Unknown")
        assert "Unknown" not in out
        assert "Priya" in out

    def test_empty_name_never_leaves_stray_space(self):
        assert "Hello ," not in build_intro_text(lang="en-IN", first_name="")
        # Hindi fallback shouldn't say "Namaste  ji" or similar
        hi = build_intro_text(lang="hi-IN", first_name=None)
        assert "  " not in hi


class TestSystemMessage:
    def test_injects_current_language_tag(self):
        msg = build_system_message(
            base_prompt="BASE",
            current_language="hi-IN",
            lead_first_name="Ravi",
            lead_company="Acme Pharma",
        )
        assert "hi-IN" in msg
        assert "Ravi" in msg
        assert "Acme Pharma" in msg
        assert "BASE" in msg

    def test_language_tag_present(self):
        msg = build_system_message(
            base_prompt="P",
            current_language="en-IN",
            lead_first_name=None,
            lead_company=None,
        )
        assert "en-IN" in msg

    def test_unusable_name_becomes_empty(self):
        msg = build_system_message(
            base_prompt="P",
            current_language="en-IN",
            lead_first_name="Unknown",
            lead_company=None,
        )
        assert "<lead></lead>" in msg


def test_priya_prompt_loads_from_shared_path():
    """Sanity check that the agent finds the prompt the TS layer ships."""
    p = load_priya_prompt()
    assert "Priya" in p
    assert "Supreme Petrochemicals" in p
    # Critical rules must be present.
    assert "language" in p.lower()
