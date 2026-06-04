"""WhatsApp Cloud API adapter — fire post-call demo confirmations.

Used by both the real_estate (site-visit reminder) and voice_agent_sales
(demo-meeting confirmation) end-of-call hooks. Talks directly to the Meta
Graph API via httpx; we only need one endpoint (POST /messages).

Authentication model — system-user permanent token per tenant:

  - Each tenant onboards their Meta Business Manager + WhatsApp Business
    Account once. We get back: phone_number_id, business_account_id, and a
    System User permanent token. All three live on TenantConfig.
  - No OAuth refresh dance — Meta's permanent tokens don't expire unless
    revoked from Business Manager.

Message model — approved templates only:

  - For business-initiated messages outside the 24h customer service window,
    Meta requires a pre-approved Message Template. We use one template,
    `almmatix_demo_confirm`, with these body parameters:
        {{1}} broker name
        {{2}} demo date+time
        {{3}} Google Meet link
    Tenants override the template name via TenantConfig.whatsapp_template_name
    if they have their own brand-approved version.

End-of-call hook behavior:
  - any of phone_id / business_id / token / to-number missing → log + skip
  - API call fails                                            → log warning, no raise
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Stable since 2023-Q2. Bump version when Meta deprecates.
GRAPH_API_VERSION = os.environ.get("WHATSAPP_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Default template language code. Override per tenant later if needed.
DEFAULT_TEMPLATE_LANG = os.environ.get("WHATSAPP_TEMPLATE_LANG", "en")

_PHONE_STRIP_RE = re.compile(r"[^\d]")


@dataclass(frozen=True)
class WhatsAppDemoConfirmRequest:
    """Inputs to send_demo_confirm. Maps to the almmatix_demo_confirm template."""

    phone_number_id: str  # tenant's phone_number_id from Meta Business Manager
    access_token: str  # tenant's system-user permanent token
    template_name: str  # e.g. "almmatix_demo_confirm"
    to_phone_e164: str  # broker's phone, will be normalized to E.164 digits
    broker_name: str
    demo_when_human: str  # e.g. "Kal subah 11 baje" or "Tomorrow 11 AM IST"
    meet_link: str  # the Google Meet URL from book_demo_meeting
    template_lang: str = DEFAULT_TEMPLATE_LANG


@dataclass
class WhatsAppSendResult:
    """Returned by send_demo_confirm on success."""

    message_id: str  # Meta's wamid — opaque, useful for support/debug


def normalize_to_msisdn(raw: str) -> str:
    """Strip everything non-digit. Meta expects bare E.164 digits, no '+'."""
    digits = _PHONE_STRIP_RE.sub("", raw or "")
    # Tolerate a stray leading '0' for Indian 11-digit inputs (091XXXXXXXXX).
    if digits.startswith("0") and len(digits) > 10:
        digits = digits.lstrip("0")
    # If user passed a 10-digit Indian mobile, prepend country code.
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _build_template_payload(req: WhatsAppDemoConfirmRequest) -> dict:
    """Compose the Meta /messages payload for a template send."""
    return {
        "messaging_product": "whatsapp",
        "to": normalize_to_msisdn(req.to_phone_e164),
        "type": "template",
        "template": {
            "name": req.template_name,
            "language": {"code": req.template_lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": req.broker_name},
                        {"type": "text", "text": req.demo_when_human},
                        {"type": "text", "text": req.meet_link},
                    ],
                },
            ],
        },
    }


def _is_configured(req: WhatsAppDemoConfirmRequest) -> bool:
    return bool(
        req.phone_number_id
        and req.access_token
        and req.template_name
        and req.to_phone_e164
    )


async def send_demo_confirm(
    req: WhatsAppDemoConfirmRequest,
    *,
    http: httpx.AsyncClient | None = None,
) -> WhatsAppSendResult | None:
    """Send the demo-confirm WhatsApp template. Fail-open: never raises.

    Returns None when credentials are missing (logged) so the end-of-call
    hook can stay alive even on misconfigured tenants. Returns None on API
    error too — a missed WhatsApp is recoverable by human follow-up.
    """
    if not _is_configured(req):
        logger.info(
            "whatsapp send skipped (not configured): phone_id_set=%s "
            "token_set=%s template=%r to=%r",
            bool(req.phone_number_id), bool(req.access_token),
            req.template_name, req.to_phone_e164,
        )
        return None

    payload = _build_template_payload(req)
    url = f"{GRAPH_BASE}/{req.phone_number_id}/messages"

    owns_client = http is None
    client = http or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {req.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
    except Exception:
        logger.exception("whatsapp send HTTP error")
        return None
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code >= 400:
        # Meta returns a useful error.message; truncate to keep logs small.
        logger.warning(
            "whatsapp send failed: %s %s", resp.status_code, resp.text[:300],
        )
        return None

    data = resp.json()
    messages = data.get("messages") or []
    if not messages:
        logger.warning("whatsapp send returned no message id: %s", data)
        return None
    return WhatsAppSendResult(message_id=messages[0].get("id", ""))
