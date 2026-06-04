"""End-of-call hook: book the demo on Google Calendar + send WhatsApp confirm.

Wired into the StatusCallback handler in `exotel_ws_handler.py`. Runs
fire-and-forget after the lead_scorer classifies the call. Only fires for
hot/warm classifications — cold/dead calls don't get bookings (avoids
spamming wrong-number leads with WhatsApp templates).

Fail-open everywhere: a missing tenant credential, an API timeout, or an
unparseable phone number must NOT raise. The hook is best-effort plumbing;
the source of truth is the human salesperson who reads the CRM and follows up.

MVP slot strategy:
  We don't yet extract a specific demo time from the conversation
  (Priya defers all logistics to "Laksh demo mein dikha denge"). So the
  hook books a default slot — tomorrow 11:00 IST — and the human team
  reschedules via Calendar if the broker needs another time. Locking in
  a placeholder slot is better than booking nothing, because the Meet
  link + WhatsApp message create a real obligation in the broker's inbox
  within minutes of hangup — the moment they remember the call.
"""
from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

from .google_calendar import BookingResult, book_demo_meeting
from .tenant_config import TenantConfig
from .whatsapp import WhatsAppDemoConfirmRequest, send_demo_confirm

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Classifications that trigger a booking. "dead" and "cold" never book —
# they're either wrong numbers or uninterested, and a WhatsApp template to
# either burns Meta quality score for zero pipeline value.
_QUALIFYING_CLASSIFICATIONS = {"hot", "warm"}


@dataclass(frozen=True)
class PostCallHookResult:
    """Returned to the caller so the WS handler can log a single summary line."""

    booked: bool
    whatsapp_sent: bool
    meet_link: Optional[str]
    event_id: Optional[str]
    reason: str  # short tag for the log line: "skipped:cold", "booked", "no_calendar", etc.


def default_demo_slot(now_ist: Optional[datetime.datetime] = None) -> str:
    """Tomorrow 11:00 IST, ISO-8601 with offset. Stable, easy to reschedule.

    Why 11:00? Brokers usually open shop ~10:30 (residential clients call
    them in the morning before office), and 11:00 lands after their first
    coffee but before the noon walk-in rush. A 15-min slot in that window
    is the least-disruptive ask we can make sight-unseen.
    """
    now = now_ist or datetime.datetime.now(tz=IST)
    tomorrow = (now + datetime.timedelta(days=1)).date()
    slot = datetime.datetime.combine(
        tomorrow, datetime.time(11, 0), tzinfo=IST,
    )
    return slot.isoformat()


def humanize_slot(slot_iso: str) -> str:
    """Render an ISO slot in the form WhatsApp template {{2}} expects.

    English-first because the approved template language is "en"; the broker
    parses date+time visually anyway. e.g. "Tue 09 Jun, 11:00 AM IST".
    """
    try:
        dt = datetime.datetime.fromisoformat(slot_iso).astimezone(IST)
    except (ValueError, TypeError):
        return slot_iso
    return dt.strftime("%a %d %b, %I:%M %p IST").replace(" 0", " ")


async def run_post_call_hook(
    *,
    tenant: TenantConfig,
    classification: str,
    lead_first_name: Optional[str],
    lead_phone: str,
    primary_pain: str = "",
    broker_focus: str = "",
    slot_iso: Optional[str] = None,
) -> PostCallHookResult:
    """Book Calendar + send WhatsApp for qualifying leads.

    Never raises. Returns a result the caller can log in one line:
        "post_call_hook: booked=True wa=True meet=https://..."
    """
    cls = (classification or "").lower().strip()
    if cls not in _QUALIFYING_CLASSIFICATIONS:
        return PostCallHookResult(
            booked=False, whatsapp_sent=False, meet_link=None,
            event_id=None, reason=f"skipped:{cls or 'unknown'}",
        )

    if not tenant.has_calendar():
        return PostCallHookResult(
            booked=False, whatsapp_sent=False, meet_link=None,
            event_id=None, reason="no_calendar",
        )

    broker_name = (lead_first_name or "Broker").strip() or "Broker"
    slot = slot_iso or default_demo_slot()

    booking: BookingResult | None = await book_demo_meeting(
        calendar_id=tenant.google_calendar_id,
        refresh_token=tenant.google_refresh_token,
        broker_name=broker_name,
        broker_phone=lead_phone or "",
        slot_iso=slot,
        broker_focus=broker_focus,
        primary_pain=primary_pain,
        duration_minutes=15,
    )

    if booking is None:
        # book_demo_meeting already logged the why (missing creds, API err, etc.)
        return PostCallHookResult(
            booked=False, whatsapp_sent=False, meet_link=None,
            event_id=None, reason="booking_failed",
        )

    # WhatsApp follow-up — only meaningful when we have both a Meet link and
    # the lead's phone. Without the Meet link the template body would render
    # "null", which Meta rejects with 132000.
    wa_sent = False
    if tenant.has_whatsapp() and lead_phone and booking.meet_link:
        wa_req = WhatsAppDemoConfirmRequest(
            phone_number_id=tenant.whatsapp_phone_id,
            access_token=tenant.whatsapp_access_token,
            template_name=tenant.whatsapp_template_name,
            to_phone_e164=lead_phone,
            broker_name=broker_name,
            demo_when_human=humanize_slot(slot),
            meet_link=booking.meet_link,
        )
        wa_result = await send_demo_confirm(wa_req)
        wa_sent = wa_result is not None

    return PostCallHookResult(
        booked=True,
        whatsapp_sent=wa_sent,
        meet_link=booking.meet_link,
        event_id=booking.event_id,
        reason="booked",
    )
