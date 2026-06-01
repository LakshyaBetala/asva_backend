# Pricing & Plan — AI Voice Agent

> Locked offer, cost model, margin analysis, quality feasibility, and
> talk track for the lighthouse customer: Supreme Petrochemicals (SPC),
> Chennai. Numbers in INR unless stated otherwise.

---

## TL;DR — the offer

| Item | Amount |
|---|---:|
| One-time setup (charged at contract sign) | **₹1,00,000** |
| Monthly subscription (billed monthly, annual contract) | **₹15,000** |
| **al_creds included per month** | **2,000 creds** |
| Overage above 2,000 al_creds/mo | **₹10/cred** |
| Per-number DID rental (we provision + manage) | **₹500/month/number** included |
| **Year 1 total** (setup + 12 × ₹15k) | **₹2,80,000** |
| **Year 2+ annual** (12 × ₹15k) | **₹1,80,000** |
| Annual contract term | 12 months, auto-renew |
| Cancel anytime after Month 1 | 30-day notice, no penalty |

### al_cred billing model (REGISTERED 2026-06)

1 al_cred = up to 150 seconds of call time. Creds ceiling-round per call:

| Call duration | al_creds billed |
|---|---:|
| 0 – 150 s   | **1 cred** |
| 151 – 300 s | **2 creds** |
| 301 – 450 s | **3 creds** |
| 451 – 600 s | **4 creds** |

**Hard cap: 600 s (10 min)** — calls are auto-cut at this point. 4 creds is the maximum any single call can consume. This is enforced in `pipeline.py` (HARD_CAP_SECONDS=600) and the Exotel REST call time-limit so a runaway never burns more than 4 creds against the customer.

Soft-close nudges fire at 140s, 290s, 440s, 580s so the LLM has a window to wrap before each cred ticks over.

**Target customer profile:** B2B Indian SME or mid-market doing
outbound sales / lead-qualification calls in volumes of 30–80/day.
SPC fits perfectly at 50 calls/day.

---

## What SPC actually gets for ₹15k/month

Tangible, demoable deliverables:

1. **Priya** — a custom-tuned AI sales agent voice (chosen from
   Sarvam Bulbul v3's gallery; 30+ Indian voices to pick from).
2. **All 3 priority Indian languages from day one**:
   English, Hindi, Tamil. Priya auto-detects and switches on every
   turn — no manual setting, no awkward transitions.
3. **Up to 2,000 outbound calls/month**, billed flat. That's 90+
   calls a day with full weekends off — well above SPC's 50/day
   target. No usage anxiety.
4. **Live CRM dashboard** at a branded URL:
   - Upload lead lists via CSV or add one at a time
   - Click "Call with AI" on any lead → Priya dials within ~3 sec
   - Realtime transcript pane as the call happens
   - English-normalized AI summary + 0–100 conversion score after
     each call ends (~30 sec wait)
   - Lead status: Hot / Warm / Cold / Do Not Call / Needs Review
   - Extracted fields: decision-maker, chemicals discussed, monthly
     volume, current supplier, supplier pain, decision timeline,
     email/WhatsApp
5. **Hot-lead handoff to human reps**:
   - WhatsApp message with summary and a deeplink back to the lead
   - Email backup via Resend
   - Rep opens the lead → sees the AI summary + transcript + all
     extracted fields
   - One-click **Call now** button: on mobile it's a `tel:` link;
     on desktop it bridges via Exotel two-leg call so the rep's
     phone rings, then connects to the lead
6. **Agent ON/OFF master switch** — one toggle in /settings pauses
   all outbound dialing (for audits, holidays, ramp-down)
7. **Multi-rep dashboard** with role-based access (admin vs rep)
   and per-rep WhatsApp assignment for Hot leads
8. **BYON (Bring Your Own Number) option** — plug your existing
   Exotel/Plivo SID into Settings and we route every call through
   your trunk instead of ours. Lower telephony bills, you keep
   carrier relationship; subscription unchanged.
9. **Call recordings** stored in Cloudflare R2 (zero egress fees);
   replay any call from the lead detail page
10. **DNC list management** — instant respect for "do not call",
    persistent across all future campaigns

What is included in **Setup (₹1L one-time)**:

- Picking Priya's exact voice from Sarvam Bulbul gallery (live A/B
  with your team)
