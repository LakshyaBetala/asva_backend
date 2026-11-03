# PAPER_ANALYSIS — ASVA: streaming multilingual voice agent for outbound lead qualification

Technical foundation for an IEEE conference paper. Every quantitative statement below is traceable to a file in this repository or to a measurement script in `docs/paper/eval/`. Values that come from code comments (design intent) rather than measurement are marked *[design]*.

---

## 1. Core problem and objective

**Problem.** Small brokers and B2B sellers in India buy lead lists (property seekers, industrial buyers) and must call each lead quickly, in the lead's language (English, Hindi or Tamil, frequently code-mixed), extract a handful of qualification facts, and route promising leads to a human. Manual calling does not scale, and generic voice bots fail on three engineering axes:

1. **Turn latency on narrowband telephony.** Human conversational turn gaps cluster around 200 ms [Stivers 2009]; a cascaded STT → LLM → TTS pipeline over 8 kHz PSTN audio adds network round trips to three cloud services per turn. Gaps above ~2 s are perceived as a machine and lead to hang-ups.
2. **Language control under noisy, code-mixed speech.** Per-utterance language identification (LID) from the STT service is unreliable on short backchannels ("haan", "ok", "ம்"), and streaming STT sometimes transcribes English speech in Indic script. A naive "reply in the detected language" policy flips language mid-call.
3. **Multi-tenant data integrity.** Each call produces transcripts, per-turn telemetry, structured qualification slots and a post-call score that must be isolated per customer organisation and billed by duration.

**Objective.** Build and characterise an end-to-end system that (i) places outbound calls, (ii) converses in en-IN / hi-IN / ta-IN with deliberate language control, (iii) extracts qualification slots live and scores the lead after the call, and (iv) persists everything in a PostgreSQL schema whose tenant isolation and billing invariants are enforced by the database itself.

## 2. Key novelty and contributions

C1. **Sentence-pipelined streaming orchestration with parallel slot extraction** (`streaming_orchestrator.py`). LLM tokens are segmented at sentence boundaries (`. ? ! ।`) and each sentence is synthesised and transmitted while the LLM continues; a separate structured-extraction LLM call runs concurrently so qualification never sits on the response critical path. Output is hard-capped at two sentences per turn.

C2. **Hysteresis-based language state machine for code-mixed Indian calls** (`language_state.py`). Five rules: confidence gating (τ_c = 0.75), switch hysteresis (H = 2 consecutive full utterances, ≥ 3 words), explicit trigger phrases with instant switch, code-mix tolerance, and Unicode-script evidence treated as a *vote* rather than a decision. Includes a bridge phrase on switch.

C3. **Two-tier phrase cache and endpointing for narrowband audio** (`phrase_cache.py`, `exotel_ws_handler.py`). Content-addressed TTS cache key `sha256(text ‖ voice_id ‖ lang)` with a single pinned voice across languages; server-side VAD endpointing with a merge grace window (400 ms) and a dangling-fragment hold (700 ms), falling back to amplitude VAD (750 ms silence) with batch STT.

C4. **Database-enforced multi-tenancy and billing** (`packages/db/supabase/migrations/`). 13-table PostgreSQL schema with 37 tenant-isolation row-level-security policies keyed on a JWT claim injected by a login hook, child-table scoping via `EXISTS` sub-queries, a `BEFORE` trigger implementing tiered duration billing, and execution-based migration verification that surfaced three latent defects (Section 6).

## 3. Formal system architecture

### 3.1 Components

