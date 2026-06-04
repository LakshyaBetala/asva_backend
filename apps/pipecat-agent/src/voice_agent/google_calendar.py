"""Google Calendar adapter — book site visits at end-of-call.

Used by the real_estate industry brain's close hook. Talks directly to the
Calendar REST API via httpx (avoids the heavy google-api-python-client
dependency tree; we only need two endpoints: token refresh + event insert).

Authentication model — OAuth 2.0 refresh-token-per-tenant:

  - App-level credentials in env: GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET.
    Created once in Google Cloud Console (OAuth 2.0 Web Client).
  - Per-tenant refresh token: stored on TenantConfig.google_refresh_token.
    Obtained one-time by sending the broker through the OAuth consent
    screen during onboarding; refresh tokens don't expire unless revoked.
  - Access tokens are minted on demand (~1 hour TTL) and cached
    per-process per-tenant.

Why not a service account? Service accounts can only access calendars
explicitly shared with them, which means the broker has to do a manual
"share calendar with X@iam.gserviceaccount.com" step per tenant. The
refresh-token model lets the broker just click "Allow" once during
onboarding and we own a long-lived credential — better UX, less support.

End-of-call hook behavior:
  - calendar_id missing/empty on tenant       -> log + skip silently
  - refresh_token missing/empty on tenant     -> log + skip silently
  - GOOGLE_CLIENT_ID/SECRET missing on env    -> log + skip silently
  - API call fails                             -> log warning, do not raise
    (a missed booking is recoverable by human follow-up; a raised
    exception would kill the WS shutdown path).
"""

from __future__ import annotations

import datetime
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Google's OAuth token endpoint. Stable URL since 2018.
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Default site-visit duration. Brokers schedule 30-min slots; some power
# users want 60 — overridable per tenant via tenant_config (future), env for now.
DEFAULT_VISIT_MINUTES = int(os.environ.get("CALENDAR_VISIT_MINUTES", "30"))


@dataclass(frozen=True)
class BookingRequest:
    """Inputs to book_site_visit. All fields user-visible on the event."""

    calendar_id: str  # tenant's calendar (often 'primary' or a resource id)
    refresh_token: str  # tenant's OAuth refresh token
    lead_name: str
    lead_phone: str
    locality: str  # canonical English spelling (post real_estate.canonical_locality)
    slot_iso: str  # ISO-8601 datetime, e.g. "2026-06-14T16:00:00+05:30"
    summary_extra: str = ""  # free-text suffix on title, e.g. "2 BHK, 1.2Cr budget"
    notes: str = ""  # body of the event description
    create_meet_link: bool = True
    title_prefix: str = "Site visit"  # overridden for non-realty flows
    duration_minutes: int = DEFAULT_VISIT_MINUTES


@dataclass
class BookingResult:
    """Returned by book_site_visit on success."""

    event_id: str
    html_link: str  # Calendar event URL — shareable with the lead
    meet_link: str | None  # set when create_meet_link=True and Meet provisioned


class CalendarNotConfigured(RuntimeError):
    """Raised internally when app/env credentials missing. Caller logs and skips."""


# Process-wide access-token cache: (refresh_token -> (access_token, expires_at_monotonic))
# Refresh tokens uniquely identify a tenant from our side; access tokens are
# safe to share within one process.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
# Refresh ~5 min before the 60 min token TTL to avoid mid-call 401s.
_TOKEN_REFRESH_SLACK_SEC = 5 * 60


async def _get_access_token(
    refresh_token: str,
    *,
    client_id: str,
    client_secret: str,
    http: httpx.AsyncClient | None = None,
) -> str:
    """Mint or reuse a Google OAuth access token for this refresh_token."""
    cached = _TOKEN_CACHE.get(refresh_token)
    if cached and cached[1] > time.monotonic() + _TOKEN_REFRESH_SLACK_SEC:
        return cached[0]

    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code >= 400:
        # Don't log the token itself — only the response so we can debug
        # without leaking credentials.
        raise CalendarNotConfigured(
            f"Google token refresh failed: {resp.status_code} {resp.text[:200]}"
        )

    payload = resp.json()
    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _TOKEN_CACHE[refresh_token] = (access_token, time.monotonic() + expires_in)
    return access_token