- Loading your full **250-product catalogue** into the agent's KB
- Tuning the sales playbook for SPC's 18 industries
- Drafting and registering the **TRAI DLT templates** in EN/HI/TA
- **50 supervised test calls** before go-live (your team listens,
  we tune)
- 6-scenario E2E demo (live, recorded, kept for your reference)
- 2-rep onboarding session (90 minutes)
- Cloudflare + Supabase + Sarvam + Exotel/Plivo account provisioning
  on your behalf (or your own accounts if preferred)

---

## Usage assumption (the contract floor)

| Parameter | Value |
|---|---:|
| Calls per day | 50 |
| Working days per year (incl. major holidays) | 260 |
| Total calls per year | **13,000** |
| Average call duration | 150 sec (2.5 min) |
| Total talk-time per year | 32,500 min (~542 hr) |
| Hot rate (industry benchmark) | 10–15% |
| Hot leads per year | ~1,300–1,950 |

Calls per month average: ~1,100. Well under the 2,000/mo cap, so
**no overage expected** at SPC's projected volume.

---

## Tech stack (no-compromise, locked)

| Layer | Choice | Rationale |
|---|---|---|
| Voice loop orchestration | **Pipecat (Python)** self-hosted on Hetzner CX22 (€4.50/mo) | Open-source, proven sub-700ms turn-taking, no per-minute platform tax. Same architecture Bolna and many YC voice startups run. |
| STT | **Sarvam Saaras v3** WebSocket streaming | Best-in-class Indian-language ASR, telephony-optimized, native code-mixing support |
| LLM (conversation) | **Google Gemini 2.5 Flash** | Free tier 1,500 req/day; paid is ~₹0.30/call; sub-300ms TTFT |
| TTS | **Sarvam Bulbul v3** streaming + intro caching | Best Indian-voice prosody. Pre-cache fixed intro per language → ~30% TTS cost cut |
| Telephony | **Plivo SIP outbound** (managed) or **BYON** (Exotel / Plivo / Tata) | India-native, DLT-friendly, ₹0.65–1.20/min. Twilio explicitly avoided — 2–3× cost for India |
| CRM frontend | **Next.js on Cloudflare Pages** | Free commercial-use tier, Mumbai+Chennai PoP |
| Database + Auth | **Supabase** Postgres + Auth (free tier → Pro $25/mo at scale) | RLS multi-tenancy, realtime fan-out for transcripts |
| Webhooks / API | **Cloudflare Workers** (Hono) | Zero cold-start; 100k req/day free |
| Recordings | **Cloudflare R2** | Zero egress fees |
| Scoring + email | **Gemini Flash + Resend** | English-normalized summaries; free tier covers SPC volume |
| Handoff | **wa.me deeplink** (no WhatsApp Business API needed for v1) | Free; upgrade to WABA only when client asks |

**Latency budget** (target sub-800ms turn-taking):

```
End of lead speech → first audible Priya word
   80 ms   VAD detects end of utterance
   30 ms   Network: phone → Plivo → our orchestrator
  200 ms   Sarvam Saaras WebSocket final transcript
  250 ms   Gemini 2.5 Flash time-to-first-token
  200 ms   Sarvam Bulbul TTS first audio chunk
   80 ms   Network: orchestrator → Plivo → phone
─────────
  840 ms   typical
  ~650 ms  when Priya is using a cached intro phrase
```

This matches every "premium" Indian voice agent on the market today.
We don't sacrifice quality to hit our margin.

---

## Cost model — per al_cred (REFRESHED 2026-06)

