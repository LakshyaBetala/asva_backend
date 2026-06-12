"""Hot-phrase cache for Priya's common acknowledgments and transitions.

Why this exists
---------------
Priya says the same ~100 phrases all day: "haan ji", "achha", "theek hai",
"main aapko quote bhejti hoon", "samjha". Live-synthesizing every "haan"
costs ~₹0.10 of Bulbul TTS and adds ~400ms of latency. Pre-synthesizing
them once to R2 and streaming the bytes back costs ~₹0 and ~120ms.

Two tiers of cache:
  1. ACK_CLIPS — pre-recorded 200ms "haan/achha/sari" played without a
     full LLM round-trip. The agent decides to insert one based on
     filler audit + STT confidence; no LLM call needed.
  2. HOT_PHRASES — top-100 longer phrases (5-15 words) like "main aapko
     quote bhejti hoon". When the LLM emits one of these verbatim, we
     check the cache before calling Bulbul.

Cache key = sha256(text + voice_id + lang_code). Voice_id pinned to a
single Sarvam Bulbul voice (Chennai female) across all 3 languages so
voice never swaps on language flip.

This module is platform-pure — no R2 SDK imports. Adapters injected
via Protocol so unit tests work without network.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Protocol


# Pinned Sarvam Bulbul voice for all 3 languages. Bulbul v3 ships with
# multiple voice IDs per language; we pick one and never swap so the
# language transition doesn't double as a voice transition. CRM-configurable
# per tenant; this default matches our agent persona name (Priya).
#
# "-2" suffix: while smallest.ai was the live synthesizer, cache misses
# wrote MEHER audio under the old priya-female keys (the key pins a voice
# the synthesizer didn't honour). Bumping the id orphans those poisoned
# entries so every phrase re-synthesizes with the real Bulbul voice.
PINNED_VOICE_ID = "bulbul-v3:priya-female-2"


def phrase_r2_key(*, text: str, lang: str, voice_id: str = PINNED_VOICE_ID) -> str:
    """Cache key for one pre-synthesized phrase.

    Format: phrase/{lang}/{voice_id}/{sha256-of-text}.mp3
    Hash prevents key collisions and accidentally including PII in paths.
    """
    canonical = f"{text.strip().lower()}|{voice_id}|{lang}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"phrase/{lang}/{voice_id}/{digest}.mp3"


class R2Reader(Protocol):
    async def get(self, key: str) -> bytes | None: ...


class R2Writer(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...


# Synthesizer = Sarvam Bulbul wrapper. Tests inject a stub.
Synthesizer = Callable[[str, str], Awaitable[bytes]]  # (text, lang) -> mp3 bytes


@dataclass
class PhraseLoadResult:
    audio: bytes
    used_cache: bool


async def load_or_synthesize_phrase(
    *,
    text: str,
    lang: str,
    r2_reader: R2Reader,
    r2_writer: R2Writer,
    synthesize: Synthesizer,
    voice_id: str = PINNED_VOICE_ID,
) -> PhraseLoadResult:
    """Return audio bytes for a single phrase, using R2 cache when possible."""
    key = phrase_r2_key(text=text, lang=lang, voice_id=voice_id)
    cached = await r2_reader.get(key)
    if cached is not None:
        return PhraseLoadResult(audio=cached, used_cache=True)

    audio = await synthesize(text, lang)
    asyncio.create_task(_safe_write_back(r2_writer, key, audio))
    return PhraseLoadResult(audio=audio, used_cache=False)


async def _safe_write_back(writer: R2Writer, key: str, body: bytes) -> None:
    """Same isolation pattern as intro_cache. Failures never crash calls."""
    try:
        await writer.put(key, body, "audio/mpeg")
    except Exception:
        pass


# -- Pre-warming ----------------------------------------------------------

# Top 100 phrases Priya uses across all 3 languages. Curated, not generated.
# These are pre-synthesized once via warm_phrase_cache() and live in R2
# for the lifetime of the deployment.
TOP_HOT_PHRASES: dict[str, list[str]] = {
    "hi-IN": [
        # Acknowledgments
        "Haan ji.",
        "Achha.",
        "Theek hai.",
        "Bilkul.",
        "Samjha.",
        "Sahi baat hai.",
        # Transitions
        "Aage badhte hain.",
        "Ek sawaal aur hai.",
        "Aapka time precious hai, jaldi karte hain.",
        # Commit / close
        "Matching options isi number pe WhatsApp kar doongi.",
        "Site visit ke liye Saturday theek rahega ya Sunday?",
        "Team aapko aaj hi call karegi.",
        "WhatsApp pe details bhej dun?",
        "Aapke saath baat karke acha laga.",
        # Soft probes
        "Aapke saath kuch aisa hai?",
        "Aap kaunsa area dekh rahe hain?",
        "Kitne BHK chahiye aapko?",
    ],
    "en-IN": [
        "Got it.",
        "I see.",
        "Understood.",
        "Makes sense.",
        "Sure.",
        "Right.",
        "Let me ask one more thing.",
        "Your time is precious, I'll keep this short.",
        "I'll WhatsApp the matching options to this number.",
        "For the site visit, Saturday or Sunday?",
        "Our team will call you today.",
        "Shall I send details on WhatsApp?",
        "Great talking to you.",
        "Does that match your experience?",
        "Which area are you looking at?",
        "Are you looking to buy or rent?",
    ],
    "ta-IN": [
        "Sari sir.",
        "Aama sir.",
        "Puriyudhu sir.",
        "Sari sari.",
        "Innum oru kelvi sir.",
        "Ungal time priceful, naan konjam quickly mudikkuren.",
        "Matching properties indha number ku WhatsApp la anuppuren sir.",
        "Site visit ku Saturday-aa, Sunday-aa sir?",
        "WhatsApp la details anuppalaamaa sir?",
        "Ungalode pechu nallaa irundhuchu sir.",
        "Andha problem ungalukku irukkaa sir?",
        "Endha area paakareenga sir?",
        "Ethana BHK venum sir?",
    ],
}


# Short ack clips (200-400ms typical). Played without LLM round-trip
# when the lead pauses or asks for confirmation. These are the same
# strings as above but flagged separately because the agent inserts
# them outside the normal turn cycle.
ACK_CLIPS: dict[str, list[str]] = {
    "hi-IN": ["Haan ji.", "Achha.", "Theek hai.", "Bilkul.", "Samjha."],
    "en-IN": ["Got it.", "I see.", "Right.", "Okay.", "Sure."],
    "ta-IN": ["Sari sir.", "Aama sir.", "Puriyudhu sir.", "Sari sari."],
}


async def warm_phrase_cache(
    *,
    r2_writer: R2Writer,
    synthesize: Synthesizer,
    voice_id: str = PINNED_VOICE_ID,
    phrases: dict[str, list[str]] = TOP_HOT_PHRASES,
) -> int:
    """Pre-synthesize all hot phrases to R2. Run once at deploy time.

    Returns the count of phrases successfully written. Failures are
    swallowed (logged in real impl) — partial warm is fine.
    """
    written = 0
    for lang, phrase_list in phrases.items():
        for text in phrase_list:
            try:
                audio = await synthesize(text, lang)
                key = phrase_r2_key(text=text, lang=lang, voice_id=voice_id)
                await r2_writer.put(key, audio, "audio/mpeg")
                written += 1
            except Exception:
                continue
    return written


def all_phrases() -> Iterable[tuple[str, str]]:
    """Iterate (text, lang) for every pre-warmable phrase. Useful for tests."""
    for lang, phrase_list in TOP_HOT_PHRASES.items():
        for text in phrase_list:
            yield (text, lang)
