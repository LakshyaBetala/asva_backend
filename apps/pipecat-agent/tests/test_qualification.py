"""Tests for qualification.py — per-turn slot extraction."""
from __future__ import annotations

import json
from typing import Awaitable

import pytest

from voice_agent.qualification import (
    BuyingFrequency,
    DecisionRole,
    QualificationSlots,
    extract_slots,
)


# SPC catalog used for scoring tests.
SPC = frozenset({"solvent", "acetone", "toluene", "polymer", "acid", "caustic"})


def _stub_llm(response: str):
    """Build an LlmCall that always returns the given response."""
    async def _call(prompt: str) -> str:
        return response
    return _call


def _failing_llm(exc: type[Exception] = RuntimeError):
    async def _call(prompt: str) -> str:
        raise exc("simulated llm failure")
    return _call


class TestScoring:
    def test_hot_when_all_signals_present(self):
        s = QualificationSlots(
            product_interest="acetone solvent",
            volume_monthly_kg=500,
            decision_role=DecisionRole.PROCUREMENT,
            timeline_days=14,
            buying_confidence=0.85,
        )
        assert s.score(SPC) == "hot"

    def test_warm_when_engaged_but_long_timeline(self):
        s = QualificationSlots(
            product_interest="industrial polymer",
            decision_role=DecisionRole.OWNER,
            timeline_days=45,
            buying_confidence=0.6,
        )
        assert s.score(SPC) == "warm"

    def test_warm_when_named_competitor_present(self):
        s = QualificationSlots(
            product_interest="caustic soda",
            current_supplier="ABC Chemicals",
            decision_role=DecisionRole.PROCUREMENT,
            buying_confidence=0.55,
        )
        assert s.score(SPC) == "warm"

    def test_cold_when_product_off_catalog(self):
        s = QualificationSlots(
            product_interest="industrial fertilizer",  # not in SPC catalog
            decision_role=DecisionRole.OWNER,
            timeline_days=14,
            buying_confidence=0.9,
        )
        assert s.score(SPC) == "cold"

    def test_cold_when_low_buying_confidence(self):
        s = QualificationSlots(
            product_interest="acetone",
            decision_role=DecisionRole.OWNER,
            timeline_days=14,
            buying_confidence=0.3,
        )
        assert s.score(SPC) == "cold"


