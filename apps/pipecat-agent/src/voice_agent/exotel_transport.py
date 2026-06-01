"""Exotel telephony transport — outbound dialer + bidirectional audio stream.

Two surfaces:

  1. place_outbound_call() — Exotel REST API call to start an outbound
     dial. Exotel rings the lead and, when answered, connects to our
     stream URL via the "Voicebot / Voice Streaming" applet.
  2. ExotelStreamSession — async iterator wrapping the WebSocket Exotel
     opens to us once the call connects. Pipecat reads inbound audio
     frames from this and writes outbound TTS frames back.

Exotel's WebSocket framing
--------------------------
Exotel sends JSON messages over WS, each containing base64-encoded
audio chunks. Format (per Exotel Voice Streaming docs):

  Inbound (Exotel → us):
    {"event": "start", "stream_sid": "...", "call_sid": "...", ...}
    {"event": "media", "media": {"payload": "<b64 mu-law>", "chunk": 1, ...}}
    {"event": "stop", ...}

  Outbound (us → Exotel):
    {"event": "media", "stream_sid": "...",
     "media": {"payload": "<b64 mu-law>"}}
    {"event": "clear", "stream_sid": "..."}      # interrupt playback

Audio is 8 kHz μ-law mono (G.711) — same as Plivo. Our Sarvam TTS
returns 8 kHz WAV; we strip the WAV header + convert PCM → μ-law before
sending. Conversion lives in audio_codec.py to keep this module thin.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol
from urllib.parse import urlencode

import httpx


EXOTEL_BASE_DEFAULT = "https://api.exotel.com"
EXOTEL_BASE_IN = "https://api.in.exotel.com"  # Mumbai / India region
EXOTEL_BASE_SG = "https://api.sg.exotel.com"  # Singapore region
EXOTEL_BASE_US = "https://api.us.exotel.com"  # US region
DEFAULT_TIMEOUT_SECONDS = 10.0


def base_url_for_region(region: str | None) -> str:
    """Map an account region code to the correct Exotel API base.

    Exotel routes accounts by region and REJECTS credentials presented to the
    wrong regional endpoint with a 401. The dashboard shows your region under
    "API Credentials → Account region". `api.exotel.com` is the legacy global
    endpoint; India (Mumbai) accounts must hit api.in.exotel.com.
    """
    if not region:
        return EXOTEL_BASE_DEFAULT
    r = region.strip().lower()
    if r in {"in", "india", "mumbai", "ap-south-1"}:
        return EXOTEL_BASE_IN
    if r in {"sg", "singapore", "ap-southeast-1"}:
        return EXOTEL_BASE_SG
    if r in {"us", "us-east-1"}:
        return EXOTEL_BASE_US
    return EXOTEL_BASE_DEFAULT


class ExotelError(RuntimeError):
    """Raised for non-2xx REST responses or malformed stream frames."""


# -- REST: outbound call placement -----------------------------------------

@dataclass(frozen=True)
class OutboundCallRequest:
    to: str  # E.164 lead number — Exotel dials this (the "From" leg of connect)
    caller_id: str  # ExoPhone shown to the lead as caller ID
    # AgentStream path: Url points at an Exotel App flow whose first applet is
    # the Voicebot applet (the WSS endpoint is configured INSIDE that applet in
    # App Bazaar, not passed here). Format:
    #   http://my.exotel.com/{sid}/exoml/start_voice/{app_id}
    flow_url: str | None = None
    # Legacy Plivo-style direct StreamUrl. Only used when flow_url is unset.
    stream_url: str | None = None
    custom_field: str | None = None  # echoed back in the start frame; call_id
    status_callback: str | None = None  # POST'd by Exotel when call ends
    record: bool = True
    time_limit_seconds: int = 600  # matches HARD_CAP_SECONDS (4-cred billing tier)


@dataclass(frozen=True)
class OutboundCallResponse:
    call_sid: str
    status: str  # queued | in-progress | completed | failed
    raw: dict[str, Any]


async def place_outbound_call(
    *,
    request: OutboundCallRequest,
    account_sid: str,
    api_key: str,
    api_token: str,
    region: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> OutboundCallResponse:
    """POST /v1/Accounts/{sid}/Calls/connect — places one outbound call.

    For AgentStream: Exotel dials `to` (the lead) showing `caller_id`
    (the ExoPhone). When answered it runs the App flow at `flow_url`,
    whose Voicebot applet opens the bidirectional WebSocket to us. The
    call lifecycle webhooks hit the URLs configured on your App in the
    Exotel dashboard plus the `status_callback` here.
    """
    if not account_sid or not api_key or not api_token:
        raise ExotelError("missing Exotel credentials")
    if not (request.flow_url or request.stream_url):
        raise ExotelError("OutboundCallRequest needs flow_url or stream_url")

    base = base_url_for_region(region)
    url = f"{base}/v1/Accounts/{account_sid}/Calls/connect.json"
    # Exotel uses HTTP Basic auth with API_KEY:API_TOKEN.
    auth = httpx.BasicAuth(api_key, api_token)

    # In connect-to-flow, `From` is the number Exotel dials (the lead) and
    # `Url` is the flow it runs once answered. `CallerId` is the ExoPhone.
    form = {
        "From": request.to,
        "CallerId": request.caller_id,
        "Record": "true" if request.record else "false",
        "TimeLimit": str(request.time_limit_seconds),
    }
    if request.flow_url:
        form["Url"] = request.flow_url
    else:
        form["StreamUrl"] = request.stream_url  # type: ignore[assignment]
    if request.custom_field:
        form["CustomField"] = request.custom_field
    if request.status_callback:
        form["StatusCallback"] = request.status_callback

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.post(
            url,
            data=form,
            auth=auth,
            timeout=timeout,
        )
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        raise ExotelError(f"Exotel {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    call = payload.get("Call") or payload
    return OutboundCallResponse(
        call_sid=str(call.get("Sid") or call.get("CallSid") or ""),
        status=str(call.get("Status") or "queued"),
        raw=payload,
    )


async def hangup_call(
    *,
    call_sid: str,
    account_sid: str,
    api_key: str,
    api_token: str,
    region: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """End an in-progress call via Exotel REST.

    DELETE /v1/Accounts/{sid}/Calls/{CallSid}.json marks the call completed
    on Exotel's side and drops the carrier leg. Without this, closing only
    the WebSocket from our side can leave the phone line open in some
    Voicebot-applet flows — the lead hears silence instead of a clean hangup.

    Best-effort: log and swallow errors so a failed REST hangup doesn't
    crash the WS handler. The WebSocket close still happens regardless.
    """
    if not call_sid or not account_sid or not api_key or not api_token:
        return
    base = base_url_for_region(region)
    url = f"{base}/v1/Accounts/{account_sid}/Calls/{call_sid}.json"
    auth = httpx.BasicAuth(api_key, api_token)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.delete(url, auth=auth, timeout=timeout)
        if resp.status_code >= 400:
            # Some accounts only support POST-with-Status=completed; try that fallback.
            resp = await http.post(
                url, data={"Status": "completed"}, auth=auth, timeout=timeout,
            )
            if resp.status_code >= 400:
                raise ExotelError(
                    f"Exotel hangup {resp.status_code}: {resp.text[:200]}"
                )
    finally:
        if owns_client:
            await http.aclose()


# -- WebSocket: bidirectional audio stream ---------------------------------

class WebSocketLike(Protocol):
    """The subset of a WS client we use. Both `websockets` and Starlette's
    WebSocket satisfy this; tests inject a fake."""

    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...


@dataclass
class StreamMediaFrame:
    """Inbound audio chunk from the lead."""

    payload_b64: str
    chunk_index: int
    timestamp_ms: int | None

    @property
    def audio_bytes(self) -> bytes:
        """Raw μ-law 8 kHz bytes as Exotel delivered them."""
        return base64.b64decode(self.payload_b64)


@dataclass
class StreamStartFrame:
    """First frame on stream open — contains identifiers."""

    stream_sid: str
    call_sid: str
    custom_field: str | None


@dataclass
class StreamStopFrame:
    """Final frame — call ended."""

    reason: str | None


StreamFrame = StreamMediaFrame | StreamStartFrame | StreamStopFrame


class ExotelStreamSession:
    """Wraps an Exotel WebSocket. Async-iterates inbound frames; provides
    `send_audio()` and `send_clear()` for outbound."""

    def __init__(self, ws: WebSocketLike, *, stream_sid: str | None = None) -> None:
        self.ws = ws
        self.stream_sid = stream_sid
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[StreamFrame]:
        while not self._closed:
            try:
                raw = await self.ws.recv()
            except Exception:
                self._closed = True
                return
            frame = parse_inbound_frame(raw)
            if frame is None:
                continue
            # Capture stream_sid from start frame so outbound frames can echo it.
            if isinstance(frame, StreamStartFrame):
                self.stream_sid = frame.stream_sid
            yield frame
            if isinstance(frame, StreamStopFrame):
                self._closed = True
                return

    async def send_audio(self, mu_law_bytes: bytes) -> None:
        """Push one outbound audio frame back to the lead's ear."""
        if not self.stream_sid:
            raise ExotelError("cannot send_audio before receiving start frame")
        frame = {
            "event": "media",
            "stream_sid": self.stream_sid,
            "media": {"payload": base64.b64encode(mu_law_bytes).decode("ascii")},
        }
        await self.ws.send(json.dumps(frame))

    async def send_clear(self) -> None:
        """Interrupt currently-playing TTS — used when lead barge-ins.

        Without this, the lead's interruption gets queued behind the rest
        of Priya's outbound buffer and she sounds like she's not listening.
        """
        if not self.stream_sid:
            return
        await self.ws.send(json.dumps({"event": "clear", "stream_sid": self.stream_sid}))