Live stack: Sarvam Saaras STT + Groq Llama-4-Scout (conversation LLM, with
Gemini fallback) + Sarvam Bulbul v3 for Tamil OR smallest.ai Lightning v3.1
for Hindi/English + Exotel @ ₹0.60/min + Gemini Flash post-call scoring (free
tier covers SPC volume; GPT-4.1-Mini was evaluated and rejected — no free tier,
$5 starter credits expire in 3 months, and conversation latency hit was too high).

A 150-second call (1 al_cred). Two TTS lanes because routing is per-language:

| Component | Tamil-only (Sarvam Bulbul) | Hi/En (smallest.ai) |
|---|---:|---:|
| Sarvam Saaras STT (₹0.50/min × 2.5) | ₹1.25 | ₹1.25 |
| TTS (₹2/min Sarvam ta, ₹0.30/cred smallest.ai cached) | ₹2.60 | ₹0.75 |
| Groq Llama-4-Scout (~5k tok @ $0.05/$0.25 per M) | ₹0.06 | ₹0.06 |
| Exotel outbound (₹0.60/min × 2.5) | ₹1.50 | ₹1.50 |
| Gemini Flash post-call scoring | ₹0.10 | ₹0.10 |
| **Per-cred variable** | **₹5.51** | **₹3.66** |
| + DID rental (₹500/mo / typical 1,100 creds used) | +₹0.45 | +₹0.45 |
| + VPS + misc fixed (₹650/mo / typical creds) | +₹0.30 | +₹0.30 |
| **Per-cred all-in** | **₹6.26** | **₹4.41** |

