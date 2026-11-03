# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Multi-tenant outbound AI voice agent ("Priya") that phones leads in English/Hindi/Tamil, qualifies them, scores them Hot/Warm/Cold, and streams everything into a Supabase-backed CRM. Originally built for SPC (petrochemicals), now pivoted to real-estate brokers. `../ai_voice` is an older copy of this repo; don't edit it.

## Layout (pnpm + turbo monorepo, plus one Python app)

- `apps/pipecat-agent/` — **Python** voice agent (FastAPI + Pipecat). Telephony via Exotel WebSocket (`exotel_ws_handler.py`), Sarvam STT, LLM (Gemini primary when `LLM_PRIMARY=gemini`, Groq/OpenAI-compatible fallback in `groq_llm.py`), TTS selected by `TTS_PROVIDER` (Sarvam Bulbul / Smallest / Cartesia / ElevenLabs). `local_audio.py` is a mic/speaker harness that runs the same orchestrator without a phone. Writes calls, transcripts, turn latencies and qualification slots to Supabase via `supabase_client.py` (REST, service-role key).
- `apps/web/` — Next.js 14 App Router CRM (leads, campaigns, credits, settings). Reads Supabase with the user's JWT, so RLS does tenant isolation.
- `apps/workers/*` — Cloudflare Workers (Hono): `campaigns` (dispatcher; enforces `daily_spend_cap_inr` via the `tenant_spend_today()` RPC), `score` (post-call LLM scoring), `handoff` (WhatsApp/email), `webhooks`, `clicktocall`.
- `packages/db/` — Supabase project: `supabase/migrations/` is the **only** source of schema truth; `supabase/seed.sql` creates tenant SPC + login `admin@spc.test` / `demo-password-change-me`; `supabase/tests/` holds pgTAP RLS tests; `supabase/queries/asql_showcase.sql` holds analytics queries.
- `packages/shared/` — TS shared code (phone normalization, CSV import, scoring schema, prompts in `src/prompts/`).
- `infra/supabase/SETUP.sql` — hand-maintained one-paste version of all migrations for a hosted project's SQL editor. **When you add a migration, fold it into SETUP.sql too.**

## Database model (key cross-file facts)

- Every tenant-scoped table has RLS keyed on `public.current_tenant_id()`, which reads `tenant_id` from the JWT. The claim is injected by `public.custom_access_token_hook` (enabled in `config.toml` locally; on hosted Supabase it must be enabled by hand under Auth → Hooks). Child tables without `tenant_id` (`transcripts`, `call_events`, `lead_scores`, `handoffs`) scope through an `EXISTS` join to `calls`/`leads`.
- Billing: the `calls_compute_billed_units` trigger derives `billed_units` from `duration_sec` (≤150s=1, ≤300=2, ≤450=3, else 4). It must stay in sync with `CallContext.billed_units()` in `apps/pipecat-agent/src/voice_agent/pipeline.py`. `estimated_cost_inr` is written by `cost_guard.py`; the trigger falls back to ₹12/unit (`PROJECTED_UNIT_COST_INR` in `apps/workers/campaigns/src/dispatch.ts`).
- `transcripts`, `calls`, `lead_scores` are in the `supabase_realtime` publication; the CRM live view depends on that.

## Commands

```powershell
pnpm install
pnpm dev                     # all JS apps (web on :3000)
pnpm test | pnpm typecheck | pnpm lint
pnpm --filter @ai-voice/campaigns-worker test     # one workspace
pnpm --filter @ai-voice/web exec vitest run path/to/file.test.ts

# Local Supabase (Docker Desktop must be running). API :54321, DB :54322, Studio :54323
pnpm db:start                # = supabase start --workdir packages/db (CLI via npx supabase if not installed)
pnpm db:reset                # re-apply migrations + seed.sql
pnpm --filter @ai-voice/db test:rls
pnpm db:gen-types

# Python agent (from apps/pipecat-agent; pytest.ini sets pythonpath=src)
python -m pytest -q
python -m pytest tests/test_pipeline.py::test_billed_units_match_al_cred_billing
python -m voice_agent.local_audio --lang hi-IN --lead-name Suresh   # talk to Priya via mic
.\run-server.ps1             # FastAPI on :8080; refuses to start if ../ai_voice's voice_agent shadows this one
```

Root `seed-remote*.js` scripts fill a database with demo CRM data: `DATABASE_URL=... node seed-remote-ultimate.js`. **They delete all `+91…` leads of the first tenant first**, so never point them at a database with real leads.

## Gotchas

- Secrets live in `apps/pipecat-agent/.env` and `apps/web/.env.local` (gitignored). Never hardcode connection strings; the seed scripts read `DATABASE_URL`.
- `tenant_config.get_tenant()` currently has a DEMO-DAY OVERRIDE that returns the broker tenant for every id.
- Windows dev box: set `PYTHONIOENCODING=utf-8` when printing Hindi/Tamil text from Python scripts.
