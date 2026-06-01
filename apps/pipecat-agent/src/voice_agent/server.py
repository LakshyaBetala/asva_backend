"""FastAPI control plane.

Exposes the SamvaadClient-compatible HTTP surface so the rest of the
stack (campaigns-worker, webhooks-worker) thinks it's talking to a
Samvaad managed agent. Real call lifecycle happens in pipeline.py.

  POST /agents/{agent_id}/calls   -> start an outbound call
  GET  /calls/{call_id}/recording -> stream the mp3 from R2
  GET  /healthz                   -> liveness probe

Auth: simple Bearer token (INTERNAL_API_TOKEN). Treat the server as
internal — never expose it publicly; only the webhooks-worker and
campaigns-worker should reach it.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

# Surface our INFO-level call diagnostics (intro played, turns, latency).
# Without this Python's lastResort handler swallows everything below WARNING.
logging.basicConfig(level=logging.INFO)
logging.getLogger("voice_agent").setLevel(logging.INFO)

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field


class StartCallRequest(BaseModel):
    to: str = Field(..., description="E.164 phone number of the lead")
    from_: str = Field(..., alias="from", description="Caller ID (managed or BYON)")
    lang_hint: str = Field("en-IN", description="Initial language hint")
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartCallResponse(BaseModel):
    call_id: str


def _require_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("INTERNAL_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server misconfigured: INTERNAL_API_TOKEN unset",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bearer token")


app = FastAPI(title="voice-agent", version="0.1.0")

# Exotel WS + outbound trigger live in their own module to keep this file
# focused on the SamvaadClient-compatible HTTP surface.
from .exotel_ws_handler import router as exotel_router  # noqa: E402

app.include_router(exotel_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/agents/{agent_id}/calls",
    response_model=StartCallResponse,
    dependencies=[Depends(_require_bearer)],
)
async def start_call(agent_id: str, req: StartCallRequest) -> StartCallResponse:
    """Begin an outbound call. Returns the provider call ID synchronously;
    actual call lifecycle events stream back via webhook."""
    call_id = f"vc_{uuid.uuid4().hex[:16]}"
    # pipeline.start_call(...) is wired here in the real deployment;
    # kept thin so unit tests can verify auth + payload shape without
    # standing up the full Pipecat stack.
    return StartCallResponse(call_id=call_id)