| Layer | Module(s) | Role |
|---|---|---|
| Telephony | Exotel Voicebot applet; `exotel_transport.py` | Outbound dial, bidirectional 8 kHz 16-bit PCM over WebSocket |
| Transport/session | `exotel_ws_handler.py` (1,435 LOC) | Framing, endpointing, barge-in, streaming-STT session, per-call context registry |
| Turn engine | `streaming_orchestrator.py` (2,272 LOC) | STT → normalisation → language state → LLM stream → sentence TTS → events |
| Dialogue control | `language_state.py`, `conversation_state.py` | Language FSM; monotone phase machine; filler/acknowledgement audit |
| Extraction & scoring | `qualification.py`, `lead_scorer.py` | Live slot extraction (8 slots + per-slot confidence); post-call classification |
| Speech services | `sarvam_streaming_stt.py`, `sarvam_stt.py`, `sarvam_tts*.py`, `smallest_tts.py`, `cartesia_tts.py`, `elevenlabs_tts.py` | Provider adapters behind a common `synthesize`/`transcribe` contract |
| LLM services | `gemini_llm.py`, `groq_llm.py` | Streaming generation; OpenAI-compatible fallback |
| Cost & safety | `cost_guard.py`, `pipeline.py` | Cost model, daily cap, runaway watchdog, hard cap |
| Persistence | `supabase_client.py` → PostgreSQL (Supabase) | Calls, transcripts, turn latencies, slots, scores |
| Back office | `apps/workers/*` (Cloudflare Workers), `apps/web` (Next.js CRM) | Dispatch with spend cap, scoring, hand-off, CRM with realtime |

### 3.2 Turn pipeline and latency model

For turn *k*, let end-of-speech be detected at time *e_k*. The agent's perceived response delay is the time to first audio (TTFA):

  TTFA_k = Δ_EP + Δ_STT + Δ_pre + Δ_LLM,1 + Δ_TTS,1 + Δ_net

where Δ_EP is endpointing delay, Δ_STT transcription latency (≈ 0 when the streaming STT has already finalised the transcript at end-of-speech), Δ_pre normalisation and language-state processing, Δ_LLM,1 time to the first complete sentence from the LLM stream, Δ_TTS,1 synthesis time of that sentence (≈ cache fetch time on a cache hit), and Δ_net the transmission to the telephony socket. The logged quantity used in Section 5 is the measurable core

  T̂_k = Δ_STT + Δ_LLM,1 + Δ_TTS,1.

Sentence pipelining converts the sequential cost Σ_i (Δ_LLM,i + Δ_TTS,i) into Δ_LLM,1 + Δ_TTS,1 for perceived latency, because sentences i ≥ 2 are produced while sentence 1 is playing. With a two-sentence cap (`MAX_SENTENCES_PER_TURN = 2`), the turn's wall time is bounded by the playback of at most two sentences.

### 3.3 Endpointing

Streaming path: the STT server emits a final segment; the turn is held for a grace window g = 400 ms (`STREAM_MERGE_GRACE_SEC`) and extended while the server reports speech activity; a segment that ends in a syntactically dangling fragment is held an extra h = 700 ms (`STREAM_DANGLING_HOLD_SEC`) and merged with the next segment. Batch fallback: chunks of ~100 ms are classified silent when peak |x| < 300; a turn closes after s = 750 ms of silence (`SILENCE_MS_THRESHOLD`), with minimum utterance 400 ms and maximum buffer 8 s. Barge-in: while the agent speaks, sustained input with peak ≥ 2500 for ≥ 500 ms flushes queued agent audio.

### 3.4 Language state machine

State ℓ ∈ L = {en, hi, ta}. Each utterance u = (λ, c, w, σ, x) carries the STT language label λ, confidence c, word count w, detected script σ ∈ L ∪ {∅} and text x. Hidden state: pending language p and counter n. Transition δ(ℓ, p, n, u):

1. If x contains an explicit request for language m ≠ ℓ (trigger phrase or "<language> + request cue"), ℓ ← m (instant).
2. Else if σ ≠ ∅: if σ = ℓ, reset (p, n) ← (∅, 0); else if w ≥ 2 and x is not a bare acknowledgement, increment n if p = σ else (p, n) ← (σ, 1); switch when n ≥ H, H = 2.
3. Else if c < τ_c = 0.75: no change.
4. Else if w ≥ 3 and λ ≠ ℓ: hysteresis on λ as in (2).
5. Code-mixed utterances never trigger a switch; they set only the dominant language for response selection.

