"""Tests for the intro-cache reader.

Verifies the R2 fast path, the write-back fallback, and the key format
parity with packages/shared/src/intro-cache.ts.
"""
from __future__ import annotations

import asyncio

import pytest

from voice_agent.intro_cache import (
    IntroLoadResult,
    intro_r2_key,
    load_or_synthesize_intro,
)


def test_r2_key_format_matches_typescript():
    """If this drifts from packages/shared/src/intro-cache.ts the Pipecat
    agent will miss every cache entry the TS layer wrote."""
    assert intro_r2_key(tenant_id="t1", lead_id="l1", lang="en-IN") == \
        "intro/t1/l1/en-IN.mp3"


class FakeReader:
    def __init__(self, store: dict[str, bytes]):
        self.store = store
        self.gets: list[str] = []

    async def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        return self.store.get(key)


class FakeWriter:
    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes, str]] = []

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        self.puts.append((key, body, content_type))


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_audio_and_skips_synth():
    reader = FakeReader({"intro/t1/l1/en-IN.mp3": b"CACHED-AUDIO"})
    writer = FakeWriter()
    synth_called = 0

    async def synth(text: str) -> bytes:
        nonlocal synth_called
        synth_called += 1
        return b"FRESH"

    res = await load_or_synthesize_intro(
        tenant_id="t1",
        lead_id="l1",
        lang="en-IN",
        r2_reader=reader,
        r2_writer=writer,
        synthesize=synth,
        text_for_lang=lambda _l: "Hello",
    )
    assert res.used_cache is True
    assert res.audio == b"CACHED-AUDIO"
    assert synth_called == 0


@pytest.mark.asyncio
async def test_cache_miss_synthesizes_and_schedules_writeback():
    reader = FakeReader({})
    writer = FakeWriter()

    async def synth(text: str) -> bytes:
        return b"FRESH-AUDIO"

    res = await load_or_synthesize_intro(
        tenant_id="t1",
        lead_id="l1",
        lang="hi-IN",
        r2_reader=reader,
        r2_writer=writer,
        synthesize=synth,
        text_for_lang=lambda _l: "Namaste",
    )
    assert res.used_cache is False
    assert res.audio == b"FRESH-AUDIO"

    # Yield to allow the fire-and-forget writeback task to complete.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert any(
        key == "intro/t1/l1/hi-IN.mp3" and body == b"FRESH-AUDIO"
        for key, body, _ct in writer.puts
    )


@pytest.mark.asyncio
async def test_writeback_failure_does_not_break_call():
    reader = FakeReader({})

    class BadWriter:
        async def put(self, key, body, content_type):
            raise RuntimeError("R2 down")

    async def synth(text: str) -> bytes:
        return b"OK"

    # Must not raise even though writeback explodes.
    res = await load_or_synthesize_intro(
        tenant_id="t1",
        lead_id="l1",
        lang="en-IN",
        r2_reader=reader,
        r2_writer=BadWriter(),
        synthesize=synth,
        text_for_lang=lambda _l: "Hello",
    )
    assert res.audio == b"OK"
    await asyncio.sleep(0)  # let the failing task run
    await asyncio.sleep(0)