def _build_event_payload(req: BookingRequest) -> dict[str, Any]:
    """Compose the Calendar API event resource. Pure function — easy to test."""
    start = datetime.datetime.fromisoformat(req.slot_iso)
    end = start + datetime.timedelta(minutes=req.duration_minutes)

    title_tail = f" — {req.locality}" if req.locality else ""
    title = f"{req.title_prefix}: {req.lead_name}{title_tail}"
    if req.summary_extra:
        title += f" ({req.summary_extra})"

    description_lines = [
        f"Lead: {req.lead_name}",
        f"Phone: {req.lead_phone}",
    ]
    if req.locality:
        description_lines.append(f"Locality: {req.locality}")
    if req.notes:
        description_lines.append("")
        description_lines.append(req.notes)
    description_lines.append("")
    description_lines.append("Booked by Almmatix Voice Agent.")

    body: dict[str, Any] = {
        "summary": title,
        "description": "\n".join(description_lines),
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
        # Email reminder 1h before, popup 15 min before. Standard broker UX.
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 60},
                {"method": "popup", "minutes": 15},
            ],
        },
    }

    if req.create_meet_link:
        # conferenceData with createRequest forces Calendar to auto-provision
        # a Meet link. Requires `conferenceDataVersion=1` query param on insert.
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            },
        }

    return body


def _is_configured(req: BookingRequest, client_id: str, client_secret: str) -> bool:
    """All four credentials must be present for the booking to be possible."""
    return bool(req.calendar_id and req.refresh_token and client_id and client_secret)


async def book_site_visit(
    req: BookingRequest,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> BookingResult | None:
    """Create a site-visit event on the tenant's Google Calendar.

    Returns None when credentials are missing (logged, never raises) so the
    end-of-call hook can fail open. Returns None on API error too — a missed
    booking is recoverable by human follow-up; a raised exception would kill
    the WS shutdown path.
    """
    cid = client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
    secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not _is_configured(req, cid, secret):
        logger.info(
            "calendar booking skipped (not configured): calendar_id=%r "
            "refresh_token_set=%s client_id_set=%s",
            req.calendar_id, bool(req.refresh_token), bool(cid),
        )
        return None

    try:
        access_token = await _get_access_token(
            req.refresh_token, client_id=cid, client_secret=secret, http=http,
        )
    except CalendarNotConfigured as exc:
        logger.warning("calendar booking skipped: %s", exc)
        return None
    except Exception:
        logger.exception("calendar token refresh failed; skipping booking")
        return None

    payload = _build_event_payload(req)
    insert_url = f"{CALENDAR_API_BASE}/calendars/{req.calendar_id}/events"
    params: dict[str, str | int] = {"sendUpdates": "all"}
    if req.create_meet_link:
        params["conferenceDataVersion"] = 1

    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.post(
            insert_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
            json=payload,
            timeout=15.0,
        )
    except Exception:
        logger.exception("calendar event insert HTTP error")
        return None
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code >= 400:
        logger.warning(
            "calendar event insert failed: %s %s",
            resp.status_code, resp.text[:300],
        )
        return None

    data = resp.json()
    meet_link: str | None = None
    if req.create_meet_link:
        entry_points = (data.get("conferenceData") or {}).get("entryPoints") or []
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri")
                break

    return BookingResult(
        event_id=data["id"],
        html_link=data.get("htmlLink", ""),
        meet_link=meet_link,
    )


async def book_demo_meeting(
    *,
    calendar_id: str,
    refresh_token: str,
    broker_name: str,
    broker_phone: str,
    slot_iso: str,
    broker_focus: str = "",
    primary_pain: str = "",
    duration_minutes: int = 15,
    client_id: str | None = None,
    client_secret: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> BookingResult | None:
    """Book a 15-min Almmatix product demo with the broker.

    Thin wrapper around book_site_visit: same plumbing, demo-flavored title +
    description. Used by the voice_agent_sales brain's end-of-call hook.
    """
    summary_extra = broker_focus or ""
    notes_lines = []
    if primary_pain:
        notes_lines.append(f"Broker pain: {primary_pain}")
    notes_lines.append("Founder Laksh Betala to run the demo.")
    notes_lines.append("Discuss pricing tiers, free pilot terms, integration.")
    req = BookingRequest(
        calendar_id=calendar_id,
        refresh_token=refresh_token,
        lead_name=broker_name,
        lead_phone=broker_phone,
        locality="",
        slot_iso=slot_iso,
        summary_extra=summary_extra,
        notes="\n".join(notes_lines),
        create_meet_link=True,
        title_prefix="Almmatix demo",
        duration_minutes=duration_minutes,
    )
    return await book_site_visit(
        req, client_id=client_id, client_secret=client_secret, http=http,
    )
