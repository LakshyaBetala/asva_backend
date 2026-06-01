"""Demo CLI: place one outbound call to your whitelisted mobile via Exotel.

Prereqs (one-time):
  1. FastAPI server running:  uvicorn voice_agent.server:app --host 0.0.0.0 --port 8080
  2. ngrok or Cloudflare Tunnel exposing port 8080 publicly:
        ngrok http 8080  →  https://<random>.ngrok-free.app
  3. EXOTEL_STREAM_URL in .env set to the WSS form of that URL:
        EXOTEL_STREAM_URL=wss://<random>.ngrok-free.app
  4. EXOTEL_DEMO_TO_NUMBER in .env = your whitelisted personal mobile.

Then:
  python -m voice_agent.demo_call
  python -m voice_agent.demo_call --to +918072116397 --lang hi-IN --lead-name Suresh

Your phone rings. Pick up. Priya greets you in the chosen language.
Speak. She responds. Hard cap 360s.
"""
from __future__ import annotations

import argparse
import asyncio
import os

import httpx


DEFAULT_BACKEND = "http://127.0.0.1:8080"


def _load_env() -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError:
        dotenv_values = None
    env: dict[str, str] = {}
    if dotenv_values:
        env.update({k: v for k, v in dotenv_values(".env").items() if v})
    env.update({k: v for k, v in os.environ.items() if v})
    return env


async def place(args: argparse.Namespace) -> None:
    env = _load_env()
    to = args.to or env.get("EXOTEL_DEMO_TO_NUMBER", "").strip()
    if not to:
        raise SystemExit(
            "No destination. Pass --to +91xxxxxxxxxx or set EXOTEL_DEMO_TO_NUMBER in .env."
        )

    payload = {
        "to": to,
        "lead_first_name": args.lead_name,
        "lead_company": args.lead_company,
        "lang_hint": args.lang,
        "lead_id": args.lead_id,
        "tenant_id": args.tenant_id,
    }

    print(f"\n→ Placing Exotel call to {to}  (lang={args.lang})")
    print(f"  backend: {args.backend}")
    print(f"  stream URL Exotel will hit: {env.get('EXOTEL_STREAM_URL', '<unset!>')}")

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(f"{args.backend}/exotel/calls", json=payload)

    print(f"\n← {resp.status_code} {resp.reason_phrase}")
    if resp.status_code >= 400:
        print(resp.text)
        raise SystemExit(1)

    body = resp.json()
    print(f"  call_sid:   {body['call_sid']}")
    print(f"  status:     {body['status']}")
    print(f"  stream_url: {body['stream_url']}")
    print("\nYour phone should ring within ~3 seconds. Pick up and talk to Priya.\n")


def main() -> None:
    p = argparse.ArgumentParser(prog="voice_agent.demo_call")
    p.add_argument("--to", help="E.164 destination, e.g. +918072116397")
    p.add_argument("--lang", default="hi-IN", choices=["hi-IN", "en-IN", "ta-IN"])
    p.add_argument("--lead-name", default="Suresh")
    p.add_argument("--lead-company", default="Acme Chemicals")
    p.add_argument("--lead-id", default=None, help="Defaults to a random id.")
    p.add_argument("--tenant-id", default="demo-tenant")
    p.add_argument("--backend", default=DEFAULT_BACKEND, help="FastAPI base URL.")
    args = p.parse_args()
    if not args.lead_id:
        args.lead_id = f"demo-{os.urandom(4).hex()}"
    asyncio.run(place(args))


if __name__ == "__main__":
    main()
