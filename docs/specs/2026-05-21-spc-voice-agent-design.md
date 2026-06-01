# SPC Voice Agent — Design Spec

**Date:** 2026-05-21
**Status:** Approved for implementation planning
**Author:** brainstormed with Claude Code
**First customer:** Supreme Petrochemicals (SPC), Chennai — https://www.supremepetrochemicals.com/
**Productization:** Multi-tenant SaaS from day one; SPC is tenant #1.

---

## 1. Problem statement

SPC is a 29-year-old Chennai-based industrial chemicals distributor: 250+ products across 18 industries (pharma, paints, water treatment, adhesives, etc.), bulk supply, 4-hour quote SLA, ISO 9001:2015 / drug-licence / FSSAI certified, 33 supplier partnerships. Their growth bottleneck is outbound lead qualification: dialing prospects, finding the right procurement contact, learning what chemicals they buy, scoring fit, and routing the hot ones to a human sales rep — at scale, in the language the prospect prefers.

We are building a productized voice-AI agent that:

1. Places **real outbound phone calls** to a list of leads.
2. Conducts a **human-sounding qualification conversation up to 3 minutes** (target 90–180s; shorter is fine if the lead is clearly cold or clearly hot) in **English, Hindi, or Tamil**, auto-switching to whichever the prospect speaks.
3. **Logs everything** (transcript, recording, extracted fields, score, summary) into a multi-tenant CRM we own and operate.
4. **Classifies** each lead as Hot / Warm / Cold with a 0–100 conversion-probability score, and stores a one-paragraph **AI summary** of the call for the human rep.
5. **Hands off Hot leads** to human reps via WhatsApp with summary + transcript link, AND surfaces a one-click **"Call this lead now"** button in the CRM so the rep can immediately convert the lead with full conversation context already on screen.

The same product, with a per-tenant persona / KB / script, is sold to other companies after the SPC reference deal.

## 2. Scope

**In scope (v1 — the demo)**
- One tenant pre-seeded (SPC) with Priya persona and SPC's product catalogue.
- CSV upload + single-lead manual entry of leads.
- Outbound dialing via Sarvam Samvaad → Exotel telephony.
- 8-step qualification flow with auto-language switch EN/HI/TA, ≤3-minute cap.
- Real-time transcript streaming to dashboard.
- Post-call AI scoring (Hot/Warm/Cold + 0–100 + structured extracted fields + paragraph summary).
- WhatsApp handoff via `wa.me` deeplink with pre-filled summary.
- **One-click human-takeover from CRM**: rep opens a Hot lead, sees AI summary + transcript + extracted fields, clicks "Call now" → outbound dial from the rep's own phone (`tel:` link on mobile) or via Exotel click-to-call API (desktop).
- Multi-tenant data model with Supabase RLS isolation.

**Out of scope (v1)**
- Inbound calls / IVR.
- WhatsApp Business API automation (the demo uses `wa.me` deeplinks; WABA is a paid upgrade later).
- Two-way sync with external CRMs (HubSpot/Zoho) — webhook export is a v2 feature.
- A/B testing different scripts.
- Voice cloning of a real SPC sales rep — using Sarvam's stock voice gallery in v1.
- Analytics beyond per-call view + per-campaign aggregate counts.

## 3. Stack & infra decisions (locked)

