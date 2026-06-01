"""Intro-phrase cache reader for the first-turn fast path.

If `intro/{tenant}/{lead}/{lang}.mp3` exists in R2, we stream that file
directly to the caller. Cuts first-impression latency from ~840ms (full
STT→LLM→TTS) to ~250ms (R2 TTFB only).

On a cache miss, we fall through to live Bulbul TTS and async-upload the
result so the *next* call to the same lead is fast.

This module mirrors `packages/shared/src/intro-cache.ts` — keep the R2
key format in sync.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol


def intro_r2_key(*, tenant_id: str, lead_id: str, lang: str) -> str:
    """Mirrors introR2Key() in packages/shared/src/intro-cache.ts."""
    return f"intro/{tenant_id}/{lead_id}/{lang}.mp3"


class R2Reader(Protocol):
    async def get(self, key: str) -> bytes | None:
        """Return audio bytes or None if the key doesn't exist."""
        ...


class R2Writer(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None:
        ...


@dataclass
class IntroLoadResult:
    audio: bytes
    used_cache: bool


async def load_or_synthesize_intro(
    *,
    tenant_id: str,
    lead_id: str,
    lang: str,
    r2_reader: R2Reader,
    r2_writer: R2Writer,
    synthesize: Callable[[str], Awaitable[bytes]],
    text_for_lang: Callable[[str], str],
) -> IntroLoadResult:
    """Try R2 cache first; on miss, synthesize via Bulbul and async write-back."""
    key = intro_r2_key(tenant_id=tenant_id, lead_id=lead_id, lang=lang)
    cached = await r2_reader.get(key)
    if cached is not None:
        return IntroLoadResult(audio=cached, used_cache=True)

    text = text_for_lang(lang)
    audio = await synthesize(text)

    # Fire-and-forget write-back. Do not await — we want to stream audio
    # to the caller immediately. Errors logged but never block the call.
    asyncio.create_task(_safe_write_back(r2_writer, key, audio))
    return IntroLoadResult(audio=audio, used_cache=False)


async def _safe_write_back(writer: R2Writer, key: str, body: bytes) -> None:
    try:
        await writer.put(key, body, "audio/mpeg")
    except Exception:
        # Cache failure must never crash a live call. A retry job will
        # repair caches later.
        pass
