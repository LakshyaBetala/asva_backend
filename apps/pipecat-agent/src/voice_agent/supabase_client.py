"""Agent-side Supabase client for persisting call data.

The voice agent writes to Supabase after each turn:
  - qualification_slots (upsert — idempotent on call_id)
  - turn_latencies (insert — one row per turn)
  - transcripts (insert — lead + priya lines per turn)
  - calls (update — duration_sec, status, billed_units)

Uses the service_role JWT so RLS doesn't block agent writes. The agent
is an internal trusted service, not an end-user.

Writes are fire-and-forget (asyncio.create_task) so they never block
the audio loop. A failed DB write must NEVER crash or slow a live call.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(s: str | None) -> bool:
    """Gate every persist call — calls.id is a uuid column, so passing the
    agent's internal log handle ('call-1e4b...') triggers 22P02 on every
    POST. Better to silently no-op than to spam errors."""
    return bool(s) and bool(_UUID_RE.match(s))


@dataclass
class SupabaseConfig:
    url: str  # e.g. https://rcbvdxyehtwhzgajzdlj.supabase.co
    service_role_key: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SupabaseConfig":
        e = env or os.environ
        url = (
            e.get("SUPABASE_URL")
            or e.get("NEXT_PUBLIC_SUPABASE_URL")
            or ""
        ).rstrip("/")
        key = (
            e.get("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        )
        if not url or not key:
            raise SupabaseConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set"
            )
        return cls(url=url, service_role_key=key)


class SupabaseConfigError(RuntimeError):
    pass


class AgentSupabaseClient:
    """Thin async wrapper around Supabase REST API (PostgREST).

    Each method returns None on success, raises on unexpected failure.
    All methods are safe to call from asyncio.create_task — they swallow
    transient errors and log instead of raising.
    """

    def __init__(self, config: SupabaseConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self._cfg = config
        self._http = client or httpx.AsyncClient(timeout=10.0)
        self._headers = {
            "apikey": config.service_role_key,
            "Authorization": f"Bearer {config.service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def _url(self, table: str) -> str:
        return f"{self._cfg.url}/rest/v1/{table}"

    async def _post(self, table: str, payload: dict[str, Any]) -> None:
        resp = await self._http.post(
            self._url(table), json=payload, headers=self._headers
        )
        if resp.status_code >= 400:
            logger.error("supabase POST %s failed %d: %s", table, resp.status_code, resp.text[:200])

    async def _upsert(self, table: str, payload: dict[str, Any], on_conflict: str) -> None:
        headers = {**self._headers, "Prefer": "return=minimal,resolution=merge-duplicates"}
        resp = await self._http.post(
            self._url(table), json=payload, headers=headers,
            params={"on_conflict": on_conflict},
        )
        if resp.status_code >= 400:
            logger.error("supabase UPSERT %s failed %d: %s", table, resp.status_code, resp.text[:200])

    async def _patch(self, table: str, filters: dict[str, str], payload: dict[str, Any]) -> None:
        params = {f"{k}": f"eq.{v}" for k, v in filters.items()}
        resp = await self._http.patch(
            self._url(table), json=payload, headers=self._headers, params=params,
        )
        if resp.status_code >= 400:
            logger.error("supabase PATCH %s failed %d: %s", table, resp.status_code, resp.text[:200])

    # -- Public methods -------------------------------------------------------

    async def upsert_qualification_slots(
        self, *, call_id: str, tenant_id: str, lead_id: str,
        slots_row: dict[str, Any],
    ) -> None:
        payload = {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            **slots_row,
        }
        await self._upsert("qualification_slots", payload, on_conflict="call_id")

    async def insert_turn_latency(
        self, *, call_id: str, tenant_id: str, turn_idx: int,
        stt_ms: int | None = None, llm_ms: int | None = None,
        tts_ms: int | None = None, total_ms: int = 0,
        used_intro_cache: bool = False,
    ) -> None:
        await self._post("turn_latencies", {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "turn_idx": turn_idx,
            "stt_final_ms": stt_ms,
            "llm_first_token_ms": llm_ms,
            "tts_first_chunk_ms": tts_ms,
            "total_turn_ms": total_ms,
            "used_intro_cache": used_intro_cache,
        })

    async def insert_transcript(
        self, *, call_id: str, speaker: str, text: str,
        lang: str | None = None, turn_idx: int = 0,
    ) -> None:
        db_speaker = "agent" if speaker == "priya" else speaker
        await self._post("transcripts", {
            "call_id": call_id,
            "speaker": db_speaker,
            "text": text,
            "lang": lang,
            "ts_ms": turn_idx * 10000,
            "idx": turn_idx,
        })

    async def update_call_status(
        self, *, call_id: str, status: str,
        duration_sec: float | None = None,
        billed_units: int | None = None,
        turns: int | None = None,
        tenant_id: str | None = None,
    ) -> None:
        if not _is_uuid(call_id):
            return
        payload: dict[str, Any] = {"status": status}
        if duration_sec is not None:
            payload["duration_sec"] = int(duration_sec)
        if billed_units is not None:
            # al_cred billing: max 4 creds per call (150-sec blocks; hard cap 600s).
            payload["billed_units"] = min(billed_units, 4)
        if status == "completed":
            payload["ended_at"] = datetime.now(timezone.utc).isoformat()
        await self._patch("calls", {"id": call_id}, payload)

    async def insert_call(
        self, *, call_id: str, tenant_id: str, lead_id: str,
        lang: str = "hi-IN",
    ) -> None:
        if not (_is_uuid(call_id) and _is_uuid(lead_id) and _is_uuid(tenant_id)):
            return
        await self._post("calls", {
            "id": call_id,
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "status": "in_progress",
            "kind": "ai_outbound",
            "language_used": lang,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })


    async def insert_lead_score(
        self, *, lead_id: str, call_id: str,
        classification: str, score: int,
        reason: str, summary: str,
        next_action: str | None = None,
        extracted: dict | None = None,
    ) -> None:
        if not (_is_uuid(call_id) and _is_uuid(lead_id)):
            return
        import json as _json
        await self._post("lead_scores", {
            "lead_id": lead_id,
            "call_id": call_id,
            "classification": classification,
            "score_0_100": score,
            "reason": reason,
            "summary": summary,
            "next_action": next_action or "",
            "extracted": _json.dumps(extracted or {}),
            "call_quality_flags": "{}",
        })


# -- Fire-and-forget helpers ------------------------------------------------
# The orchestrator calls these; they wrap in create_task so the audio
# loop never blocks on DB latency.

def persist_turn_async(
    db: AgentSupabaseClient | None,
    *,
    call_id: str,
    tenant_id: str,
    lead_id: str,
    turn_idx: int,
    lead_text: str,
    lead_lang: str,
    priya_text: str,
    slots_row: dict[str, Any],
    latency: dict[str, int],
    used_intro_cache: bool = False,
) -> None:
    """Schedule all per-turn DB writes. Safe to call with db=None (no-op).
    Also no-ops if call_id is not a real UUID — the agent supports trial
    calls without a backing leads row, and those would otherwise spam 22P02
    errors on every turn."""
    if db is None:
        return
    if not _is_uuid(call_id):
        return

    async def _run() -> None:
        try:
            await asyncio.gather(
                db.upsert_qualification_slots(
                    call_id=call_id, tenant_id=tenant_id, lead_id=lead_id,
                    slots_row=slots_row,
                ),
                db.insert_turn_latency(
                    call_id=call_id, tenant_id=tenant_id, turn_idx=turn_idx,
                    stt_ms=latency.get("stt_ms"),
                    llm_ms=latency.get("llm_ms"),
                    tts_ms=latency.get("tts_ms"),
                    total_ms=latency.get("total_ms", 0),
                    used_intro_cache=used_intro_cache,
                ),
                db.insert_transcript(
                    call_id=call_id, speaker="lead", text=lead_text,
                    lang=lead_lang, turn_idx=turn_idx,
                ),
                db.insert_transcript(
                    call_id=call_id, speaker="priya", text=priya_text,
                    lang=lead_lang, turn_idx=turn_idx,
                ),
            )
        except Exception:
            logger.exception("persist_turn_async failed for call_id=%s turn=%d", call_id, turn_idx)

    asyncio.create_task(_run())
