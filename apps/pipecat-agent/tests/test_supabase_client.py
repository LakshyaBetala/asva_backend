"""Tests for the agent-side Supabase client.

We mock httpx to verify the correct PostgREST calls are made with the
right headers, table names, and payloads. No real Supabase connection.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from voice_agent.supabase_client import (
    AgentSupabaseClient,
    SupabaseConfig,
    SupabaseConfigError,
    persist_turn_async,
)


def _config() -> SupabaseConfig:
    return SupabaseConfig(
        url="https://test.supabase.co",
        service_role_key="sr_test_key",
    )


def test_config_from_env_reads_keys():
    cfg = SupabaseConfig.from_env({
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sr_k",
    })
    assert cfg.url == "https://x.supabase.co"
    assert cfg.service_role_key == "sr_k"


def test_config_from_env_falls_back_to_next_public():
    cfg = SupabaseConfig.from_env({
        "NEXT_PUBLIC_SUPABASE_URL": "https://y.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sr_k",
    })
    assert cfg.url == "https://y.supabase.co"


def test_config_from_env_raises_on_missing():
    with pytest.raises(SupabaseConfigError, match="SUPABASE_URL"):
        SupabaseConfig.from_env({})


@pytest.mark.asyncio
async def test_upsert_qualification_slots_sends_correct_request():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        await db.upsert_qualification_slots(
            call_id="c1", tenant_id="t1", lead_id="l1",
            slots_row={"product_interest": "toluene", "buying_confidence": 0.7},
        )

    assert "qualification_slots" in captured["url"]
    assert "on_conflict=call_id" in captured["url"]
    assert captured["body"]["call_id"] == "c1"
    assert captured["body"]["product_interest"] == "toluene"
    assert captured["headers"]["authorization"] == "Bearer sr_test_key"


@pytest.mark.asyncio
async def test_insert_turn_latency_posts_to_correct_table():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        await db.insert_turn_latency(
            call_id="c1", tenant_id="t1", turn_idx=3,
            stt_ms=500, llm_ms=1200, tts_ms=800, total_ms=2500,
        )

    assert "turn_latencies" in captured["url"]
    assert captured["body"]["turn_idx"] == 3
    assert captured["body"]["stt_final_ms"] == 500
    assert captured["body"]["total_turn_ms"] == 2500


@pytest.mark.asyncio
async def test_insert_transcript_posts_with_speaker_and_text():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        await db.insert_transcript(
            call_id="c1", speaker="lead", text="haan ji",
            lang="hi-IN", turn_idx=2,
        )

    assert captured["body"]["speaker"] == "lead"
    assert captured["body"]["text"] == "haan ji"
    assert captured["body"]["lang"] == "hi-IN"
    assert captured["body"]["idx"] == 2
    assert captured["body"]["ts_ms"] == 20000


@pytest.mark.asyncio
async def test_update_call_status_patches_with_filters():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        # Writes are gated on real UUIDs (placeholder ids no-op silently).
        cid = "11111111-2222-3333-4444-555555555555"
        await db.update_call_status(
            call_id=cid, status="completed",
            duration_sec=145, billed_units=1,
        )

    assert "calls" in captured["url"]
    assert f"id=eq.{cid}" in captured["url"]
    assert captured["body"]["status"] == "completed"
    assert captured["body"]["duration_sec"] == 145
    assert captured["body"]["billed_units"] == 1


@pytest.mark.asyncio
async def test_failed_post_logs_but_does_not_raise():
    """DB failure must never crash a call."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        # Must NOT raise.
        await db.insert_turn_latency(
            call_id="c1", tenant_id="t1", turn_idx=0, total_ms=0,
        )


@pytest.mark.asyncio
async def test_persist_turn_async_fires_all_writes():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url).split("/rest/v1/")[1].split("?")[0])
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        db = AgentSupabaseClient(_config(), client=http)
        # Writes are gated on real UUIDs (placeholder ids no-op silently).
        persist_turn_async(
            db,
            call_id="11111111-2222-3333-4444-555555555555",
            tenant_id="22222222-3333-4444-5555-666666666666",
            lead_id="33333333-4444-5555-6666-777777777777",
            turn_idx=1,
            lead_text="haan ji", lead_lang="hi-IN", priya_text="achha",
            slots_row={"buying_confidence": 0.5},
            latency={"stt_ms": 500, "llm_ms": 1200, "tts_ms": 800, "total_ms": 2500},
        )
        # Let the fire-and-forget tasks run.
        await asyncio.sleep(0.1)

    assert "qualification_slots" in calls
    assert "turn_latencies" in calls
    assert calls.count("transcripts") == 2  # lead + priya


@pytest.mark.asyncio
async def test_persist_turn_async_noop_when_db_is_none():
    """When Supabase is unconfigured, persist_turn_async is a no-op."""
    persist_turn_async(
        None,
        call_id="c1", tenant_id="t1", lead_id="l1", turn_idx=0,
        lead_text="x", lead_lang="en-IN", priya_text="y",
        slots_row={}, latency={},
    )
    # Must not raise.
