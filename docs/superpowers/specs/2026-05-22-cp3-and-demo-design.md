# CP3 + SPC Live Demo — Design Spec

**Date:** 2026-05-22
**Status:** Approved (sections 1–5)
**Author:** Laksh + Claude (brainstorming session, post-CP2)
**Implements:** Production-ready outbound voice agent for SPC live demo this week + per-tenant rollout from client #2.

---

## 1. Goal & non-negotiables

Outbound-only voice agent ("Priya") that calls SPC's lead list in Hindi / English / Tamil, holds a real qualifying conversation, and writes a scored lead (Hot/Warm/Cold) with extracted slot data back to the CRM. Incoming calls are handled manually by SPC staff — not in scope.

**Non-negotiable build gates (ship-blockers):**

| Gate | Enforcement |
|---|---|
| P95 turn latency <1.5s | Measured on 50 supervised test calls before SPC demo. |
| Real human sound | Blind A/B with 5 non-technical listeners. >2/5 must NOT identify Priya as AI. |
| Smart responses | 20 golden fixtures pass + manual review of 50 real-call transcripts. |
| Right language | Language state machine (20 unit tests) + 10 bilingual real calls. |
| No regression | All 51 Py + 132 TS tests stay green. |

If a gate fails, the build does not ship. No exceptions.

---

## 2. Pricing & billing model

| | Client #1 (SPC) | Client #2+ |
|---|---|---|
| Setup (one-time) | ₹75,000 | ₹1,00,000 |
| Monthly subscription | ₹15,000 | ₹20,000 |
| Monthly call allowance | 2,000 | 2,000 |
| Wiggle room (free) | 10% (200 bonus calls) | 10% (200 bonus calls) |
| Per-call overage rate (past wiggle) | ₹10/call | ₹12/call |

**Billing unit = `calls.billed_units`, not raw call count.**
- 0–180s call → 1 unit
- 181–360s call → 2 units
- Hard cap 360s

**Stored in `calls` table as `billed_units` column (computed on call end).** Tenant's monthly counter sums `billed_units`, not row count. CRM displays "units used / allowance".

**Why dual-billing:** A converting conversation must never be cut at 180s. Allowing organic extension to 360s with double billing aligns incentives — the agent only "earns" a second unit when the client got value worth keeping the call alive.

---

## 3. Cost economics

**Per-unit (180s) cost stack at realistic call mix:**

| Component | Cost per 180s |
|---|---|
| Sarvam Saaras STT (streaming) | ~₹3.00 |
| Sarvam Bulbul TTS | ~₹3.00 |
| Gemini 2.5 Flash (with caching) | ~₹0.40 |
| Plivo outbound SIP | ~₹1.80 |
| Infra amortized | ~₹0.20 |
| **Raw per-unit** | **~₹8.40** |

**Mitigations applied in CP3 (drop to ~₹4.30/unit weighted average):**

1. Phrase cache (top-100 Priya acks / closings pre-synthesized to R2) → -25% TTS
2. Ack clips (200ms pre-recorded "haan/achha/theek hai" played without LLM round-trip) → -10% TTS
3. Realistic mix (30% <30s hangups + 50% short qualifiers + 20% full conversations) → -45% weighted

**Per-client P&L (Year 1, SPC):**
```
Revenue:          2000 × ₹7.50          = ₹15,000
Variable cost:    2000 × ₹4.30          = ₹ 8,600
Setup amort:      ₹75,000 / 12          = ₹ 6,250
─────────────────────────────────────────────────
Y1 net per client per month:              ₹12,650  (≈84% Y1 margin)
```

