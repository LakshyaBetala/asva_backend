"""Tests for the end-of-call book+WhatsApp hook."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from voice_agent.google_calendar import BookingResult
from voice_agent.post_call_hook import (
    PostCallHookResult,
    default_demo_slot,
    humanize_slot,
    run_post_call_hook,
)
from voice_agent.tenant_config import TenantConfig
from voice_agent.whatsapp import WhatsAppSendResult

IST = ZoneInfo("Asia/Kolkata")


def _tenant(
    *,
    calendar=True,
    whatsapp=True,
) -> TenantConfig:
    return TenantConfig(
        tenant_id="t1",
        company_name="Almmatix",
        agent_name="Priya",
        city="Bangalore",
        default_lang="hi-IN",
        voice_id_en="emily",
        voice_id_hi="anushka",
        voice_id_ta="anushka",
        industry_key="voice_agent_sales",
        google_calendar_id="primary" if calendar else "",
        google_refresh_token="r-token" if calendar else "",
        whatsapp_phone_id="phone-id" if whatsapp else "",
        whatsapp_business_id="biz-id" if whatsapp else "",
        whatsapp_access_token="wa-token" if whatsapp else "",
    )


# -- default_demo_slot ------------------------------------------------------

def test_default_demo_slot_is_tomorrow_11_ist():
    now = datetime.datetime(2026, 6, 5, 14, 30, tzinfo=IST)
    slot = default_demo_slot(now)
    parsed = datetime.datetime.fromisoformat(slot)
    assert parsed.date() == datetime.date(2026, 6, 6)
    assert parsed.hour == 11 and parsed.minute == 0
    assert parsed.tzinfo is not None


def test_humanize_slot_renders_human_readable():
    out = humanize_slot("2026-06-06T11:00:00+05:30")
    # exact format: "Sat 06 Jun, 11:00 AM IST" (single digits not zero-padded)
    assert "Jun" in out and "11:00 AM IST" in out


def test_humanize_slot_returns_input_on_bad_iso():
    assert humanize_slot("not-an-iso") == "not-an-iso"


# -- classification gating --------------------------------------------------

@pytest.mark.asyncio
async def test_skips_cold_classification():
    result = await run_post_call_hook(
        tenant=_tenant(),
        classification="cold",
        lead_first_name="Naman",
        lead_phone="+919876543210",
    )
    assert result.booked is False
    assert result.whatsapp_sent is False
    assert result.reason == "skipped:cold"


@pytest.mark.asyncio
async def test_skips_dead_classification():
    result = await run_post_call_hook(
        tenant=_tenant(),
        classification="dead",
        lead_first_name="X",
        lead_phone="+919876543210",
    )
    assert result.reason == "skipped:dead"


@pytest.mark.asyncio
async def test_skips_when_calendar_not_configured():
    result = await run_post_call_hook(
        tenant=_tenant(calendar=False),
        classification="hot",
        lead_first_name="Naman",
        lead_phone="+919876543210",
    )
    assert result.booked is False
    assert result.reason == "no_calendar"


# -- happy path -------------------------------------------------------------

@pytest.mark.asyncio
async def test_hot_lead_books_and_sends_whatsapp():
    booking = BookingResult(
        event_id="evt-1",
        html_link="https://cal/x",
        meet_link="https://meet.google.com/abc-defg-hij",
    )
    wa_result = WhatsAppSendResult(message_id="wamid.123")

    with patch(
        "voice_agent.post_call_hook.book_demo_meeting",
        new=AsyncMock(return_value=booking),
    ) as mock_book, patch(
        "voice_agent.post_call_hook.send_demo_confirm",
        new=AsyncMock(return_value=wa_result),
    ) as mock_wa:
        result = await run_post_call_hook(
            tenant=_tenant(),
            classification="hot",
            lead_first_name="Naman",
            lead_phone="+919876543210",
            primary_pain="cold-call fatigue",
            broker_focus="Bandra resale",
        )

    assert result.booked is True
    assert result.whatsapp_sent is True
    assert result.meet_link == "https://meet.google.com/abc-defg-hij"
    assert result.event_id == "evt-1"
    assert result.reason == "booked"

    mock_book.assert_awaited_once()
    book_kwargs = mock_book.await_args.kwargs
    assert book_kwargs["broker_name"] == "Naman"
    assert book_kwargs["broker_phone"] == "+919876543210"
    assert book_kwargs["primary_pain"] == "cold-call fatigue"

    mock_wa.assert_awaited_once()
    wa_call_req = mock_wa.await_args.args[0]
    assert wa_call_req.meet_link == "https://meet.google.com/abc-defg-hij"
    assert wa_call_req.broker_name == "Naman"
    assert wa_call_req.to_phone_e164 == "+919876543210"


@pytest.mark.asyncio
async def test_warm_lead_books_but_skips_whatsapp_when_not_configured():
    booking = BookingResult(
        event_id="evt-2", html_link="https://cal/y",
        meet_link="https://meet.google.com/zzz",
    )
    with patch(
        "voice_agent.post_call_hook.book_demo_meeting",
        new=AsyncMock(return_value=booking),
    ), patch(
        "voice_agent.post_call_hook.send_demo_confirm",
        new=AsyncMock(),
    ) as mock_wa:
        result = await run_post_call_hook(
            tenant=_tenant(whatsapp=False),
            classification="warm",
            lead_first_name="Asha",
            lead_phone="+919876543210",
        )
    assert result.booked is True
    assert result.whatsapp_sent is False
    mock_wa.assert_not_awaited()


@pytest.mark.asyncio
async def test_booking_failure_reports_clean_reason():
    with patch(
        "voice_agent.post_call_hook.book_demo_meeting",
        new=AsyncMock(return_value=None),
    ), patch(
        "voice_agent.post_call_hook.send_demo_confirm",
        new=AsyncMock(),
    ) as mock_wa:
        result = await run_post_call_hook(
            tenant=_tenant(),
            classification="hot",
            lead_first_name="X",
            lead_phone="+919876543210",
        )
    assert result.booked is False
    assert result.reason == "booking_failed"
    mock_wa.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_name_when_lead_first_name_missing():
    booking = BookingResult(event_id="e", html_link="h", meet_link=None)
    with patch(
        "voice_agent.post_call_hook.book_demo_meeting",
        new=AsyncMock(return_value=booking),
    ) as mock_book:
        await run_post_call_hook(
            tenant=_tenant(),
            classification="hot",
            lead_first_name=None,
            lead_phone="+919876543210",
        )
    assert mock_book.await_args.kwargs["broker_name"] == "Broker"
