"""HMAC-signed event emitter to the webhooks-worker.

The signature format MUST match `verifyHmac` in
`packages/shared/src/samvaad/provider.ts`:

  signature = lowercase hex of HMAC-SHA256(secret, body)
  header    = x-samvaad-signature

If this drifts, every webhook will be rejected as invalid signature.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx


def sign_body(*, secret: str, body: bytes) -> str:
    """Hex-encoded HMAC-SHA256, lowercase. Matches the TS verifier exactly."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


EventKind = Literal[
    "call.started",
    "call.answered",
    "transcript.chunk",
    "turn.completed",
    "call.ended",
    "recording.ready",
]


@dataclass
class WebhookEmitter:
    url: str
    secret: str
    timeout_s: float = 5.0
    _client: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient())

    async def emit(self, event: dict[str, Any]) -> None:
        """Send a signed event. Caller owns retry policy."""
        # Canonical JSON: compact, sorted keys → deterministic for HMAC.
        body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = sign_body(secret=self.secret, body=body)
        headers = {
            "content-type": "application/json",
            "x-samvaad-signature": sig,
        }
        await self._client.post(
            self.url, content=body, headers=headers, timeout=self.timeout_s
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_event(
    kind: EventKind,
    *,
    call_id: str,
    event_id: str,
    **payload: Any,
) -> dict[str, Any]:
    """Factory matching SamvaadEvent in packages/shared/src/samvaad/types.ts."""
    base: dict[str, Any] = {"kind": kind, "event_id": event_id, "call_id": call_id}
    base.update(payload)
    return base


def build_turn_completed(
    *,
    call_id: str,
    event_id: str,
    turn_idx: int,
    stt_final_ms: int | None,
    llm_first_token_ms: int | None,
    tts_first_chunk_ms: int | None,
    total_turn_ms: int,
    used_intro_cache: bool,
) -> dict[str, Any]:
    return build_event(
        "turn.completed",
        call_id=call_id,
        event_id=event_id,
        turn_idx=turn_idx,
        stt_final_ms=stt_final_ms,
        llm_first_token_ms=llm_first_token_ms,
        tts_first_chunk_ms=tts_first_chunk_ms,
        total_turn_ms=total_turn_ms,
        used_intro_cache=used_intro_cache,
    )