On a switch the machine emits a bridge phrase for the pair (ℓ, m). The design objective is to minimise false switches on short or misrecognised utterances at the cost of a delay of at most H − 1 turns for genuine switches without an explicit request.

### 3.5 Conversation phase machine

Phase φ(t) is monotone non-decreasing in elapsed time t (seconds) with thresholds from `conversation_state.py`: GREETING t < 8; CONNECT t < 35; DISCOVER t < 70; QUALIFY t < 130; CLOSE t < 140; EXTENSION t < 290 iff buying confidence β ≥ 0.6 (else CLOSE). Phase boundaries are placed just before the billing boundaries of Section 3.8 (soft close at 140 s before the 150 s boundary; extension ends before 300 s).

### 3.6 Qualification slots and live temperature

Slots S = {product_interest, volume_monthly, buying_frequency, current_supplier, pain_point, decision_role, timeline_days, β}, each with confidence κ_s ∈ [0, 1]. A concurrent extraction call returns candidate values v'_s and κ'_s; merge rule: s ← v'_s iff v'_s ≠ null and κ'_s ≥ κ_s. Invalid JSON leaves the state unchanged.

Live temperature at turn k:

  hot if β ≥ 0.7 or (pain_point ≠ ∅ and timeline_days ≤ 30);
  warm if (∃ slot filled) and β ≥ 0.3;
  cold if k ≥ 3;
  unknown otherwise.

The authoritative post-call class ∈ {hot, warm, cold, dead} with a 0–100 score is produced by a separate LLM call over the full transcript and final slots (`lead_scorer.py`), with a deterministic fallback when the LLM output is invalid.

### 3.7 LLM availability policy

Per call, one key from a Gemini key pool is assigned by rotation; on HTTP 429 or stream failure the turn falls back to an OpenAI-compatible endpoint (Groq / Cerebras); if every provider fails, a localised "hold" line is spoken and the next turn retries. The system never substitutes a canned business answer for a failed generation.

### 3.8 Billing and cost model

Billed credits as a function of call duration d (seconds), implemented both in Python (`CallContext.billed_units`) and as a PostgreSQL `BEFORE INSERT OR UPDATE` trigger:

  b(d) = min(4, ⌈d / 150⌉) for completed calls with d > 0; 0 otherwise.

Per-call variable cost (`cost_guard.estimate_call_cost_inr`), with t_L and t_A the lead and agent speech seconds, T the duration, n the number of LLM turns and h the cache hits:

  C = (t_L/60)·r_STT + max(0, (t_A/60)·r_TTS − h·s) + (T/60)·r_tel + n·c_LLM + c_infra

with r_STT = r_TTS = ₹3.00/min, s = ₹0.10 per hit, r_tel = ₹1.80/min, c_LLM = ₹0.015/turn, c_infra = ₹0.20 *[design constants]*. The dispatcher's pessimistic projection for a 180 s call (t_L = t_A = 72 s, n = 30, h = 0) gives C = 3.60 + 3.60 + 5.40 + 0.45 + 0.20 = ₹13.25. The daily guard admits a call iff spent_today + Ĉ ≤ cap (default ₹600), with spent_today computed by the SQL function `tenant_spend_today()` on an IST day boundary. A runaway watchdog kills calls past 600 s + 10 s grace.

### 3.9 Tenant isolation model

For every tenant-scoped relation R with column tenant_id, the policy predicate is P_R(r) ≡ r.tenant_id = τ(J), where τ(J) extracts the `tenant_id` claim from the request JWT J (`current_tenant_id()`), and the claim is written at token issue by `custom_access_token_hook`. For a child relation R_c without tenant_id that references R_p, P_Rc(r) ≡ ∃ q ∈ R_p : q.id = r.fk ∧ q.tenant_id = τ(J). Inserts use `WITH CHECK` with the same predicate, so a client can neither read nor write rows of another tenant regardless of application code.

## 4. Implementation specifications

