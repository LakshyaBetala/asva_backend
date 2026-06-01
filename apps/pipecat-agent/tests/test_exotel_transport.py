"""Tests for the Exotel telephony transport.

REST: verify the outbound dial POST shape + auth headers.
WS: verify inbound frame parsing + outbound send_audio / send_clear.
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from voice_agent.exotel_transport import (
    ExotelError,
    ExotelStreamSession,
    OutboundCallRequest,
    StreamMediaFrame,
    StreamStartFrame,
    StreamStopFrame,
    parse_inbound_frame,
    place_outbound_call,
)


# -- REST tests ------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_outbound_call_posts_form_and_auth():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"Call": {"Sid": "exo-call-123", "Status": "queued"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await place_outbound_call(
            request=OutboundCallRequest(
                to="+919876543210",
                caller_id="04447877048",
                flow_url="http://my.exotel.com/almmatix1m/exoml/start_voice/12345",
                custom_field="call-id-xyz",
            ),
            account_sid="acct_sid",
            api_key="ak",
            api_token="atok",
            client=client,
        )

    assert "Calls/connect.json" in captured["url"]
    assert "acct_sid" in captured["url"]
    assert captured["auth"].startswith("Basic ")
    # Exotel dials the lead (From) and shows the ExoPhone (CallerId).
    assert "From=%2B919876543210" in captured["body"]
    assert "CallerId=04447877048" in captured["body"]
    assert "Url=http" in captured["body"]
    assert "start_voice" in captured["body"]
    assert "CustomField=call-id-xyz" in captured["body"]
    assert resp.call_sid == "exo-call-123"
    assert resp.status == "queued"


@pytest.mark.asyncio
async def test_place_outbound_call_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad auth")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ExotelError, match="401"):
            await place_outbound_call(
                request=OutboundCallRequest(
                    to="+91x", caller_id="+91y", flow_url="http://x"
                ),
                account_sid="s", api_key="k", api_token="t", client=client,
            )


@pytest.mark.asyncio
async def test_place_outbound_call_rejects_missing_creds():
    with pytest.raises(ExotelError, match="missing"):
        await place_outbound_call(
            request=OutboundCallRequest(to="+91", caller_id="+91", flow_url="http://x"),
            account_sid="", api_key="", api_token="",
        )


@pytest.mark.asyncio
async def test_place_outbound_call_requires_flow_or_stream():
    with pytest.raises(ExotelError, match="flow_url or stream_url"):
        await place_outbound_call(
            request=OutboundCallRequest(to="+91", caller_id="+91"),
            account_sid="s", api_key="k", api_token="t",
        )


# -- Frame-parsing tests --------------------------------------------------

def test_parse_start_frame_with_flat_layout():
    msg = json.dumps({
        "event": "start",
        "stream_sid": "ss-1",
        "call_sid": "cs-1",
        "custom_field": "lead-123",
    })
    frame = parse_inbound_frame(msg)
    assert isinstance(frame, StreamStartFrame)
    assert frame.stream_sid == "ss-1"
    assert frame.call_sid == "cs-1"
    assert frame.custom_field == "lead-123"


def test_parse_start_frame_with_nested_layout():
    msg = json.dumps({
        "event": "start",
        "start": {
            "streamSid": "ss-2",
            "callSid": "cs-2",
            "customField": "lead-456",
        },
    })
    frame = parse_inbound_frame(msg)
    assert isinstance(frame, StreamStartFrame)
    assert frame.stream_sid == "ss-2"
    assert frame.call_sid == "cs-2"
    assert frame.custom_field == "lead-456"


def test_parse_start_frame_with_custom_parameters():
    # AgentStream passes the API CustomField via start.custom_parameters.
    msg = json.dumps({
        "event": "start",
        "stream_sid": "ss-3",
        "start": {
            "call_sid": "cs-3",
            "custom_parameters": {"CustomField": "lead-789"},
        },
    })
    frame = parse_inbound_frame(msg)
    assert isinstance(frame, StreamStartFrame)
    assert frame.stream_sid == "ss-3"
    assert frame.call_sid == "cs-3"
    assert frame.custom_field == "lead-789"


def test_parse_connected_event_returns_none():
    # Exotel's first handshake frame carries no identifiers; ignore it.
    assert parse_inbound_frame(json.dumps({"event": "connected"})) is None


def test_parse_media_frame_decodes_base64():
    audio = b"\x12\x34\x56"
    msg = json.dumps({
        "event": "media",
        "media": {
            "payload": base64.b64encode(audio).decode(),
            "chunk": 7,
            "timestamp": 1234,
        },
    })
    frame = parse_inbound_frame(msg)
    assert isinstance(frame, StreamMediaFrame)
    assert frame.audio_bytes == audio
    assert frame.chunk_index == 7
    assert frame.timestamp_ms == 1234


def test_parse_stop_frame():
    msg = json.dumps({"event": "stop", "stop": {"reason": "hangup"}})
    frame = parse_inbound_frame(msg)
    assert isinstance(frame, StreamStopFrame)
    assert frame.reason == "hangup"


def test_parse_unknown_event_returns_none():
    assert parse_inbound_frame(json.dumps({"event": "weird"})) is None
    assert parse_inbound_frame("not-json") is None
    assert parse_inbound_frame(json.dumps([1, 2, 3])) is None


# -- WS session tests ------------------------------------------------------

class FakeWebSocket:
    """In-memory WS for tests. Recv pulls from a queue; send appends."""

    def __init__(self, inbound: list[str]):
        self._inbound = list(inbound)
        self.sent: list[str] = []

    async def recv(self) -> str:
        if not self._inbound:
            raise RuntimeError("ws closed")
        return self._inbound.pop(0)

    async def send(self, data: str) -> None:
        self.sent.append(data)


@pytest.mark.asyncio
async def test_session_iterates_start_media_stop_then_closes():
    audio_payload = base64.b64encode(b"AUDIO-CHUNK").decode()
    ws = FakeWebSocket([
        json.dumps({"event": "start", "stream_sid": "ss1", "call_sid": "cs1"}),
        json.dumps({"event": "media", "media": {"payload": audio_payload}}),
        json.dumps({"event": "stop"}),
    ])
    session = ExotelStreamSession(ws)

    frames = []
    async for f in session:
        frames.append(f)

    assert len(frames) == 3
    assert isinstance(frames[0], StreamStartFrame)
    assert isinstance(frames[1], StreamMediaFrame)
    assert frames[1].audio_bytes == b"AUDIO-CHUNK"
    assert isinstance(frames[2], StreamStopFrame)
    # Stream sid captured from start.
    assert session.stream_sid == "ss1"


@pytest.mark.asyncio
async def test_send_audio_b64_encodes_and_includes_stream_sid():
    ws = FakeWebSocket([])
    session = ExotelStreamSession(ws, stream_sid="ss-out")

    await session.send_audio(b"\x01\x02\x03")
    msg = json.loads(ws.sent[0])
    assert msg["event"] == "media"
    assert msg["stream_sid"] == "ss-out"
    assert base64.b64decode(msg["media"]["payload"]) == b"\x01\x02\x03"


@pytest.mark.asyncio
async def test_send_audio_raises_before_start_frame():
    ws = FakeWebSocket([])
    session = ExotelStreamSession(ws)
    with pytest.raises(ExotelError, match="start frame"):
        await session.send_audio(b"x")


@pytest.mark.asyncio
async def test_send_clear_sends_clear_event():
    ws = FakeWebSocket([])
    session = ExotelStreamSession(ws, stream_sid="ss-x")
    await session.send_clear()
    msg = json.loads(ws.sent[0])
    assert msg == {"event": "clear", "stream_sid": "ss-x"}


@pytest.mark.asyncio
async def test_send_clear_noop_when_no_stream_sid():
    ws = FakeWebSocket([])
    session = ExotelStreamSession(ws)
    await session.send_clear()  # must not raise
    assert ws.sent == []


@pytest.mark.asyncio
async def test_session_skips_unknown_frames_and_continues():
    audio = base64.b64encode(b"X").decode()
    ws = FakeWebSocket([
        json.dumps({"event": "start", "stream_sid": "s1", "call_sid": "c1"}),
        "garbage-not-json",
        json.dumps({"event": "weird"}),
        json.dumps({"event": "media", "media": {"payload": audio}}),
        json.dumps({"event": "stop"}),
    ])
    session = ExotelStreamSession(ws)

    frames = [f async for f in session]
    types = [type(f).__name__ for f in frames]
    assert types == ["StreamStartFrame", "StreamMediaFrame", "StreamStopFrame"]
