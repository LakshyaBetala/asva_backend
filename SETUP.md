# SETUP — AI Voice Agent for SPC

End-to-end runbook to get this project from a fresh clone to a real
3-minute outbound call to a real Indian mobile number. Estimated
total time once accounts are approved: **5–7 calendar days**, of
which ~4 hours is hands-on work and the rest is KYC waiting.

> All work lives in `C:\Users\laksh\ai_voice`. Do not clone anywhere
> else. The repo is the single source of truth.

---

## 0. Prerequisites (one-time, ~30 min)

| Tool | Version | Install |
|---|---|---|
| Node.js | 20.18+ (see `.nvmrc`) | https://nodejs.org |
| pnpm | 9.x | `npm i -g pnpm@9` |
| Git for Windows | 2.45+ | https://git-scm.com/download/win |
| Docker Desktop | latest | https://www.docker.com/products/docker-desktop |
| Supabase CLI | 2.x | `npm i -g supabase` |
| Wrangler (Cloudflare) | 3.x | comes via workspace deps |
| psql | 15+ | https://www.postgresql.org/download/windows |

Confirm:
```powershell
node --version    # v20.x
pnpm --version    # 9.x
docker --version
supabase --version
```

---

## 1. Sign up for the external services (do these in parallel; KYC takes time)

| Service | URL | What to capture |
|---|---|---|
| **Cloudflare** | https://dash.cloudflare.com | API token (Pages + Workers + R2 edit), Account ID |
| **Supabase** (hosted) | https://supabase.com | New project in `ap-south-1`, Project URL + anon key + service_role key |
| **Sarvam AI** | https://www.sarvam.ai | API key, note free ₹1,000 credit |
| **Exotel** | https://exotel.com | Submit KYC (PAN, GSTIN, address proof) — **takes 24–48h** — then capture SID, API key, API token, virtual caller-ID |
| **Exotel DLT** | (via Exotel) | Register sender header `SUPREMEPETRO` and the 3 message templates from `docs/specs/...design.md` §9.2 |
| **Resend** | https://resend.com | API key, verified sender (use `onboarding@resend.dev` for demo) |

Once collected, paste all keys into a local `.env.local` at repo root
based on `.env.example`. Generate the internal token with:
```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```
and use the same value for every `INTERNAL_API_TOKEN` env var across
all five workers and the web app.

---

## 2. Local development (~30 min after deps installed)

```powershell
# 1. Install workspace deps
pnpm install

# 2. Start Docker Desktop, then start Supabase locally
pnpm db:start
# Copy the printed `anon key` and `service_role key` into .env.local
# along with NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321

# 3. Apply migrations + seed SPC tenant + demo admin
pnpm db:reset

# 4. Generate typed Supabase client
pnpm db:gen-types

# 5. Run all unit tests (35 tests across shared + workers)
pnpm -r test

# 6. Start the Next.js dashboard
pnpm --filter @ai-voice/web dev
# Visit http://localhost:3000, log in with admin@spc.test / demo-password-change-me
# Upload infra/seed/demo-leads.csv via the dashboard
```

---

## 3. Push hosted Supabase (~15 min)

```powershell
cd packages/db
supabase link --project-ref <YOUR_PROJECT_REF>
supabase db push                                  # applies migrations
# Then run the seed manually against the hosted DB:
psql "<connection-string-from-supabase-dashboard>" -f supabase/seed.sql
# Regenerate types from cloud:
supabase gen types typescript --linked > src/types.gen.ts
cd ../..
```

Update Cloudflare Pages env vars to point at the hosted Supabase
URL + anon key once you reach Step 5.

---

## 4. Configure the Priya agent on Sarvam (~30 min)

1. Sarvam dashboard → **Samvaad** → **New agent**.
2. Either import `infra/samvaad/spc-priya.agent.json` if their UI
   supports JSON import, or paste each field manually.
3. Upload the KB files:
   - `infra/samvaad/kb/products.csv`
   - `infra/samvaad/kb/value-prop.md`
   - (Optional) replace the `products.csv` placeholder with SPC's
     full 250-product catalogue when available.
4. Pick a female voice from the Bulbul gallery — preview several and
   choose the most natural. Record the chosen `voice_id` in the JSON
   and commit.
5. Paste the Priya system prompt from
   `packages/shared/src/prompts/priya-system.md` into the agent's
   system prompt field.
6. Save. Copy the agent ID (`agt_xxx`) Sarvam returns.
7. In Supabase Studio (local or cloud) SQL editor:
   ```sql
   update public.tenants
   set samvaad_agent_id = '<agt_xxx>'
   where slug = 'spc';
   ```

---

## 5. Deploy workers + dashboard (~45 min)

Authenticate Wrangler once:
```powershell
npx wrangler login
```

Create the R2 bucket:
```powershell
npx wrangler r2 bucket create ai-voice-recordings
```