- **Languages/runtimes.** Python ≥ 3.11 (agent; FastAPI + Uvicorn, asyncio, httpx, Pydantic, structlog; Pipecat framework), TypeScript (Next.js 14 App Router CRM; Hono on Cloudflare Workers), SQL/PL/pgSQL (PostgreSQL 17 on Supabase).
- **Concurrency.** One asyncio task per call; within a turn, the LLM stream and slot extraction run as concurrent tasks; TTS for sentence *i* overlaps generation of sentence *i+1*; persistence (`insert_call`, turn rows, intro pre-synthesis) runs as tracked background tasks so it never blocks audio. Intro audio is pre-synthesised while the phone is ringing.
- **APIs.** `POST /exotel/calls` (place call; requires tenant_id; returns call SID); `WS /exotel/stream/{call_id}` (bidirectional audio; context resolved by Exotel CustomField = call UUID); Supabase REST/RPC for persistence; Workers for dispatch, scoring, hand-off, webhooks, click-to-call.
- **Audio.** 8 kHz 16-bit PCM on the line; 50 ms lead-in silence per TTS chunk; inter-sentence gap 120 ms (180 ms for Tamil); optional output gain.
- **Schema.** 13 tables (tenants, users, campaigns, leads, dnc_list, calls, call_events, transcripts, lead_scores, qualification_slots, handoffs, turn_latencies, lead_intro_audio), 36 indexes, 37 tenant-isolation RLS policies plus one read policy for the login-hook role, 1 view (`tenant_monthly_units`), 4 functions, 1 trigger, realtime publication on calls/transcripts/lead_scores; 18 ordered migrations.
- **Tests.** 387 Python unit/integration tests (pytest, respx-mocked HTTP), 116 TypeScript worker tests (Vitest; 20 skipped), pgTAP RLS isolation test.

## 5. Experimental and empirical metrics

### 5.1 Data

`apps/pipecat-agent/call-logs.txt`: per-turn telemetry written by the production WebSocket handler and the local harness during internal pilot sessions (developer and tester calls over Exotel PSTN and the laptop harness). No customer traffic. 115 sessions started; 52 sessions with ≥ 1 completed lead turn; 421 logged turns (hi-IN 196, en-IN 176, ta-IN 49). Session duration: median 98 s, mean 117 s, p95 291 s, max 450 s; turns per session: median 6, max 26. Lead-turn intent labels: normal 332, backchannel 32, silence 31, garbled 15, close 7, clarify 2, off-topic 1, reject 1. Reply language changed on 18 turns. Reproduction: `python docs/paper/eval/logstats.py call-logs.txt`, `python docs/paper/eval/ttfa.py call-logs.txt`.

### 5.2 Time to first audio (397 turns with T̂ > 0)

| Measure | n | mean | p50 | p90 | p95 |
|---|---|---|---|---|---|
| T̂ (STT + LLM₁ + TTS₁), all | 397 | 1688 | 1567 | 2627 | 3236 |
| LLM first sentence | 382 | 887 | 616 | 1438 | 1672 |
| TTS first sentence (synthesised) | 358 | 679 | 430 | 1448 | 1805 |
| Batch STT (batch-mode turns) | 154 | 483 | 442 | 620 | 701 |

(ms.) Share of mean T̂: LLM 50.6 %, TTS 38.3 %, STT 11.1 %. T̂ < 1 s on 21.2 % of turns, < 1.5 s on 47.1 %, < 2 s on 77.6 %. By reply language, p50: en-IN 1482 ms, hi-IN 1640 ms, ta-IN 1414 ms.

### 5.3 Observational ablations (same logs; not randomised)

| Condition | n | p50 T̂ | mean T̂ | Δp50 |
|---|---|---|---|---|
| Batch STT (amplitude VAD + POST) | 154 | 1760 | 1942 | — |
| Streaming STT (server VAD) | 243 | 1387 | 1527 | −21.2 % |
| Synthesised first sentence | 358 | 1624 | 1762 | — |
| Phrase-cache first sentence | 39 | 997 | 1010 | −38.6 % |

