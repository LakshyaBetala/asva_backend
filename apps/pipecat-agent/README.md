# voice-agent (Pipecat)

Outbound voice agent for Supreme Petrochemicals. Speaks English, Hindi,
Tamil; auto-detects and switches mid-call via the deliberate language
state machine (not naive auto-detect).

## Stack

- **STT**: Sarvam Saaras v3 (WebSocket streaming, per-utterance lang tag)
- **LLM**: Google Gemini 2.5 Flash (sub-300ms TTFT, free tier 1500/day)
- **TTS**: Sarvam Bulbul v3 (streaming, single Chennai-accent voice across 3 langs)
- **SIP**: Plivo (managed) or BYON (Exotel/Plivo/Tata via tenant config)
- **Orchestrator**: Pipecat
- **Webhooks out**: HMAC-SHA256 signed events to `webhooks-worker`

## Layout

```
src/voice_agent/
  language_state.py   # The heart — deliberate language-switch logic
  prompts.py          # Loads priya-system.md, injects <current_language>
  intro_cache.py      # R2 reader for pre-cached intro phrases
  webhook.py          # HMAC-signed event emitter
  pipeline.py         # Pipecat assembly: STT -> LLM -> TTS
  server.py           # FastAPI control plane (start/stop calls)
tests/
  test_language_state.py
  test_webhook.py
  test_intro_cache.py
```

## Run locally (smoke tests)

```bash
cd apps/pipecat-agent
pip install -e ".[dev]"
pytest -v
```

## Deploy to Hetzner CX22

```bash
docker build -t voice-agent .
docker run -p 8080:8080 --env-file .env voice-agent
```

## Why a language state machine (not naive auto-detect)?

Naive STT-auto-detect-then-respond fails on Indian calls. A single
"haan" mis-flips the agent's language for the rest of the turn. Our
state machine requires 2 consecutive full-utterances in the new
language OR an explicit code-switch trigger phrase before flipping —
plus a smooth bridge phrase on transition. See `language_state.py`.
