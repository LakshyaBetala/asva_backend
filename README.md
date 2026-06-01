# AI Voice — SPC Lead Qualification Agent

Multi-tenant outbound voice-AI calling agent. Tenant #1: Supreme Petrochemicals, Chennai.

- Real outbound calls in **English, Hindi, or Tamil** via Sarvam Samvaad + Exotel.
- ≤ 3-minute qualification conversation with a human-sounding agent ("Priya").
- Live transcript streamed into a multi-tenant CRM (Supabase + Cloudflare Pages).
- Post-call LLM scoring → Hot/Warm/Cold + 0–100 score + **English-only summary, reason, next-action, extracted fields** (regardless of call language).
- Hot leads notified via WhatsApp + Resend email.
- **One-click human takeover** on every lead — mobile `tel:` link or desktop Exotel bridge.

## Documentation

- **Design spec:** [`docs/specs/2026-05-21-spc-voice-agent-design.md`](docs/specs/2026-05-21-spc-voice-agent-design.md)
- **Implementation plans (3 milestones):**
  - [`docs/plans/2026-05-21-plan-1-foundation-and-crm.md`](docs/plans/2026-05-21-plan-1-foundation-and-crm.md) — repo, schema, CRM
  - [`docs/plans/2026-05-21-plan-2-voice-agent.md`](docs/plans/2026-05-21-plan-2-voice-agent.md) — voice agent + first real call
  - [`docs/plans/2026-05-21-plan-3-scoring-handoff-demo.md`](docs/plans/2026-05-21-plan-3-scoring-handoff-demo.md) — scoring + handoff + demo

## Quickstart (local dev)

```powershell
pnpm install
# Start Supabase locally (requires Docker Desktop running):
pnpm db:start
# Copy .env.example -> .env.local and paste the keys Supabase prints.
pnpm dev
# Dashboard at http://localhost:3000
```

## Stack

- Frontend: Next.js 14 (App Router) on Cloudflare Pages
- Backend: Cloudflare Workers (Hono) + Cloudflare R2 (recordings, zero egress)
- DB + Auth + Realtime: Supabase (`ap-south-1`)
- Voice: Sarvam Samvaad (Saaras STT + Bulbul TTS + Sarvam LLM + Exotel telephony)
- Email: Resend
- WhatsApp: `wa.me` deeplinks for demo, WhatsApp Business API on upgrade