BYON (client's own Exotel) drops the ₹1.50/cred telephony line entirely:
- Tamil-only: **₹4.01/cred variable, ₹4.76 all-in**
- Hi/En: **₹2.16/cred variable, ₹2.91 all-in**

Note: longer calls bill more creds, so per-cred cost stays roughly constant. A
600s call costs us ~4× the per-cred variable (~₹22 Tamil / ~₹14.50 Hi-En) and
bills 4 creds × ₹7.50 = ₹30 to the customer — the cred ceiling protects margin.

---

## Worst-case margin — by language mix, full al_cred utilisation

₹15,000 / 2000 al_creds = **₹7.50/cred** customer price. If a customer
saturates all 2000 creds in a month:

| Scenario (managed, Exotel ₹0.60/min) | Cost (variable) | Fixed (DID+VPS) | Total cost | Profit | **Margin** |
|---|---:|---:|---:|---:|---:|
| 100% Tamil (Sarvam Bulbul) | ₹11,020 | ₹1,150 | ₹12,170 | ₹2,830 | **18.9%** |
| 70% Tamil / 30% Hi-En blend | ₹9,910 | ₹1,150 | ₹11,060 | ₹3,940 | **26.3%** |
| 100% Hi/En (smallest.ai) | ₹7,320 | ₹1,150 | ₹8,470 | ₹6,530 | **43.5%** |
| Negotiated Exotel ₹0.45/min, 100% Tamil | ₹10,420 | ₹1,150 | ₹11,570 | ₹3,430 | **22.9%** |
| Negotiated Exotel ₹0.45/min, 70/30 blend | ₹9,400 | ₹1,150 | ₹10,550 | ₹4,450 | **29.7%** |
| BYON, 100% Tamil | ₹8,020 | ₹1,150 | ₹9,170 | ₹5,830 | **38.9%** |
| BYON, 100% Hi/En | ₹4,320 | ₹1,150 | ₹5,470 | ₹9,530 | **63.5%** |

**Realistic (typical 1,100 al_creds actually used, 70/30 Tamil blend, Exotel ₹0.60):**
- Variable: 1,100 × ₹4.96 = ₹5,456
- Fixed: ₹1,150
- Total cost: ₹6,606
- **Margin: 56%**

### Conclusions

- **Tamil-only managed mode at full saturation is the danger zone (~19%)**. Any cost shock — Sarvam TTS rate hike, Exotel hike — pushes us underwater. Mitigations: (1) push BYON for Tamil-heavy buyers; (2) negotiate Exotel down to ₹0.45/min; (3) deeper R2 phrase caching to cut Sarvam TTS by 30%.
- **Typical SPC-shaped usage (~1,100 creds, blended) is healthy at 56%**.
- **BYON is always the high-margin variant** (38-63%) — for customers procurement-led on price, default the offer to BYON.
- **GPT-4.1-Mini summary swap declined**: no free tier (only $5 promotional credits expire in 90 days at $0.40/$1.60 per M tok). Sticking with Gemini Flash for post-call scoring (1,500 free req/day covers ~50 calls/day for free).

## Cost model — annual

13,000 calls/yr × per-call cost above:

| Cost bucket | Managed | BYON |
|---|---:|---:|
| Per-call variable (13k × per-call) | ₹60,450 | ₹34,450 |
| Hetzner CX22 VPS (Pipecat orchestrator) | ₹4,800 | ₹4,800 |
| Supabase free tier | ₹0 | ₹0 |
| Cloudflare Pages + Workers + R2 free tier | ₹0 | ₹0 |
| Resend free tier (3k email/mo, far above need) | ₹0 | ₹0 |
| Domain + misc + 10% buffer | ₹3,000 | ₹3,000 |
| **Total Year-2+ ops cost** | **₹68,250** | **₹42,250** |
| Year-1 add-on: setup engineering (3 days @ ₹15k/day) | +₹45,000 | +₹45,000 |
| **Total Year-1 cost** | **₹1,13,250** | **₹87,250** |

---

## Margin analysis

| Year | SPC pays | Cost (managed) | Cost (BYON) | Margin (managed) | Margin (BYON) |
|---|---:|---:|---:|---:|---:|
| Year 1 | ₹2,80,000 | ₹1,13,250 | ₹87,250 | **₹1,66,750 (60%)** | **₹1,92,750 (69%)** |
| Year 2 | ₹1,80,000 | ₹83,250 | ₹57,250 | **₹96,750 (54%)** | **₹1,22,750 (68%)** |
| Year 3 | ₹1,80,000 | ₹83,250 | ₹57,250 | **₹96,750 (54%)** | **₹1,22,750 (68%)** |
| **3-year cumulative** | **₹6,40,000** | **₹2,79,750** | **₹2,01,750** | **₹3,60,250 (56%)** | **₹4,38,250 (68%)** |

(Year 2+ cost includes ₹15k/yr light AMC engineering for KB updates and platform upgrades.)

**Healthy by every standard:**
- Year-2+ gross margin ≥ 54% on managed mode
- Year-2+ gross margin ≥ 68% on BYON mode
- Break-even on the contract within Month 8 of Year 1
- Customer Acquisition Cost (CAC) for the first deal is your time;
  the unit economics let you reinvest in pipeline from Month 9 onward

---

## Feasibility check — "genuine, honest, all Indian languages"

A point-by-point honest answer. **This section was rewritten after a
self-critique pass to remove over-promising language.**

### 1. "Doesn't feel like talking to AI" — honest version

**Feasibility: HIGH for the first 30-60 seconds. MEDIUM for the full 3 minutes.**

No voice agent on the market today — not Vapi, not Bland, not Sarvam
Samvaad, not us — passes a 3-minute Turing test with an attentive
listener. Anyone telling SPC otherwise is selling. The honest
distribution:

| Call duration | % who can tell it's AI |
|---|---:|
| 15-second hello + first reply | 15–25% |
| 60-second opener with one qualifying question | 30–40% |
| 3-minute deep qualification | 60–75% |
| Listener explicitly checking for AI tells | ~95% |

**What we DO promise SPC:**

> *"For the 30–60 second first impression with a busy procurement
> manager who isn't listening for AI tells, Priya is indistinguishable
> from a junior BDR. For attentive listeners deeper in the call, we
> disclose honestly when asked — getting caught lying destroys
> conversion. Polite disclosure keeps the call going."*

This is defensible, true, and matches what the Priya system prompt
actually does (see `apps/voice/prompts/priya-system.md` rule "Are you
a bot?": Priya admits, then pivots back to qualifying).

What makes the agent feel human, by impact order:

| Factor | Status |
|---|---|
| Sub-1-second turn-taking | ✓ 650–840 ms target with Pipecat + Sarvam + Gemini |
| Voice naturalness (prosody, breath, intonation) | ✓ Sarvam Bulbul v3 — best Indian-language TTS available |
| Personalized opening (uses lead's name) | ✓ Built-in via `lead_first_name` metadata + 3-language templates |
| Pre-cached intro audio per lead | ✓ `lead_intro_audio` table + `synthesizeAndCacheIntros` helper (CP1) |
| Filler words ("right", "okay", "achha") | ✓ Explicit in Priya's system prompt |
| Pauses (0.5–1 sec where a human would pause) | ✓ Pipecat inter-turn pauses; Bulbul SSML supports pause tags |
| Mirroring lead's energy and formality | ✓ System prompt instruction |
| Objection handling without scripting | ✓ 9-pattern sales playbook in prompt |
| Acknowledges being AI if directly asked | ✓ Explicit prompt rule; pivots back to qualifying |
| **Backchanneling ("mm-hmm", "haan haan" mid-utterance)** | ⏳ CP2 — needed for true "active listener" feel |
| **Disfluency on hard questions ("umm, let me think...")** | ⏳ CP2 prompt tuning |

Verifying this in practice requires the **50 supervised test calls**
in the Setup package. Until those are done, every claim here is
aspiration, not proven.

### 2. "Answers honestly and correctly"

**Feasibility: HIGH, with guardrails in place.**

- **Knowledge base grounding:** the 250-product catalogue is loaded
  into the agent's KB. Priya cross-references "Do you sell X?"
  against the actual list — no hallucination of products that
  don't exist.
- **Hard "never invent" rule** in the system prompt:
  > "Never invent products or prices. If asked something outside
  > scope, say: Let me have a product specialist call you back
  > within four hours."
- **No public price quoting:** Priya never quotes a price live —
  always defers to the 4-hour quote SLA. This eliminates the
  single biggest hallucination risk.
- **Honest AI disclosure:** when the lead asks "are you a bot",
  Priya says: *"I'm an AI assistant from SPC's sales team — I do
  the first 30 seconds, then a human takes over for serious quotes.
  Now, are you involved in procurement at {{lead.company}}?"*
  This is shipped behavior, not a roadmap promise.

### 3. "All Indian languages and understanding"

**Day-1 feasibility: HIGH for clean-audio EN / HI / TA. MEDIUM for noisy
audio. The mid-call language-switching problem is the #1 thing that
makes Indian SME owners hang up — we have a deliberate solution for it.**

**Honest audio-quality reality:**

| Audio condition | Sarvam Saaras v3 word accuracy |
|---|---:|
| Clean speech (studio / quiet room) | ~92% |
| Mild background (office, home) | 80–85% |
| Real road / factory / auto-rickshaw noise | **65–75%** |
| Heavy Hinglish/Tanglish ("bhai woh delivery issue thi") | misreads ~1 in 4 utterances |

Tamil-Tanglish is harder than Hinglish: Tamil's SOV grammar means the
verb falls at the end of the sentence, so TTS prosody errors on the
final word make the agent sound robotic faster than in Hindi.

| Language | STT (Sarvam Saaras) | TTS (Sarvam Bulbul) | LLM (Gemini Flash) |
|---|---|---|---|
| English (Indian) | ✓ | ✓ | ✓ |
| Hindi | ✓ | ✓ | ✓ |
| Tamil | ✓ | ✓ | ✓ |

**Other Indian languages available without code change** (same stack,
agent config update) — quote SPC future-state coverage:

| Language | STT | TTS | LLM | Activation cost |
|---|---|---|---|---|
| Telugu | ✓ | ✓ | ✓ | ₹0 (re-tune prompt: 1 hour) |
| Bengali | ✓ | ✓ | ✓ | ₹0 |
| Marathi | ✓ | ✓ | ✓ | ₹0 |
| Kannada | ✓ | ✓ | ✓ | ₹0 |
| Malayalam | ✓ | ✓ | ✓ | ₹0 |
| Gujarati | ✓ | ✓ | ✓ | ₹0 |
| Punjabi | ✓ | ✓ | ✓ | ₹0 |
| Odia | ✓ | ✓ | ✓ | ₹0 |

**Sarvam supports 11 Indian languages**; we ship 3 actively for SPC
and offer the others as a no-cost configuration add-on if their
expansion needs it.

**Language matching is locked** in the system prompt:
> "The single most important rule of this entire call: speak whatever
> language the lead chooses to speak."

**The mid-call language-switching solution (CP2 — our real moat):**

Naive auto-detect-and-respond fails on real Indian calls. A single
"haan" or "okay" mis-flips the agent's language for the rest of the
turn — leads notice immediately and the call dies. Our solution is a
deliberate **language state machine** layered on top of Sarvam STT:

1. **Per-utterance language tag from Saaras** — used as a signal, not
   gospel. Confidence threshold = 0.75; below that, we don't switch.
2. **State only flips after 2 consecutive full-utterances in the new
   language**, OR an explicit code-switch trigger phrase ("can we
   speak in English", "Hindi mein bolo", "Tamil-la pesa mudiyuma").
   A one-word "haan" never flips state.
3. **Bridge phrases** when switching: "Sure, English mein bolte hain"
   → then a clean transition to English. No snap mid-sentence.
4. **Single voice across all 3 languages.** Bulbul voice cloning gives
   us one Chennai-accent Priya base, rendered in EN / HI / TA. Critical
   so the lead feels they're talking to *the same person*.
5. **LLM gets the current language injected per turn** (`<current_language>en-IN</current_language>`)
   so it stops drifting back to Hindi-only context after a switch.
6. **Code-mixing (Hinglish/Tanglish) preserves dominant language** —
   does NOT trigger a switch. Most Indian SME conversations are
   code-mixed; over-correcting feels artificial.

This is the engineering difference between "demo works in English"
and "real Indian call works." See `apps/pipecat-agent/src/voice_agent/language_state.py`
for the full state machine + tests.

### 4. "Clean CRM data"

**Feasibility: HIGH.**

- **English-normalization rule**: regardless of the call language,
  the scoring LLM produces `summary`, `reason`, `next_action`,
  `industry`, `chemicals[]`, `current_supplier`, `supplier_pain[]`,
  `timeline` all in English.
- **Validation guard**: the scoring worker rejects any LLM output
  that contains Devanagari (Hindi) or Tamil script in those fields
  and forces a retry → marks `needs_review` if it persists.
- **Structured extraction** via Zod schema — no free-text dumping.
- **Original-language transcripts** preserved verbatim in the
  `transcripts` table for fidelity (so the rep can review the
  actual conversation), but the CRM-facing summary fields are
  uniformly English. Any rep can read any lead.

---

## Competitive positioning — Indian market

| Platform | Effective per-call cost | India-native? | Margin if you resold them | Quality |
|---|---:|---|---:|---|
| Vapi (US) | ₹13–17 | No (no DLT, no DPDP) | Negative at ₹15k/mo | High |
| Bland (US) | ₹15–18 | No | Negative | High |
| Sarvam Samvaad (turnkey) | ₹14–15 | Yes | Negative — Samvaad fee eats it | High |
| Bolna (India SaaS) | ₹14 | Yes | Negative | High |
| **You (Pipecat + Sarvam + Plivo)** | **₹4.65 / ₹2.65 BYON** | **Yes** | **54–68%** | **Same Sarvam grade** |

You're not competing on quality — that's at parity with every
serious player. You're winning on **unit economics**, because you
cut the platform middleman that everyone else pays.

---

## Comparison vs the obvious alternative (human BDR)

This is the slide that closes the deal.

| Cost line | Human junior BDR | Priya AI |
|---|---:|---:|
| Monthly salary + ESI/PF/bonus (Chennai market) | ₹30,000 | — |
| Workstation, phone, electricity | ₹2,000 | — |
| Training + onboarding (amortized over 1 year) | ₹3,000 | — |
| Effective calls per day (a human BDR dials 25–40/day) | 30 | 50+ |
| Languages spoken fluently | 1–2 | 3 (Sarvam supports 11) |
| Hours of operation | 9am–6pm | 24/7 |
| Vacation, sick days, attrition | ~15% time loss | 0% |
| **Effective cost per call** | **~₹500** | **₹15k ÷ 1,100 = ₹14** |
| **Monthly cost** | **₹35,000** | **₹15,000** |

The math is brutal in your favour. SPC isn't replacing one BDR —
they're getting **the equivalent of 2–3 BDRs working bigger volume
in three languages for less than half the salary of one human.**

---

## Talk track for the close

> "For SPC, we're proposing a custom Priya agent at **₹15,000 a
> month, which is less than the salary of a junior BDR you'd hire
> for the same first-touch work.** Priya dials 50 leads a day in
> English, Hindi, or Tamil, qualifies them in under three minutes,
> drops a clean English summary plus a 0–100 conversion score into
> your CRM, and pings your reps on WhatsApp the moment a hot lead
> surfaces.
>
> Two thousand calls per month included — that's 67 percent
> headroom on your projected volume. You can flip the agent off
> any time, or plug in your own Exotel number if you'd prefer to
> keep telephony in-house — your subscription doesn't change.
>
> One-time setup is one lakh: we load your full 250-product
> catalogue, tune Priya's voice with your team, register the DLT
> templates in all three languages, and run 50 supervised test
> calls before go-live. Year-one all-in is two-point-eight lakh.
> Year two onwards is one-point-eight lakh — about the same as
> three months of one BDR's salary, for unlimited working hours
> and three languages of coverage."

---

## Negotiation room (in your back pocket)

If SPC pushes hard, here are the levers in order of preference:

1. **Drop monthly to ₹12,500/mo for the first 6 months, then
   ₹15,000/mo from month 7.** Total Year-1 reduction: ₹15,000.
   Margin Year 1 still 56% — fine.
2. **Halve the setup to ₹50,000** if they sign a 24-month
   commitment instead of 12. You make the difference back in
   guaranteed Year-2 revenue.
3. **Add a referral kickback**: 1 free month of subscription
   for every paying referral SPC sends. Costs you ₹15k per
   activated referral — cheaper than any CAC.
4. **DO NOT drop below ₹12k/mo** — that's the floor where
   Year-2 margin breaks negative. Walk away from a deal at
   ₹10k/mo; the customer isn't worth the support burden.

---

## Year-2+ upgrade ladder (so SPC's price increases without churn)

| Year | Tier | Price | What changes |
|---|---|---:|---|
| Year 1 | Lighthouse Launch | ₹15k/mo | Everything in this doc |
| Year 2 | Lighthouse Launch (renewal) | ₹15k/mo | Same — protect retention |
| Year 3 | Growth | ₹22k/mo | + 5,000 calls/mo cap, + WhatsApp Business API automated handoff (saves their reps 5 min per Hot lead), + dedicated quarterly business review |
| Year 4+ | Scale | ₹35k/mo | + Custom voice (cloned from a real SPC rep), + multi-tenant sub-accounts for SPC's distributor network, + API access for them to embed Priya in their own apps |

This is your renewal playbook — SPC doesn't get a "price hike",
they get **more value at a higher tier**. Year-3 conversion to
Growth is the typical SaaS expansion pattern.

---

## Pricing ladder for future clients (use SPC as anchor)

When pitching client #2 onwards, you reference SPC's tier publicly
as "Starter" — this psychologically anchors them upward:

| Tier | Audience | Price | Calls/mo |
|---|---|---:|---:|
| **Starter** (SPC's tier) | SME doing 30–80 calls/day, 1 product line | ₹15,000/mo | 2,000 |
| **Growth** | Mid-market doing 100–300 calls/day, multi-product | ₹35,000/mo | 6,000 |
| **Scale** | Enterprise doing 500+ calls/day, multi-team | ₹75,000/mo | 15,000 |
| **Custom voice add-on** | Any tier — clone of a real human rep | +₹15,000/mo | — |
| **Multi-tenant white-label** | Distributors, agencies | +₹25,000/mo | — |

Selling 10 Starter clients = ₹15,00,000/mo recurring = ₹1.8 cr/yr.
That's the path to ₹5 cr ARR in 18 months without enterprise effort.

---

## Feasibility verdict — critique-honest version

| Question | Verdict |
|---|---|
| Can we deliver 50 calls/day at 150 sec avg? | **Yes.** Concurrency is not the bottleneck. |
| Can the agent sound genuine for 30-60s? | **Yes, with proof needed.** Stack supports it; needs 50 supervised live calls to verify. |
| Can it pass an attentive 3-minute Turing test? | **No, and no agent on the market does.** We disclose honestly when asked. |
| Can it answer correctly within scope? | **Yes.** KB grounding + "never invent" rule + 4-hour-quote fallback. |
| Can it understand clean-audio EN/HI/TA? | **Yes.** Sarvam Saaras v3 is best-in-class. |
| Can it handle noisy / weak-signal calls? | **Partially.** 65-75% word accuracy in real noise. Acceptable for qualification, not for nuanced negotiation. |
| Does mid-call language switching work? | **Yes, with the CP2 language-state-machine.** Naive auto-switch fails on Indian calls; our deliberate state machine fixes it. |
| Are CRM summaries clean English? | **Yes, enforced.** Regex guard + retry; `needs_review` queue otherwise. |
| Is ₹15k/mo + ₹1L setup profitable? | **Yes.** 60% Year-1 margin, 54-68% Year 2+. |
| Is it production-ready today? | **No.** Pipecat agent CP2 still to ship. DLT registration takes 7-14 days. 50 supervised calls needed before go-live. Realistic timeline: 4-6 weeks. |
| Sellable to clients beyond SPC? | **Yes, with white-glove setup.** Year-1 cap: 3 clients (SPC + 2 friendlies). Self-serve SaaS = 4-6 more weeks of onboarding-UX work. |
| Should the "never doubt it's AI" claim be in the pitch? | **No.** Promise "indistinguishable for 30-60s, honest disclosure after that." Defensible and converts better. |

**Bottom line: the model works. Margin is real. The hardest part —
mid-call language switching on noisy Indian audio — has a deliberate
engineered solution in CP2, not a hope-and-pray. We're 4-6 weeks from
SPC's first real call, mostly waiting on DLT and supervised testing.**

---

## Production-readiness roadmap (post-CP1)

| Week | Milestone | Blocker if missed |
|---|---|---|
| 0 (now) | CP1 shipped: schema, telemetry, intro-cache lib, eval harness | — |
| 1 | CP2 shipped: Pipecat agent + language state machine + signed webhooks | Can't make any real call |
| 1 | Start DLT template registration with Plivo/Exotel | Outbound to Indian mobiles rejected in prod |
| 2 | CP3 shipped: BYON vault + warm-cache endpoint + DLT helper UI | Onboarding tenant #2 unblocked |
| 2-3 | 50 supervised test calls with real Hindi/Tamil/English speakers | Quality unverified |
| 3-4 | Background-noise stress test (factory floor, traffic, weak signal) | Real-world failure modes unknown |
| 4 | Concurrent-call load test (15+ simultaneous) | SPC bursts could degrade |
| 4 | Cost guardrails: per-day spend cap, runaway-call kill switch | Bug burns money silently |
| 4 | DPDP compliance: recording disclosure + opt-out URL in greeting | Legal risk |
| 5 | DLT approved + production cutover | — |
| 6 | First real SPC outbound call | — |

This is the honest timeline. Anyone pitching faster is hand-waving.

---

*Document version: 1.1 · Last updated 2026-05-22 — critique-honest revision*