**Per-client P&L (Year 1, clients #2+):**
```
Revenue:          2000 × ₹10.00         = ₹20,000
Variable cost:    2000 × ₹4.30          = ₹ 8,600
Setup amort:      ₹1,00,000 / 12        = ₹ 8,333
─────────────────────────────────────────────────
Y1 net:                                   ₹13,067  (≈65% Y1 margin)
```

**Cost guardrails (ship in CP3 — non-negotiable):**

| Guardrail | Implementation |
|---|---|
| Daily spend cap per tenant | `tenant_daily_spend_inr` row + dispatcher checks before each call. Halt dispatch if projected_today > cap. Default ₹600/day. |
| Runaway call kill switch | Hard terminate any call at 360s + 10s grace via watchdog in `pipeline.py`. |
| Per-call cost telemetry | `calls.estimated_cost_inr` column written at call end from `turn_latencies` aggregation. |
| Sarvam credit balance check | Daily cron worker hits Sarvam balance API, alerts at <20% remaining. |

---

## 4. Conversation architecture

### 4.1 Phase machine

New file: `apps/pipecat-agent/src/voice_agent/conversation_state.py`

```python
class Phase(str, Enum):
    GREETING  = "greeting"   # 0-8s   cached Hindi intro
    CONNECT   = "connect"    # 8-35s  rapport, no questions about products
    DISCOVER  = "discover"   # 35-70s pain-hypothesis floated, slots start filling
    QUALIFY   = "qualify"    # 70-150s 8-slot extraction interleaved with value statements
    CLOSE     = "close"      # 150-180s commit-question based on score-in-progress
    EXTENSION = "extension"  # 180-360s only if buying signals strong at 170s
```

**Phase transitions** are computed each turn from elapsed time + slot fill state + buying_confidence score. EXTENSION only entered if `buying_confidence ≥ 0.6` at the 170s soft-close moment.

### 4.2 The 8 qualification slots

Filled live per turn by a slot-extraction LLM call (parallel to the main response LLM call). Persisted to new `qualification_slots` table.

| Slot | Type | Notes |
|---|---|---|
| `product_interest` | string | Must intersect SPC catalog terms |
| `volume_monthly` | int (kg) | <50kg → soft cold |
| `buying_frequency` | enum {one_off, monthly, ad_hoc, unknown} | |
| `current_supplier` | string\|null | Named competitor boosts score |
| `pain_point` | string\|null | Extracted from open-ended response |
| `decision_role` | enum {owner, procurement, engineer, assistant, unknown} | |
| `timeline_days` | int\|null | <30 + Hot path |
| `buying_confidence` | float [0,1] | LLM-inferred from tone + commit words |

### 4.3 Scoring rule (live, per turn)

```
HOT  if buying_confidence ≥ 0.7 AND timeline_days ≤ 30
        AND decision_role ∈ {owner, procurement}
        AND product_interest ∈ SPC_CATALOG
WARM if buying_confidence ≥ 0.5
        AND (timeline_days ≤ 60 OR current_supplier ≠ null)
        AND product_interest ∈ SPC_CATALOG
COLD otherwise
```

Score is recomputed every turn. CRM lead row updates via Supabase realtime so the demo screen shows the bar shifting live.

### 4.4 Pain library

New file: `apps/pipecat-agent/src/voice_agent/pain_library.py`

Pre-written pain hypotheses per product category, language-localized:

```python
PAIN_HYPOTHESES = {
    "solvents": {
        "hi-IN": [
            "Aksar distributors ke saath payment cycle 45-60 din ho jaata hai...",
            "Quality consistency mein dikkat aati hai monsoon mein...",
            "Delivery delays Diwali season mein common hai...",
        ],
        "en-IN": [...],
        "ta-IN": [...],
    },
    "polymers": {...},
    "acids": {...},
    ...
}
```

Priya selects one matching the lead's stated business in CONNECT phase and floats it as a hypothesis in DISCOVER phase.

### 4.5 Anti-AI sound enforcement

**Encoded as enforced behaviors, not soft prompt hints:**

| Behavior | Implementation |
|---|---|
| Acknowledgment variation | `ConversationState.used_acks: set[str]`. System prompt receives "Already used: [haan, theek hai]". LLM must pick different. |
| Filler injection | Prompt directive + min 1 filler per 3 turns. Enforced via post-turn audit; if missing 3+ turns straight, inject. |
| Self-repetition prevention | Last 4 Priya turns kept verbatim in context with rule "Do not paraphrase your own recent turns." |
| Sentence length variation | Prompt: "Vary sentence length. Alternate short (3-6 words) and long (12-20 words)." |
| Single voice across languages | Sarvam Bulbul Chennai female pinned for all 3 languages. No voice swap on language flip. |
| Single retry on confusion | If STT confidence <0.6 twice consecutive: paraphrase the question differently, then move on. Never loop. |

---

## 5. CP3 build scope (Half A — my work)

| # | File | Purpose | Tests |
|---|---|---|---|
| 1 | `apps/pipecat-agent/src/voice_agent/conversation_state.py` | Phase machine + ack tracker + filler audit | 15 |
| 2 | `apps/pipecat-agent/src/voice_agent/qualification.py` | Per-turn slot extractor (Gemini structured-output call) | 12 |
| 3 | `apps/pipecat-agent/src/voice_agent/pain_library.py` | Pain hypothesis lookup per product × language | 8 |
| 4 | `apps/pipecat-agent/src/voice_agent/phrase_cache.py` | Top-100 phrase cache (extends intro_cache pattern) | 6 |
| 5 | `apps/pipecat-agent/src/voice_agent/cost_guard.py` | Daily spend cap, runaway watchdog, cost telemetry writer | 8 |
| 6 | `packages/db/supabase/migrations/20260522180000_qualification_slots.sql` | 8-slot table with RLS | — |
| 7 | `packages/db/supabase/migrations/20260522180100_billed_units.sql` | `calls.billed_units` + `calls.estimated_cost_inr` columns | — |
| 8 | `packages/db/supabase/migrations/20260522180200_tenant_overage.sql` | `tenants.overage_policy`, `tenants.monthly_units_used` rollup view | — |
| 9 | `apps/workers/score/src/score-live.ts` | `POST /score-live` worker invoked each turn by agent | 6 |
| 10 | `apps/workers/campaigns/src/dispatch.ts` | Add daily-spend-cap check before dispatching each call | 4 |
| 11 | `packages/shared/src/prompts/priya-system.md` | Anti-AI sound rules + phase directives | — |
| 12 | `apps/pipecat-agent/src/voice_agent/pipeline.py` | Update HARD_CAP=360, soft-close 170/350, EXTENSION gating | 6 (existing updated) |
| 13 | CRM polish (next sub-section) | | — |

**Estimated dev time:** 6–8 hours focused work. Aim for one commit per file group, push at end of CP3.

### 5.1 CRM polish (no redesign, polish only)

| Page | Change |
|---|---|
| `/leads` | Live status pill + inline score bar (red/amber/green) updating via Supabase realtime. |
| `/leads/[id]` | New "Qualification" panel showing 8 slot values + buying_confidence. Audio player + transcript with phrase highlights. |
| `/campaigns` | "Units remaining: X / 2,000" widget. Live progress ticker. |
| `/settings` | New "Performance" tab (ROI calculator) + "Overage Policy" toggle + tenant `avg_order_size_inr` setting. |
| Global | Top-bar quota indicator visible on every page. |

No new pages. No design system changes. shadcn components only.

### 5.2 Overage UX (the "how do we tell the customer" answer)

| % used | UI state | Notification |
|---|---|---|
| 0–80% | Green badge | None |
| 80–90% | Amber badge | Email + dashboard banner |
| 90–100% | Amber badge | Daily email reminders |
| 100–110% (free wiggle) | Blue badge "Bonus active" | Email at first overage call |
| >110% | Red badge with running total | Email + dashboard banner; honors `tenants.overage_policy` (`continue_billed` default vs `hard_pause`) |

---

## 6. CP3 Half B — credentials sign-up checklist (user task, in parallel)

Order matters (later steps need earlier ones):

| # | Service | Why | Time | Cost |
|---|---|---|---|---|
| 1 | Google AI Studio | Gemini 2.5 Flash key | 5 min | Free for demo volume |
| 2 | Sarvam AI | Saaras STT + Bulbul TTS | 10 min | ~₹500 trial credit |
| 3 | Supabase | Hosted Postgres + Auth (Mumbai region) | 10 min | Free tier |
| 4 | Cloudflare | Workers + R2 for intro/phrase cache | 15 min | Free tier |
| 5 | Plivo | Indian DID + SIP outbound | 30 min + 24–48hr KYC | $10 trial then ₹0.60/min |
| 6 | Hetzner CX22 or Railway | Pipecat container host | 15 min | ~₹350/mo |

**Demo fallback if Plivo KYC slips past demo day:** Live CRM + recorded sample call (Sarvam+Gemini loop without SIP). Loses the "phone ringing in the room" moment; keeps everything else.

---

## 7. Demo flow (SPC live, this week)

```
T+0:00  Open CRM in browser. Show clean dashboard with 247 leads.
T+0:30  Upload SPC's pre-loaded lead CSV. New leads appear.
T+1:00  Click "Start Campaign" — 3 leads queued for outbound.
T+1:30  First call dials. Your phone rings (you hold it on speakerphone).
        Priya greets in Hindi. The recipient (friendly volunteer) responds.
T+2:00  Point to CRM screen:
        • Live transcript scrolling
        • 8-slot qualification panel filling in
        • Score bar shifting grey → amber → green
T+3:00  Call ends. Lead shows as Hot/Warm/Cold with reasoning surfaced.
T+4:00  Open Settings → Performance tab. Show ROI math.
T+5:00  Walk through Settings → BYON: "Next phase, your trunk plugs in here."
T+5:30  Q&A.
```

---

## 8. Day-by-day execution plan

| Day | Claude | User |
|---|---|---|
| 1 (today) | CP3 Half A: conversation_state, qualification, pain_library, phrase_cache, migrations, cost_guard, CRM polish. Push CP3 commit. | Start signups: Google AI, Sarvam, Supabase, Cloudflare. |
| 2 | Pipeline real-audio glue + Plivo SIP transport. Push CP4 commit. | Plivo KYC, Hetzner setup, drop keys into .env. |
| 3 | First end-to-end test call from your machine. Iterate on prompts based on what you hear. | Be the lead on test calls. Note where Priya sounds robotic. |
| 4 | 10 supervised calls with friendly contacts (varied languages). Lock prompts. Tune scoring thresholds. | Same. |
| 5 | Buffer / rehearsal / SPC demo. | SPC demo. |

---

## 9. Out of scope for CP3

Listed explicitly so we don't drift:

- BYON Vault credential resolver (deferred to CP5; demo uses managed mode with user's number)
- DLT template registration (deferred; SPC's own DLT entity used for production rollout)
- Incoming call handling (manual by SPC staff, never automated)
- Sarvam B2B contract negotiation (deferred until 3 paying clients)
- Self-hosted Whisper STT (deferred; only if Sarvam negotiation fails)
- Multi-region hosting (single Mumbai region only)
- Mobile CRM app (web-only)
- AI-generated outreach scripts (deferred; current playbook lives in priya-system.md)

---

## 10. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Plivo KYC slips past demo day | Medium | Demo fallback: recorded sample + live CRM |
| Sarvam free credit exhausts mid-test | Medium | Top up ₹2k upfront; monitor balance daily |
| P95 latency >1.5s on real telco audio | Medium | Day 3 testing surfaces this; can fall back to non-streaming TTS for first turns |
| Anti-AI sound A/B fails (>2/5 detect) | Medium | Iterate prompts on Day 4; worst case demo with disclosed AI framing |
| Lead score logic too sticky (everyone Warm) | Medium | Tune thresholds on Day 3 real calls; thresholds are config not code |
| CRM realtime stream lags during demo | Low | Pre-rehearse; backup is page refresh between calls |

---

## 11. Success criteria for demo day

- [ ] Live outbound call placed from CRM, audible by SPC
- [ ] Priya speaks Hindi greeting + adapts to recipient's language
- [ ] Recipient does not unprompted say "this is a robot"
- [ ] CRM shows live transcript + score updating
- [ ] Lead persisted as Hot/Warm/Cold with reasoning
- [ ] Settings → Performance ROI math shown
- [ ] All 4 cost guardrails visible in code & DB
- [ ] No latency complaint from SPC during the call