# -- Frame parsing ---------------------------------------------------------

def parse_inbound_frame(raw: str) -> StreamFrame | None:
    """Decode one Exotel WS message. Returns None for unknown event types."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None

    event = msg.get("event")
    if event == "connected":
        # Exotel's first frame is a bare {"event":"connected"} handshake. No
        # identifiers yet — ignore it; the "start" frame carries the IDs.
        return None
    if event == "start":
        # Some Exotel deployments wrap identifiers under "start", others flat.
        start = msg.get("start") or msg
        custom_field = start.get("custom_field") or start.get("customField")
        if not custom_field:
            # AgentStream passes API CustomField via custom_parameters.
            params = start.get("custom_parameters") or start.get("customParameters") or {}
            if isinstance(params, dict):
                custom_field = (
                    params.get("call_id")
                    or params.get("CustomField")
                    or params.get("custom_field")
                )
        return StreamStartFrame(
            stream_sid=str(
                msg.get("stream_sid")
                or start.get("stream_sid")
                or start.get("streamSid")
                or ""
            ),
            call_sid=str(start.get("call_sid") or start.get("callSid") or ""),
            custom_field=custom_field,
        )
    if event == "media":
        media = msg.get("media") or {}
        payload = media.get("payload")
        if not payload:
            return None
        try:
            chunk_idx = int(media.get("chunk") or 0)
        except (TypeError, ValueError):
            chunk_idx = 0
        try:
            ts = int(media.get("timestamp")) if media.get("timestamp") else None
        except (TypeError, ValueError):
            ts = None
        return StreamMediaFrame(
            payload_b64=str(payload),
            chunk_index=chunk_idx,
            timestamp_ms=ts,
        )
    if event == "stop":
        stop = msg.get("stop") or {}
        return StreamStopFrame(reason=stop.get("reason"))
    return None
