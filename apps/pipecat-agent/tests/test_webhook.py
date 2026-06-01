"""Tests for HMAC-signed webhook emission.

The critical test here: signing must exactly match verifyHmac() in
packages/shared/src/samvaad/provider.ts. We mirror that JS function in
this file as a parity check.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from voice_agent.webhook import build_event, build_turn_completed, sign_body


def _ts_verify_hmac_equivalent(*, body: str, signature: str, secret: str) -> bool:
    """Pure-Python mirror of the TS verifyHmac in samvaad/provider.ts.

    Compute hex(HMAC-SHA256(secret, body)) and compare constant-time
    against the supplied signature. If this function disagrees with
    sign_body(), webhooks will be rejected in production.
    """
    expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if len(expected) != len(signature):
        return False
    return hmac.compare_digest(expected, signature)


def test_signature_matches_typescript_verifier():
    body = '{"kind":"call.started","call_id":"abc"}'
    sig = sign_body(secret="topsecret", body=body.encode())
    assert _ts_verify_hmac_equivalent(body=body, signature=sig, secret="topsecret") is True


def test_signature_rejects_wrong_secret():
    body = '{"x":1}'
    sig = sign_body(secret="alpha", body=body.encode())
    assert _ts_verify_hmac_equivalent(body=body, signature=sig, secret="beta") is False


def test_signature_rejects_tampered_body():
    body = '{"x":1}'
    sig = sign_body(secret="s", body=body.encode())
    assert _ts_verify_hmac_equivalent(body='{"x":2}', signature=sig, secret="s") is False


def test_canonical_json_is_sorted_and_compact():
    """We sign canonical JSON. The bytes the TS side receives must equal
    the bytes we hashed — no whitespace, sorted keys."""
    evt = build_event("call.started", call_id="c1", event_id="e1", at="2026-05-22T00:00:00Z")
    canonical = json.dumps(evt, separators=(",", ":"), sort_keys=True)
    assert " " not in canonical
    # Sorted keys → at < call_id < event_id < kind
    assert canonical.index('"at"') < canonical.index('"call_id"') < \
        canonical.index('"event_id"') < canonical.index('"kind"')


def test_turn_completed_carries_all_four_timings():
    """All four latency fields must be present on the wire — webhooks-worker
    reads them by name into turn_latencies."""
    evt = build_turn_completed(
        call_id="c1",
        event_id="t1",
        turn_idx=3,
        stt_final_ms=210,
        llm_first_token_ms=240,
        tts_first_chunk_ms=180,
        total_turn_ms=820,
        used_intro_cache=False,
    )
    assert evt["kind"] == "turn.completed"
    for key in (
        "stt_final_ms",
        "llm_first_token_ms",
        "tts_first_chunk_ms",
        "total_turn_ms",
        "used_intro_cache",
        "turn_idx",
    ):
        assert key in evt
    assert evt["total_turn_ms"] == 820


def test_intro_cache_flag_propagates():
    evt = build_turn_completed(
        call_id="c1",
        event_id="t1",
        turn_idx=0,
        stt_final_ms=None,  # first turn, no STT
        llm_first_token_ms=None,  # first turn, no LLM
        tts_first_chunk_ms=120,
        total_turn_ms=250,
        used_intro_cache=True,
    )
    assert evt["used_intro_cache"] is True
    assert evt["stt_final_ms"] is None
    assert evt["total_turn_ms"] == 250