| Layer | Choice | Reason |
|---|---|---|
| Frontend | Next.js on **Cloudflare Pages** | Free for commercial use, unlimited bandwidth, Chennai+Mumbai PoP, $5/mo upgrade path |
| DB + Auth + Realtime + Storage | **Supabase** (free tier) | Best-in-class RLS for multi-tenant; pgvector available if we add KB search later; upgrade to Pro $25/mo at scale |
| API / Webhook handlers | **Cloudflare Workers** | Zero cold-start (matters for Samvaad webhooks), 100k req/day free, $5/mo to 10M |
| Recordings + transcript files | **Cloudflare R2** | 10GB free, **zero egress fees** — critical because call audio compounds fast |
| Voice agent (demo) | **Sarvam Samvaad** | Turnkey platform: Saaras STT + Bulbul TTS + LLM + telephony glue + DLT compliance + 11 Indian languages, sub-500ms latency. ₹1,000 free credits cover demo. |
| Telephony | **Exotel** (via Samvaad's native integration) | Indian-native, DLT-compliant, ₹0.65–1.20/min outbound mobile |
| Handoff (v1) | **wa.me deeplinks + Resend email** | Free; upgrade to AiSensy WABA when client wants automation |
| Hosting region | India (CF: Mumbai/Chennai; Supabase: `ap-south-1`) | Low latency for SPC operators and webhook round-trips |

**Total fixed monthly cost to operate the demo: ₹0.** Only variable per-call cost (see §10).

**Upgrade path:** If Samvaad's per-minute platform fee compresses margins at scale, swap the voice layer to **raw Sarvam APIs + self-hosted Pipecat on a Hetzner CX22 (€4/mo)**. Our CRM/scoring/handoff code does not change — it's behind a `VoiceProvider` interface (see §6).

## 4. Locked decisions (from brainstorming round)

| # | Decision | Locked value |
|---|---|---|
| D1 | Demo target | Live outbound call to a real Indian mobile number |
| D2 | Build path | Sarvam Samvaad turnkey + our own CRM layer |
| D3 | CRM | Build on Supabase + Next.js (we own it) |
| D4 | Qualification flow | 8-step BANT-style, ≤120s hard stop |
| D5 | Lead source | CSV upload from dashboard + manual entry |
| D6 | Demo callees | User's own phone + friendly testers first; real prospects only after SPC sign-off |
| D7 | AI persona | "Priya" — female, warm, mid-20s, Chennai-accented English, fluent HI + TA, auto-switches to whichever language the prospect uses |
| D8 | Multi-tenant | Yes, from day 1; SPC = tenant #1 |
| D9 | Hot-lead handoff | WhatsApp (`wa.me` link with pre-filled summary) |
| D10 | Infra | Cloudflare Pages + Workers + R2 + Supabase (Vercel rejected for non-commercial free tier) |

## 5. Architecture

```
                          ┌──────────────────────────────────────┐
                          │  CRM Dashboard (Next.js / CF Pages)  │
                          │  - Upload CSV / add lead             │
                          │  - Start campaign                    │
                          │  - View leads, transcript, score     │
                          │  - Assign Hot leads to rep           │
                          └────────────────┬─────────────────────┘
                                           │  HTTPS (Supabase JS client + fetch)
                                           ▼
   ┌─────────────────────┐      ┌──────────────────────────────┐      ┌────────────────────────┐
   │   Supabase          │◄────►│  Cloudflare Workers (API)    │─────►│  Sarvam Samvaad        │
   │   Postgres + Auth   │      │  /api/leads/import           │      │  - Exotel telephony    │
   │   RLS multi-tenant  │      │  /api/campaigns/start        │      │  - Saaras STT          │
   │   Realtime          │      │  /webhooks/samvaad           │      │  - Bulbul TTS (Priya)  │
   └─────────────────────┘      │  /api/score                  │      │  - Sarvam LLM          │
                                │  /api/handoff/whatsapp       │      │  - Lang auto-switch    │
                                └──────────┬───────────────────┘      └─────────┬──────────────┘
                                           │                                    │
                                           ▼                                    │  webhook events
                                  ┌────────────────────┐                        │
                                  │  Cloudflare R2     │                        │
                                  │  - call recordings │◄───────────────────────┘
                                  │  - long transcripts│
                                  │  zero egress       │
                                  └────────────────────┘
```

**Boundary rule:** Samvaad owns the hard real-time stuff (turn-taking, barge-in, STT/TTS, telephony, DLT compliance). We own everything that drives differentiation and recurring revenue: the data, the script, the scoring, the handoff, the dashboards.

## 6. Components

### 6.1 Web dashboard (`apps/web`)
Next.js 14+ App Router, deployed to Cloudflare Pages via `@opennextjs/cloudflare` adapter. Pages:
- `/login` — Supabase Auth
- `/leads` — list + filter + CSV upload + manual add
- `/leads/[id]` — lead detail: AI summary at top, transcript (realtime, bilingual rendering with translations on hover), recording player, extracted fields, classification + score with reason, prominent **"Call now"** button (mobile → `tel:` link prefilled; desktop → Exotel click-to-call), action buttons (Mark DNC, Reassign rep, Manual WhatsApp handoff, Add note)
- `/campaigns` — list + start new
- `/campaigns/[id]` — running campaign with live counters
- `/settings` — tenant settings (persona name, agent ID, default language, caller-ID)

Constrained to features supported by OpenNext for Cloudflare (server components OK; pre-flight any non-supported APIs).

### 6.2 API workers (`apps/workers`)
Cloudflare Workers, one Worker per route group:
- `leads-worker` — CSV parse + validate + insert; phone E.164 normalization
- `campaigns-worker` — dispatcher: pulls queued leads, calls Samvaad agent API, throttles, writes `calls` rows
- `webhooks-worker` — receives Samvaad webhook events, idempotent on `samvaad_call_id` + `event_id`
- `score-worker` — triggered on `call.ended`, fetches transcript, calls Sarvam LLM with scoring prompt, validates JSON, writes `lead_scores`
- `handoff-worker` — generates wa.me link + Resend email, writes `handoffs`
- `clicktocall-worker` — initiates rep-to-lead bridge via Exotel `connect_two_numbers` API on demand from CRM; logs as a `calls` row with `kind='human_followup'`

### 6.3 Shared packages (`packages/`)
- `db/` — Supabase migrations, generated TS types, RLS policies
- `shared/` — Zod schemas (lead, transcript, score), conversation prompt templates, scoring rubric, voice-provider interface

### 6.4 VoiceProvider interface
The voice layer is behind an interface so we can swap Samvaad → custom Pipecat later without rewriting CRM code:

```ts
interface VoiceProvider {
  startCall(opts: { lead: Lead; agentId: string; langHint?: Lang }): Promise<{ providerCallId: string }>;
  parseWebhook(req: Request): Promise<VoiceEvent>;  // normalize events
  fetchRecording(providerCallId: string): Promise<ReadableStream>;
}
```
v1 implementation: `SamvaadProvider`. Future: `PipecatProvider`.

### 6.5 Samvaad agent config (`infra/samvaad/`)
A versioned JSON file per tenant describing the persona, system prompt, KB snippets (SPC's 250 products + 18 industries + value-prop bullets), the 8 qualification steps, language behavior, and hard limits (120s cap, do-not-call rules).

## 7. Data flow — one call, end-to-end

1. Operator uploads CSV → `leads-worker` validates and inserts rows.
2. Operator clicks **Start campaign** → `campaigns-worker` enqueues N leads, throttled to Samvaad rate limit.
3. For each lead, worker calls `Samvaad.startCall({ phone, lead_id, tenant_id, lang_hint })`.
4. Samvaad dials via Exotel, plays Priya intro in `lang_hint`, runs the 8-step flow, auto-switches language on first user reply.
5. Samvaad streams webhooks → `webhooks-worker`:
    - `call.started` → `calls.status = 'ringing'`
    - `call.answered` → `calls.status = 'in_progress'`, set `started_at`
    - `transcript.chunk` → append row to `transcripts` (Supabase realtime fans this to the dashboard)
    - `call.ended` → set `ended_at`, `duration_sec`, `status`
    - `recording.ready` → fetch audio, store in R2, write `calls.recording_r2_key`
6. On `call.ended` the worker enqueues a scoring job → `score-worker`:
    - fetches full transcript text
    - calls Sarvam LLM with scoring prompt
    - validates JSON output against Zod schema (retry once on failure, else mark `needs_review`)
    - writes `lead_scores` and updates `leads.status` to hot|warm|cold|do_not_call
7. If classification = `hot`, `handoff-worker` generates wa.me link + Resend email and writes `handoffs`.
8. Dashboard subscribes to Supabase realtime on `lead_scores` and `transcripts`, so the operator sees the lead light up Hot the instant scoring lands.

## 8. Data model (Supabase, multi-tenant via RLS)

```sql
-- All business tables carry tenant_id; RLS policy: tenant_id = jwt claim.

tenants(
  id uuid pk,
  name text,
  slug text unique,
  persona_name text,                 -- e.g. 'Priya'
  persona_lang_default text,         -- 'en-IN' | 'hi-IN' | 'ta-IN'
  samvaad_agent_id text,
  exotel_caller_id text,
  whatsapp_handoff_number text,      -- rep's number for wa.me links
  created_at timestamptz default now()
)

users(
  id uuid pk references auth.users,  -- Supabase Auth
  tenant_id uuid references tenants,
  email text,
  full_name text,
  role text check (role in ('admin','rep')),
  whatsapp text,
  created_at timestamptz
)

leads(
  id uuid pk,
  tenant_id uuid references tenants,
  name text,
  phone_e164 text,
  company text,
  industry text,
  source text,
  notes text,
  status text check (status in
    ('new','queued','calling','called','hot','warm','cold','do_not_call','needs_review')),
  assigned_to uuid references users,
  created_at timestamptz,
  unique (tenant_id, phone_e164)
)

campaigns(
  id uuid pk,
  tenant_id uuid references tenants,
  name text,
  script_version int,
  created_by uuid references users,
  started_at timestamptz,
  completed_at timestamptz
)

calls(
  id uuid pk,
  tenant_id uuid references tenants,
  lead_id uuid references leads,
  campaign_id uuid references campaigns,
  samvaad_call_id text unique,
  status text,                          -- ringing|in_progress|completed|failed|voicemail
  started_at timestamptz,
  ended_at timestamptz,
  duration_sec int,
  language_used text,
  recording_r2_key text,
  created_at timestamptz
)

call_events(
  id uuid pk,
  call_id uuid references calls,
  kind text,                            -- raw event name
  payload jsonb,
  occurred_at timestamptz
)

transcripts(
  id uuid pk,
  call_id uuid references calls,
  speaker text check (speaker in ('agent','lead')),
  text text,
  lang text,
  ts_ms int,
  idx int
)

lead_scores(
  id uuid pk,
  lead_id uuid references leads,
  call_id uuid references calls,
  classification text check (classification in ('hot','warm','cold')),
  score_0_100 int check (score_0_100 between 0 and 100),
  reason text,
  extracted jsonb,   -- {decision_maker, industry, chemicals[], volume, supplier_pain, timeline}
  scored_at timestamptz
)

handoffs(
  id uuid pk,
  lead_id uuid references leads,
  call_id uuid references calls,
  channel text check (channel in ('whatsapp','email')),
  sent_to text,
  sent_at timestamptz,
  opened_at timestamptz
)

dnc_list(
  tenant_id uuid,
  phone_e164 text,
  reason text,
  added_at timestamptz,
  primary key (tenant_id, phone_e164)
)
```

**RLS policy template applied to every business table:**
```sql
create policy tenant_isolation on <table>
  using (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);
```

The `tenant_id` claim is set during sign-in via a Supabase Auth Hook that reads `users.tenant_id`.

## 9. Conversation design

### 9.1 Persona (SPC)
- Name: **Priya**, 26, polite-confident, Chennai-accented English, fluent Hindi + Tamil.
- Voice: stock voice from Sarvam Bulbul gallery to be selected during M3.
- Demeanor: warm, never pushy, uses small fillers ("right", "okay", "achha"), respects "no" instantly.

### 9.2 The 8-step flow (≤3-minute hard cap)
1. **Intro (5s)** — Personalized greeting using the lead's first name (passed via `campaigns-worker` metadata):
   - EN: "Hello Ravi, this is Priya from Supreme Petrochemicals, Chennai. Is this a good time for a quick 30-second conversation?"
   - HI: "Namaste Ravi ji, main Priya hoon Supreme Petrochemicals Chennai se. Kya aap 30 second baat kar sakte hain?"
   - TA: "Vanakkam Ravi avargale, naan Priya, Supreme Petrochemicals Chennai-il irundhu. Ungalukku oru nimisham nerum unda?"
   - Fallback (name unavailable/placeholder): omit the name and start with "Namaste, this is Priya from Supreme Petrochemicals..."
2. **Right person?** — Procurement decision-maker?
3. **Industry fit** — What does the company manufacture? Maps to SPC's 18 sectors.
4. **Need fit** — Which chemicals do they currently source? Cross-checks SPC's 250-product catalogue.
5. **Volume + frequency** — Bulk monthly tonnage or small lots? (SPC's edge is bulk.)
6. **Pain with current supplier** — Pricing, delivery, quality?
7. **Decision timeline** — In-market now / 1–3 months / just exploring?
8. **Soft close** — "Can we send you a quote within 4 hours for [X]?" + capture preferred contact time and email/WhatsApp.

**Pacing:** Target 90–180 seconds. Hard cap at **180 seconds** — if Priya is still talking at 170s she wraps with a soft close and ends. Cold leads can end as early as 15–30s on a "not interested." Hot leads with engaged prospects can use the full 3 minutes for richer extraction.

### 9.3 Language behavior
- Start in `persona_lang_default` (English for SPC).
- After the first user reply, detect language and switch. Priya can switch mid-conversation if the user does.
- If detection is ambiguous after the first reply, Priya offers: *"Should we continue in English, Hindi, or Tamil?"*

### 9.4 Guardrails
- Never invent products or prices. If asked something out of scope: *"Let me have a specialist call you back within four hours."*
- Hard stop at 180 seconds (3 minutes).
- Respect "not interested" / "do not call" immediately → `do_not_call` + `dnc_list` insert.
- Voicemail → hang up, retry once 4 hours later.
- Forbidden topics: politics, religion, anything off-product.

### 9.5 Scoring rubric (post-call)
LLM is given the full transcript and asked to return JSON matching this Zod schema:
```ts
{
  decision_maker: boolean,
  industry: string | null,
  chemicals: string[],            // matched against SPC catalogue
  monthly_volume_kg: number | null,
  current_supplier: string | null,
  supplier_pain: ('price'|'delivery'|'quality'|'support'|'none')[],
  timeline: 'now' | '1-3mo' | 'exploring' | 'unknown',
  decision_maker_email: string | null,
  decision_maker_whatsapp: string | null,
  classification: 'hot' | 'warm' | 'cold',
  score_0_100: number,
  reason: string,                  // one-liner classification reason
  summary: string,                 // 2-4 sentence call summary for the human rep
  next_action: string,             // recommended human follow-up step
  call_quality_flags: ('voicemail'|'wrong_number'|'language_struggle'|'audio_poor'|'none')[]
}
```
Heuristic (encoded in prompt, not code, to allow tuning):
- **Hot** = decision-maker AND (timeline=now OR timeline=1-3mo) AND (volume fits bulk OR supplier_pain != none).
- **Cold** = "not interested" / wrong number / not decision-maker with no referral path.
- **Warm** = everything else.

**English normalization rule (locked):** Regardless of the call language (EN/HI/TA, possibly mixed), the scoring LLM **always emits `summary`, `reason`, `next_action`, `industry`, `current_supplier`, `chemicals[]`, `supplier_pain[]`, `timeline`, `classification`, `call_quality_flags[]` in English**. Original-language phrases are preserved verbatim in the `transcripts` table for fidelity, but every CRM-facing field is uniformly English so any rep can read any lead. This is enforced in the prompt and double-checked in code by rejecting any response containing Devanagari (`[ऀ-ॿ]`) or Tamil (`[஀-௿]`) script in those fields and forcing a retry → `needs_review`.

## 10. Cost model

### 10.1 Per-call cost — at three call-length scenarios

Costs scale roughly linearly with call duration. Real distribution will be a mix.

| Component (per call) | 60s (cold drop-off) | 90s (typical) | 180s (full 3-min, hot lead) |
|---|---|---|---|
| Saaras STT (₹0.50/min) | ₹0.50 | ₹0.75 | ₹1.50 |
| Bulbul TTS (~₹20/10k chars × ~5 chars/sec) | ₹0.60 | ₹0.90 | ₹1.80 |
| Sarvam LLM (turns scale w/ duration) | ₹0.30 | ₹0.50 | ₹1.00 |
| Exotel outbound mobile (₹1.20/min) | ₹1.20 | ₹1.80 | ₹3.60 |
| Samvaad platform fee (₹2–5/min est.) | ₹2–5 | ₹3–7 | ₹6–15 |
| Post-call scoring LLM (one-shot) | ₹0.50 | ₹0.50 | ₹0.80 |
| **Total per call** | **₹5–8** | **₹6.5–11** | **₹15–24** |

Blended average across a realistic mix (40% cold drop, 40% typical, 20% hot full 3-min): **~₹9–13 per call**.

### 10.1a Samvaad platform fee — concrete clarification

Sarvam's public pricing page lists the foundation-model APIs (Saaras STT ₹30/hr, Bulbul TTS ₹15–30/10k chars, Sarvam LLM per-token). Samvaad (the orchestration platform) is published as having tiers from ₹0 → ₹50,000 with ₹1,000 free credits, but a precise per-minute platform fee is not on the website at time of writing. The estimates above (₹2–5/min) are conservative based on comparable Indian voice-AI platforms; the design intentionally exposes Samvaad behind the `VoiceProvider` interface so that if the actual fee is materially higher, we swap to **raw Sarvam APIs + self-hosted Pipecat** (gross per-call drops to ₹5–8 even for a 3-min call) without touching CRM code.

**Action item for M3:** confirm exact Samvaad pricing at signup and revise this section.

### 10.2 Per month (variable component, blended ₹9–13/call)
| Volume | Monthly call cost | Fixed infra cost |
|---|---|---|
| 100 calls (demo) | ₹900–1,300 | ₹0 (free tiers) |
| 1,000 calls | ₹9,000–13,000 | ₹0 |
| 10,000 calls | ₹90,000–1.3L | ~₹2,000 (Supabase Pro + CF Workers Paid) |
| 100,000 calls | ₹9L–13L | ~₹10,000 + Pipecat swap likely worth it |

### 10.3 Worth-the-upgrade decision points
- **Supabase Pro ($25/mo)** when DB > 500MB or we need PITR backups — for a paying client.
- **Cloudflare Workers Paid ($5/mo)** when webhook traffic > 100k/day.
- **WhatsApp Business API (~₹2k/mo)** when a client wants two-way automated handoff instead of wa.me links.
- **Swap Samvaad → raw Sarvam APIs + Pipecat on Hetzner (€4/mo)** when monthly call volume > 20k AND Samvaad platform fee compresses unit economics — only if the per-call savings clear ₹15k/mo, i.e. real ROI.

## 11. Error handling

| Scenario | Behavior |
|---|---|
| Lead hangs up < 3s | `cold`, no score, no handoff |
| Voicemail detected | Hang up; retry once 4 hours later; if voicemail again → `cold` |
| Wrong language on turn 1 | Priya offers the trilingual prompt explicitly |
| Samvaad webhook dropped | Idempotent handler keyed by `(samvaad_call_id, event_id)`; periodic reconciliation job catches gaps |
| DLT block | Surface clearly in dashboard; fallback caller-ID config per tenant |
| Scoring LLM returns invalid JSON | Retry once; on second failure mark `needs_review` and notify admin |
| Same lead dialed twice in same day | Rejected by `unique(tenant_id, phone_e164, dial_date)` partial index; surfaced to operator |
| DNC violation attempt | Hard-blocked before dial; logged as audit event |

## 12. Testing strategy

### 12.1 Unit
- Phone normalization to E.164 (Indian mobile edge cases: 10-digit, +91-prefixed, 0-prefixed, spaces).
- CSV parser: header detection, malformed rows, duplicate phones (within file and against existing leads), max-rows guard (10,000).
- Scoring rubric on **20 hand-labeled golden transcripts** (5 hot, 7 warm, 8 cold) — Vitest snapshot tests; classification must match label; score within ±10.
- Zod schema validation of scoring output (rejects extra keys, missing keys, wrong types).
- RLS policies: SQL tests that confirm tenant A cannot read tenant B's leads/calls/transcripts.

### 12.2 Integration
- Webhook handler replays a recorded Samvaad event stream from fixtures and verifies DB state at each step.
- Idempotency: replay the same `(call_id, event_id)` twice → exactly one row inserted.
- Out-of-order events: `call.ended` arriving before `transcript.chunk` → final state still consistent.
- Scoring worker against a mocked LLM that returns malformed JSON → retry once then `needs_review`.
- Click-to-call worker against an Exotel sandbox call → bridge initiated, `calls` row written with `kind='human_followup'`.

### 12.3 End-to-end (the demo gate)
Before the SPC pitch, run six scripted self-calls and capture all to a demo recording:
1. **EN happy path** — engaged decision-maker, full 3-min flow → Hot, score ≥80, WhatsApp ping arrives.
2. **HI happy path** — Priya auto-switches on second turn → Hot.
3. **TA happy path** — same, in Tamil.
4. **Cold drop** — say "not interested" at 15s → call ends, `cold`, `dnc_list` insert.
5. **Voicemail** — let call go to VM → detected, hung up, retry scheduled.
6. **Click-to-call from CRM** — open a Hot lead, click Call now → rep's phone rings, bridges to lead's phone.

### 12.4 Load smoke
Dispatch a 50-call campaign to a sink number to validate Workers concurrency, webhook ordering, Supabase write throughput, and the realtime fan-out to the dashboard.

### 12.5 Manual quality gates before pitching SPC
- Listen to all 6 demo recordings: Priya sounds human, no robotic cadence, no obvious Sarvam-default-voice red flags.
- Transcript ↔ recording match check: spot-check 10 random utterances.
- Scoring rubric on 10 real test calls: human grader agrees with classification ≥8/10.
- Latency: first Priya word audible within 1.5s of pickup; turn-taking gap ≤700ms.

## 13. Build phases

| Milestone | Days | Deliverable |
|---|---|---|
| M1 | 1 | Repo scaffolded; Cloudflare Pages + Supabase project; multi-tenant schema migrated; SPC tenant seeded; auth working |
| M2 | 1 | CSV upload + leads CRUD + dashboard list view |
| M3 | 2 | Samvaad signup; Priya agent configured with SPC KB; Exotel KYC kicked off; first end-to-end test call from dashboard → user's phone; webhooks landing |
| M4 | 1–2 | Scoring worker + Hot/Warm/Cold + WhatsApp handoff + transcript realtime + recording playback |
| M5 | 1 | Polish, demo script for SPC pitch, cost dashboard, deploy production URL |

Total: **5–7 calendar days** for a working, demoable system on the user's own phone.

## 14. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Samvaad platform fee too high at scale | Medium | VoiceProvider abstraction; fallback to raw Sarvam APIs + Pipecat |
| Exotel KYC / DLT delay | Medium | Start KYC on day 1 of M3; Samvaad's bundled telephony as backup |
| Sarvam TTS mispronounces chemical names | Medium | Bulbul pronunciation dictionary; pre-record critical terms |
| 90-sec budget too short for genuine qualification | Low | Tunable in agent config; calibrate during M3 |
| SPC won't share lead list pre-demo | Low | Demo on user's number + 3 friendly testers — locked |
| OpenNext-on-Cloudflare missing a Next feature we use | Low | Constrain to supported features; document gotchas |
| Tamil/Hindi STT misses chemical terms | Medium | Telephony-optimized Saaras + custom vocab; manual review queue for `needs_review` |

## 15. Open questions / TBDs

1. Confirm Sarvam Samvaad's actual per-minute platform fee during signup; revise §10 if materially different.
2. Choose the specific Bulbul voice for Priya during M3 (gallery preview with three SPC team members).
3. Decide WhatsApp handoff phone — single shared rep number or per-rep wa.me based on `users.whatsapp`. Default: per-rep.
4. Decide CSV column standard: name, phone, company, industry, notes, optional `assigned_to` email. Lock during M2.
5. Click-to-call: confirm whether Exotel's `connect_two_numbers` API is included in the Samvaad-bundled Exotel account or needs separate Exotel direct access. Mobile fallback (`tel:` link) works regardless.

## 16. Out-of-scope deferrals (v2+)

- Inbound calls + IVR.
- WhatsApp Business API two-way automation.
- HubSpot/Zoho one-way push integration.
- Script A/B testing.
- Self-serve onboarding (today: we provision tenants manually).
- Analytics: funnel, agent performance, language breakdown, sentiment trends.
- Voice cloning of real rep.
- Pipecat-based custom voice layer (only if §10 cost trigger fires).
