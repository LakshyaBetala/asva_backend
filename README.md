# AI Voice — Broker Lead Qualification Agent

A state-of-the-art, multi-tenant outbound AI Voice Calling Agent designed to streamline lead qualification and CRM integration. 

> **Background:** This platform was originally engineered for **SPC (Supreme Petrochemicals, Chennai)**, a prominent spectrochemical wholesale business, to handle their B2B lead qualification. It has since been strategically pivoted and optimized to serve **Brokers**, offering seamless, automated voice outreach and lead management.

## Key Features

- **Multilingual AI Voice:** Real-time outbound calls in **English, Hindi, or Tamil** powered by Sarvam Samvaad and Exotel telephony.
- **Conversational AI:** Engaging, human-sounding AI agent capable of completing complex qualification conversations in under 3 minutes.
- **Real-Time CRM Integration:** Live call transcripts streamed directly into a multi-tenant CRM built on Supabase and Cloudflare Pages.
- **Intelligent Scoring & Extraction:** Post-call LLM analysis to categorize leads (Hot/Warm/Cold), assign a 0–100 score, and generate an English-only summary, reason, next actions, and extracted fields—regardless of the language spoken during the call.
- **Automated Notifications:** Immediate alerts for "Hot" leads via WhatsApp and Resend email.
- **Seamless Human Handoff:** One-click human takeover capability on every lead via a mobile `tel:` link or desktop Exotel bridge.

## Documentation

- **Design Specification:** [`docs/specs/2026-05-21-spc-voice-agent-design.md`](docs/specs/2026-05-21-spc-voice-agent-design.md) *(Original SPC design)*
- **Implementation Plans:**
  - [`docs/plans/2026-05-21-plan-1-foundation-and-crm.md`](docs/plans/2026-05-21-plan-1-foundation-and-crm.md) — Repository, schema, and CRM setup
  - [`docs/plans/2026-05-21-plan-2-voice-agent.md`](docs/plans/2026-05-21-plan-2-voice-agent.md) — Voice agent integration and first real call
  - [`docs/plans/2026-05-21-plan-3-scoring-handoff-demo.md`](docs/plans/2026-05-21-plan-3-scoring-handoff-demo.md) — Scoring, human handoff, and demo

## Quickstart (Local Development)

```powershell
# Install dependencies
pnpm install

# Start Supabase locally (requires Docker Desktop running)
pnpm db:start

# Copy environment variables and paste the keys Supabase prints
# (e.g., copy .env.example -> .env.local)

# Start the development server
pnpm dev
```

*Dashboard will be available at [http://localhost:3000](http://localhost:3000)*

## Technology Stack

- **Frontend:** Next.js 14 (App Router) on Cloudflare Pages
- **Backend:** Cloudflare Workers (Hono) + Cloudflare R2 (for call recordings, with zero egress fees)
- **Database, Auth & Realtime:** Supabase (`ap-south-1`)
- **Voice Infrastructure:** Sarvam Samvaad (Saaras STT, Bulbul TTS, Sarvam LLM) paired with Exotel telephony
- **Email Delivery:** Resend
- **WhatsApp Integration:** `wa.me` deep links for demos, seamlessly upgradable to WhatsApp Business API