Caveat: conditions co-vary with session date and code version (streaming STT was introduced later than batch STT; cache hits concentrate on short stock phrases), so these are associations, not controlled effects. Endpointing delay Δ_EP is not included in T̂; for batch mode it adds the 750 ms silence window by construction, which makes the true streaming advantage larger than the T̂ difference.

### 5.4 Controlled provider benchmark

`docs/paper/eval/bench.py`, 2026-11-03, client in Chennai on a campus network, 10 sequential trials per provider through the agent's own client code, identical inputs (LLM: one system prompt + one user question, metric = time to first non-empty token; TTS: one 81-character Hindi sentence, metric = full synthesis time).

| Provider / model | n | p50 | mean | min | max |
|---|---|---|---|---|---|
| LLM gpt-oss-20b (Groq) | 10 | 529 | 566 | 447 | 846 |
| LLM gpt-oss-120b (Groq) | 10 | 789 | 771 | 461 | 1136 |
| LLM Gemini 2.5 Flash | 6* | 994 | 1198 | 845 | 1990 |
| TTS ElevenLabs | 10 | 663 | 892 | 491 | 1482 |
| TTS Cartesia | 10 | 1028 | 1141 | 730 | 1547 |
| TTS Smallest | 10 | 1201 | 1293 | 1026 | 1783 |

*Four Gemini trials failed with HTTP 429 (free-tier quota), directly motivating the key-pool rotation and fallback policy of Section 3.7. Sarvam STT/TTS could not be benchmarked on this date (account out of credits, HTTP 402).

### 5.5 Database verification

All 18 migrations were executed on a fresh PostgreSQL instance (embedded PG and Supabase PG 17) and exercised with inserts. RLS: 4/4 isolation checks passed (tenant A and B each see only their own lead; cross-tenant INSERT rejected by WITH CHECK). Constraint checks: duplicate (tenant, phone), score 150 and unknown status rejected. Execution surfaced three defects that static review had missed: (D1) a CHECK constraint capping billed_units at 2 while the trigger assigned 3, rejecting every call > 300 s; (D2) cost computed as credits × average order value (₹2,00,000), which made `tenant_spend_today()` exceed the ₹600 cap after one call and halted dispatch; (D3) the login hook, running as `supabase_auth_admin`, could not read `public.users` under RLS, so tokens carried no tenant claim. Each was fixed by a forward migration.

## 6. Failure modes and limitations

- **LLM dominates latency.** 50.6 % of mean T̂; tail p95 1.67 s for the first sentence. Free-tier quotas cause 429 cascades (observed in the benchmark and noted in code comments as adding 1–3 s per turn before key rotation).
- **Provider dependency and quotas.** STT is single-provider (Sarvam); when its credits ran out (HTTP 402) the agent could not transcribe. Telephony requires a funded Exotel account.
- **Language control trade-off.** H = 2 delays a genuine silent switch by one turn; trigger-phrase lists are hand-curated.
- **Endpointing trade-off.** The 400 ms merge grace and 700 ms dangling hold reduce interruptions of slow speakers but add latency to finished turns.
- **Echo and barge-in.** Half-duplex with an amplitude threshold; echo-prone lines need barge-in disabled.
- **Romanised entity drift.** 8 kHz STT corrupts proper nouns (localities); a normaliser repairs known names only.
- **Evaluation scope.** Pilot data are internal sessions with few distinct speakers; no word-error-rate ground truth, no human-rated naturalness (MOS) and no lead-scoring accuracy against sales outcomes. Seeded CRM data used for database demonstrations is synthetic and is not used for any result above.
- **Hosting region.** Deployment far from India (e.g. EU/US/Sydney) adds round-trip time to every provider call; the paper's latencies are client-side in Chennai.
- **Scalability.** Per-call state is in process memory (sticky to one agent instance); horizontal scaling needs call-affinity routing. Projected data volume ≈ 21 rows per call → ~4.2 M rows/month at 100 tenants × 2,000 calls, motivating time partitioning.