Deploy each worker. Inside each `apps/workers/<name>/` directory run
`npx wrangler secret put <NAME>` for each secret listed in its
`wrangler.toml` (use the values from `.env.local`), then deploy.

Order matters — handoff first (because score needs HANDOFF_WORKER_URL),
then score, then webhooks (which needs SCORE_WORKER_URL),
then campaigns, then clicktocall.

```powershell
# 1. handoff
cd apps/workers/handoff
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put APP_BASE_URL
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put RESEND_FROM
npx wrangler deploy
# note the printed URL

# 2. score
cd ../score
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SARVAM_BASE_URL
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put HANDOFF_WORKER_URL   # paste from step 1
npx wrangler deploy

# 3. webhooks
cd ../webhooks
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SAMVAAD_WEBHOOK_SECRET
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put SARVAM_BASE_URL
npx wrangler secret put SCORE_WORKER_URL     # paste from step 2
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler deploy
# update the Samvaad agent webhook URL to https://<webhooks>.workers.dev/samvaad

# 4. campaigns
cd ../campaigns
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put SARVAM_BASE_URL
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler deploy

# 5. clicktocall
cd ../clicktocall
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put EXOTEL_SID
npx wrangler secret put EXOTEL_API_KEY
npx wrangler secret put EXOTEL_API_TOKEN
npx wrangler deploy

cd ../../..
```

Deploy the dashboard:
```powershell
pnpm --filter @ai-voice/web run deploy
```

In Cloudflare Pages → `ai-voice-web` → Environment variables (Production),
set:
- `NEXT_PUBLIC_SUPABASE_URL` (hosted)
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` (hosted)
- `CAMPAIGNS_WORKER_URL`
- `CLICKTOCALL_WORKER_URL`
- `INTERNAL_API_TOKEN`

Trigger a redeploy after setting the vars.

---

## 6. First end-to-end test call (~10 min)

1. Open the deployed dashboard URL.
2. Log in (admin@spc.test seed credentials).
3. **Add lead** → your own mobile number.
4. Open the lead → **Call with AI**.
5. Your phone rings. Pick up. You should hear Priya greeting you by name.
6. Test all three language switches (reply in EN, HI, TA).
7. Watch the dashboard: transcript streams in, then after `call.ended`
   the AI summary, score badge, and extracted fields appear within
   ~30s. If you scored Hot, you get a WhatsApp link + email handoff.
8. Click **Call now** on the same lead from desktop — your phone
   rings, then bridges to the lead number.

---

## 7. Six-scenario E2E demo (~30 min, do before pitching SPC)

Follow `docs/plans/2026-05-21-plan-3-scoring-handoff-demo.md` Task 9.
Record all six scenarios.

---

## 8. Troubleshooting cheat-sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| Phone never rings | Exotel KYC / DLT not approved | Wait + verify in Exotel dashboard |
| Webhook returns 401 | Signature mismatch | Confirm `SAMVAAD_WEBHOOK_SECRET` matches in both Sarvam agent config and webhooks-worker secret |
| Transcripts empty in DB | Samvaad webhook URL wrong | Update agent webhook URL to the webhooks-worker URL |
| Scoring returns needs_review | LLM returned Hindi/Tamil in fields | Expected — retry triggers automatically; if persistent, check `prompts/scoring.md` made it into the worker bundle |
| Priya doesn't greet by name | `lead_first_name` not in metadata | Verify campaigns-worker is sending `lead_first_name`; check `first_turn_templates` in `spc-priya.agent.json` |
| WhatsApp link fails to open | rep's number missing `+` | Confirm tenant.whatsapp_handoff_number or users.whatsapp is E.164 |
| pgTAP RLS test fails | seed conflicts | `pnpm db:reset` for a clean slate |
| `pnpm install` slow on Windows | normal | One-time ~1 min |

---

## 9. Cost guardrails

Per-call blended target: **₹9–13** including telephony + STT + TTS +
LLM + Samvaad. See `docs/specs/...design.md` §10 for the breakdown.

Fixed infra at demo scale: **₹0/mo** (all free tiers).

If volume crosses ~20k calls/month, see the spec's "swap to Pipecat"
upgrade path.

---

## 10. Daily workflow

```powershell
pnpm db:start            # boot local Supabase (idempotent)
pnpm -r test             # run all unit tests
pnpm --filter @ai-voice/web dev    # frontend
# Workers locally:
pnpm --filter @ai-voice/webhooks-worker dev
# Or deploy individual workers when you change them:
pnpm --filter @ai-voice/score-worker deploy
```

---

## 11. What's NOT in this repo

- API keys, service-role keys, telephony credentials — kept in
  `.env.local` (gitignored) and Cloudflare secrets.
- Recordings — they live in Cloudflare R2 bucket `ai-voice-recordings`.
- Lead lists — uploaded by tenants via dashboard CSV; never committed.

That's it. If something here is wrong, fix the doc — it's the runbook
the next engineer reads cold.
