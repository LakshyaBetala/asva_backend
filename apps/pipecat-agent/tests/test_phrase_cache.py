"""Tests for phrase_cache.py — hot-phrase + ack-clip cache."""
from __future__ import annotations

import asyncio

import pytest

from voice_agent.phrase_cache import (
    ACK_CLIPS,
    PINNED_VOICE_ID,
    TOP_HOT_PHRASES,
    all_phrases,
    load_or_synthesize_phrase,
    phrase_r2_key,
    warm_phrase_cache,
)


class StubR2:
    def __init__(self, store: dict[str, bytes] | None = None, *, get_raises: bool = False, put_raises: bool = False):
        self.store = dict(store or {})
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.get_calls: list[str] = []
        self.get_raises = get_raises
        self.put_raises = put_raises

    async def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        if self.get_raises:
            raise RuntimeError("simulated get failure")
        return self.store.get(key)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        self.put_calls.append((key, body, content_type))
        if self.put_raises:
            raise RuntimeError("simulated put failure")
        self.store[key] = body


def _stub_synth(audio: bytes = b"fake-mp3-bytes"):
    async def _call(text: str, lang: str) -> bytes:
        return audio + f"::{lang}::{text}".encode()
    return _call


class TestKeyShape:
    def test_key_is_stable_for_same_input(self):
        k1 = phrase_r2_key(text="haan ji.", lang="hi-IN")
        k2 = phrase_r2_key(text="haan ji.", lang="hi-IN")
        assert k1 == k2

    def test_key_differs_by_language(self):
        k_hi = phrase_r2_key(text="okay", lang="hi-IN")
        k_en = phrase_r2_key(text="okay", lang="en-IN")
        assert k_hi != k_en

    def test_key_starts_with_phrase_prefix(self):
        k = phrase_r2_key(text="haan ji.", lang="hi-IN")
        assert k.startswith("phrase/hi-IN/")
        assert k.endswith(".mp3")

    def test_case_insensitive_text(self):
        """'Haan Ji.' and 'HAAN JI.' should map to the same cache entry."""
        k1 = phrase_r2_key(text="Haan Ji.", lang="hi-IN")
        k2 = phrase_r2_key(text="HAAN JI.", lang="hi-IN")
        assert k1 == k2


@pytest.mark.asyncio
class TestLoadOrSynthesize:
    async def test_cache_hit_skips_synthesis(self):
        r2 = StubR2()
        key = phrase_r2_key(text="theek hai.", lang="hi-IN")
        r2.store[key] = b"cached-bytes"

        synth_called = False
        async def synth(text, lang):
            nonlocal synth_called
            synth_called = True
            return b"live"

        out = await load_or_synthesize_phrase(
            text="theek hai.",
            lang="hi-IN",
            r2_reader=r2,
            r2_writer=r2,
            synthesize=synth,
        )
        assert out.used_cache is True
        assert out.audio == b"cached-bytes"
        assert synth_called is False

    async def test_cache_miss_synthesizes_and_writes_back(self):
        r2 = StubR2()
        out = await load_or_synthesize_phrase(
            text="brand new phrase",
            lang="en-IN",
            r2_reader=r2,
            r2_writer=r2,
            synthesize=_stub_synth(),
        )
        assert out.used_cache is False
        # Give the fire-and-forget write-back a chance to run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(r2.put_calls) == 1
        key, body, ct = r2.put_calls[0]
        assert ct == "audio/mpeg"
        assert body == b"fake-mp3-bytes::en-IN::brand new phrase"

    async def test_write_back_failure_does_not_crash(self):
        r2 = StubR2(put_raises=True)
        out = await load_or_synthesize_phrase(
            text="new",
            lang="hi-IN",
            r2_reader=r2,
            r2_writer=r2,
            synthesize=_stub_synth(),
        )
        await asyncio.sleep(0)
        # No exception bubbled out — that's the assertion.
        assert out.used_cache is False


@pytest.mark.asyncio
class TestWarmCache:
    async def test_warm_writes_all_phrases(self):
        r2 = StubR2()
        # Use a smaller set for the test
        mini = {"en-IN": ["one", "two", "three"], "hi-IN": ["ek", "do"]}
        n = await warm_phrase_cache(r2_writer=r2, synthesize=_stub_synth(), phrases=mini)
        assert n == 5
        assert len(r2.put_calls) == 5

    async def test_warm_continues_past_individual_failure(self):
        r2 = StubR2()
        calls = 0
        async def flaky_synth(text, lang):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("flake")
            return b"audio"

        n = await warm_phrase_cache(
            r2_writer=r2,
            synthesize=flaky_synth,
            phrases={"en-IN": ["a", "b", "c"]},
        )
        assert n == 2  # one failure, two successes


class TestStaticPhraseSets:
    def test_top_hot_phrases_has_all_three_languages(self):
        assert set(TOP_HOT_PHRASES.keys()) == {"hi-IN", "en-IN", "ta-IN"}
        for lang, phrases in TOP_HOT_PHRASES.items():
            assert len(phrases) >= 10, f"{lang} has only {len(phrases)} phrases"

    def test_ack_clips_have_all_three_languages(self):
        assert set(ACK_CLIPS.keys()) == {"hi-IN", "en-IN", "ta-IN"}
        for lang, clips in ACK_CLIPS.items():
            assert len(clips) >= 3, f"{lang} has only {len(clips)} ack clips"

    def test_voice_id_pinned(self):
        assert PINNED_VOICE_ID
        assert "bulbul" in PINNED_VOICE_ID.lower()

    def test_all_phrases_iterator(self):
        phrases = list(all_phrases())
        # Count from TOP_HOT_PHRASES
        expected = sum(len(v) for v in TOP_HOT_PHRASES.values())
        assert len(phrases) == expected