@pytest.mark.asyncio
class TestExtractSlots:
    async def test_parses_clean_json(self):
        llm = _stub_llm(json.dumps({
            "product_interest": "acetone",
            "volume_monthly_kg": 500,
            "buying_frequency": "monthly",
            "current_supplier": None,
            "pain_point": "delivery delays",
            "decision_role": "procurement",
            "timeline_days": 21,
            "buying_confidence": 0.8,
            "slot_confidence": {
                "product_interest": 0.9,
                "volume_monthly_kg": 0.7,
                "buying_frequency": 0.8,
                "pain_point": 0.6,
                "decision_role": 0.85,
                "timeline_days": 0.8,
            },
        }))
        out = await extract_slots(transcript=[], prior_slots=QualificationSlots(), llm=llm)
        assert out.product_interest == "acetone"
        assert out.volume_monthly_kg == 500
        assert out.buying_frequency == BuyingFrequency.MONTHLY
        assert out.decision_role == DecisionRole.PROCUREMENT
        assert out.timeline_days == 21
        assert out.buying_confidence == pytest.approx(0.8)

    async def test_strips_markdown_fences(self):
        llm = _stub_llm("```json\n" + json.dumps({
            "product_interest": "toluene",
            "buying_confidence": 0.5,
            "slot_confidence": {"product_interest": 0.7},
        }) + "\n```")
        out = await extract_slots(transcript=[], prior_slots=QualificationSlots(), llm=llm)
        assert out.product_interest == "toluene"

    async def test_returns_prior_on_llm_failure(self):
        prior = QualificationSlots(product_interest="acetone", buying_confidence=0.6)
        out = await extract_slots(transcript=[], prior_slots=prior, llm=_failing_llm())
        # Identity preserved — corrupted state never leaks.
        assert out.product_interest == "acetone"
        assert out.buying_confidence == 0.6

    async def test_returns_prior_on_garbage_response(self):
        prior = QualificationSlots(product_interest="acetone", buying_confidence=0.6)
        llm = _stub_llm("definitely not json at all just words")
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.product_interest == "acetone"

    async def test_does_not_downgrade_higher_confidence_prior(self):
        """If we already know volume=500 at confidence 0.9, a new turn at
        confidence 0.3 must not overwrite it with garbage."""
        prior = QualificationSlots(
            volume_monthly_kg=500,
            slot_confidence={"volume_monthly_kg": 0.9},
        )
        llm = _stub_llm(json.dumps({
            "volume_monthly_kg": 50,  # the LLM guessed lower
            "buying_confidence": 0.4,
            "slot_confidence": {"volume_monthly_kg": 0.3},
        }))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.volume_monthly_kg == 500  # unchanged

    async def test_buying_confidence_always_takes_latest_value(self):
        """Buying confidence reflects the CURRENT moment, not cumulative."""
        prior = QualificationSlots(buying_confidence=0.8)
        llm = _stub_llm(json.dumps({
            "buying_confidence": 0.2,  # lead just said "we'll think about it"
            "slot_confidence": {},
        }))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.buying_confidence == pytest.approx(0.2)

    async def test_clamps_buying_confidence_to_unit_interval(self):
        prior = QualificationSlots()
        llm = _stub_llm(json.dumps({"buying_confidence": 1.5, "slot_confidence": {}}))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.buying_confidence == 1.0

        llm = _stub_llm(json.dumps({"buying_confidence": -0.3, "slot_confidence": {}}))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.buying_confidence == 0.0

    async def test_ignores_invalid_enum_value(self):
        prior = QualificationSlots()
        llm = _stub_llm(json.dumps({
            "decision_role": "ceo",  # not a valid enum value
            "buying_confidence": 0.5,
            "slot_confidence": {},
        }))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.decision_role == DecisionRole.UNKNOWN  # unchanged

    async def test_to_db_row_shape(self):
        s = QualificationSlots(
            product_interest="acetone",
            volume_monthly_kg=500,
            buying_frequency=BuyingFrequency.MONTHLY,
            decision_role=DecisionRole.PROCUREMENT,
            buying_confidence=0.8,
            slot_confidence={"product_interest": 0.9},
        )
        row = s.to_db_row(call_id="c1", tenant_id="t1", lead_id="L1", turn_idx=7)
        assert row["call_id"] == "c1"
        assert row["tenant_id"] == "t1"
        assert row["lead_id"] == "L1"
        assert row["product_interest"] == "acetone"
        assert row["volume_monthly_kg"] == 500
        assert row["buying_frequency"] == "monthly"
        assert row["decision_role"] == "procurement"
        assert row["buying_confidence"] == 0.80
        assert row["slot_confidence"] == {"product_interest": 0.9}
        assert row["last_turn_idx"] == 7

    async def test_merge_preserves_unspecified_slots(self):
        """A turn that only updates timeline shouldn't clear product_interest."""
        prior = QualificationSlots(
            product_interest="acetone",
            slot_confidence={"product_interest": 0.85},
        )
        llm = _stub_llm(json.dumps({
            "timeline_days": 30,
            "buying_confidence": 0.7,
            "slot_confidence": {"timeline_days": 0.9},
        }))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.product_interest == "acetone"
        assert out.timeline_days == 30
        assert out.buying_confidence == 0.7

    async def test_merge_updates_slot_confidence_map(self):
        prior = QualificationSlots()
        llm = _stub_llm(json.dumps({
            "product_interest": "polymer",
            "buying_confidence": 0.5,
            "slot_confidence": {"product_interest": 0.6},
        }))
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.slot_confidence["product_interest"] == 0.6

    async def test_handles_empty_dict_response(self):
        """An empty {} should leave prior intact."""
        prior = QualificationSlots(product_interest="acetone", buying_confidence=0.6)
        llm = _stub_llm("{}")
        out = await extract_slots(transcript=[], prior_slots=prior, llm=llm)
        assert out.product_interest == "acetone"
        # buying_confidence not present → unchanged
        assert out.buying_confidence == 0.6
