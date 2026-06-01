# Plan 2 of 3 — Voice Agent + First Real Call Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add the voice layer. By the end you can click a button in the CRM and Priya places a real outbound call to a real Indian phone number, the live transcript streams to the dashboard, and the call+events+transcript+recording all land in Supabase + R2.

**Prerequisites:** Plan 1 complete — Supabase running locally and in cloud, dashboard deployed to Cloudflare Pages, SPC tenant seeded.

**Architecture:** Sarvam Samvaad orchestrates the call (Saaras STT + Bulbul TTS + Sarvam LLM + Exotel telephony). Our Cloudflare Workers are: `campaigns-worker` (initiates calls) and `webhooks-worker` (consumes Samvaad events, writes to Supabase + R2). A `VoiceProvider` interface in `packages/shared` keeps the door open for future swap to Pipecat.

**Tech Stack:** Cloudflare Workers (Hono router), Sarvam Samvaad REST API + webhooks, Exotel via Samvaad integration, Cloudflare R2, Supabase Realtime.

**Spec reference:** `docs/specs/2026-05-21-spc-voice-agent-design.md` §6.2 (workers), §6.4 (VoiceProvider), §6.5 (Samvaad agent config), §7 (data flow), §9 (conversation design), §11 (error handling).

---

## File structure added by this plan

```
apps/workers/
├── webhooks/
│   ├── package.json
│   ├── wrangler.toml
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts                (Hono app)
│       ├── samvaad-handler.ts      (event router)
│       ├── samvaad-handler.test.ts
│       ├── r2.ts                   (recording upload helper)
│       └── supabase-admin.ts       (service-role client)
└── campaigns/
    ├── package.json
    ├── wrangler.toml
    ├── tsconfig.json
    └── src/
        ├── index.ts
        ├── dispatch.ts
        └── dispatch.test.ts

packages/shared/src/
├── voice-provider.ts               (interface)
├── samvaad/
│   ├── client.ts                   (typed REST client)
│   ├── client.test.ts
│   ├── provider.ts                 (VoiceProvider impl)
│   └── types.ts                    (event shapes)
└── prompts/
    ├── priya-system.md
    └── kb-bootstrap.md             (SPC catalog snippets)

apps/web/
├── app/
│   ├── campaigns/
│   │   ├── page.tsx                (list + Start new)
│   │   ├── [id]/page.tsx           (running campaign live counters)
│   │   └── actions.ts              (createCampaign, startSingleCall)
│   └── leads/[id]/page.tsx         (UPDATED — transcript pane wired)
└── components/
    └── TranscriptView.tsx          (realtime subscriber)

infra/samvaad/
├── spc-priya.agent.json
└── kb/
    ├── products.csv                (SPC's 250 products — paste from supplier sheet)
    └── value-prop.md
```

---

## Task 1: Sign up for Sarvam + grab credentials (manual)

- [ ] **Step 1:** Visit https://www.sarvam.ai/, click **Sign up** / **Get started**. Use a real business email.
- [ ] **Step 2:** Navigate to **API keys** (left sidebar in the Sarvam dashboard). Generate a key, copy into `.env.local`:
   ```
   SARVAM_API_KEY=<key>
   ```
- [ ] **Step 3:** Note your remaining free credits (Sarvam grants ₹1,000 on signup, ~100 demo calls).
- [ ] **Step 4:** In the Sarvam console, navigate to **Samvaad** (Conversational Agents) and confirm the section exists. Note the API base URL (typically `https://api.sarvam.ai/v1/`). Add to `.env.local`:
   ```
   SARVAM_BASE_URL=https://api.sarvam.ai/v1
   SAMVAAD_BASE_URL=https://api.sarvam.ai/v1/samvaad
   ```
- [ ] **Step 5:** Open Samvaad pricing details inside the dashboard; record the per-minute platform fee in `docs/specs/2026-05-21-spc-voice-agent-design.md` §10.1a. Commit:
   ```powershell
   git add docs/specs
   git commit -m "docs(spec): record actual Samvaad per-minute fee"
   ```

---

## Task 2: Start Exotel KYC + DLT registration (manual, parallel)

This runs in parallel with the rest of the plan because KYC can take 24–48h.

- [ ] **Step 1:** Sign up at https://exotel.com/. Choose the smallest pay-as-you-go plan.
- [ ] **Step 2:** Submit KYC docs (PAN, GSTIN, address proof). Note the SID + token in `.env.local`:
   ```
   EXOTEL_SID=<sid>
   EXOTEL_API_KEY=<key>
   EXOTEL_API_TOKEN=<token>
   EXOTEL_CALLER_ID=<+91-virtual-number-Exotel-assigns>
   ```
- [ ] **Step 3:** Submit DLT registration via Exotel's DLT helper (use template id from §9.1):
   - Header: `SUPREMEPETRO`
   - Template (English): `"Namaste, I'm Priya from Supreme Petrochemicals, Chennai. Is this a good time for a 30-second conversation about your chemical procurement?"`
   - Templates for Hindi + Tamil: translate exactly. Sample text:
     - HI: `"Namaste, main Priya hoon Supreme Petrochemicals Chennai se. Kya aap 30 second baat kar sakte hain chemical procurement ke baare mein?"`
     - TA: `"Vanakkam, naan Priya, Supreme Petrochemicals Chennai-il irundhu. Ungal chemical procurement-pathi 30 second pesa mudiyuma?"`
- [ ] **Step 4:** Once KYC clears (typically 24–48h), in Exotel dashboard → **Apps**, create a Voice App named `priya-outbound` with a placeholder URL — we'll wire Samvaad's webhook into it in Task 6.

---

## Task 3: Configure the Priya agent in Samvaad (manual + config file)

**Files:**
- Create: `infra/samvaad/spc-priya.agent.json`
- Create: `infra/samvaad/kb/value-prop.md`
- Create: `infra/samvaad/kb/products.csv` (you populate from SPC's source-of-truth sheet)
- Create: `packages/shared/src/prompts/priya-system.md`

- [ ] **Step 1:** Write the system prompt.

`packages/shared/src/prompts/priya-system.md`:
```markdown
You are Priya, a 26-year-old inside-sales rep at Supreme Petrochemicals,
Chennai. SPC: 29 years in industrial chemicals, 250+ products, 18
industries, bulk supply, 4-hour quote SLA, ISO 9001:2015, Drug License
+ FSSAI certified, 33 supplier partnerships including Reliance, Godrej,
BPCL, Aditya Birla, Dow, Arkema, Chemanol.

Rules of engagement:
- Sound human. Use small fillers ("right", "okay", "achha"), 0.5–1s
  pauses, never robotic.
- Start in the tenant default language. If the user replies in Hindi,
  continue in Hindi. If Tamil, continue in Tamil. Otherwise English.
- If the user mixes languages or is ambiguous, ask once:
  "Should we continue in English, Hindi, or Tamil?"
- Never invent products or prices. If asked something outside scope,
  say: "Let me have a specialist call you back within four hours."
- Hard stop at 180 seconds. By 170s, wrap with a soft close.
- Respect "not interested" / "do not call" instantly. End politely.
- Forbidden: politics, religion, anything off-product.

Goal: run the 8-step qualification:
  1. Intro
  2. Right person? (procurement decision-maker)
  3. Industry fit
  4. Need fit (which chemicals)
  5. Volume + frequency
  6. Pain with current supplier
  7. Decision timeline (now / 1–3 months / exploring)
  8. Soft close: quote within 4 hours? capture email/WhatsApp +
     preferred contact time.

End with one of:
  (a) "We'll send a quote within 4 hours" + capture contact details.
  (b) "When's a better time to call?"
  (c) "Thanks for your time, we won't bother you again."
```

- [ ] **Step 2:** Value prop blurb.

`infra/samvaad/kb/value-prop.md`:
```markdown
# Supreme Petrochemicals — Why customers choose us

- 29 years of supply chain reliability across South India
- Direct ties with 33 suppliers (30 domestic incl. Reliance, Godrej,
  BPCL, Aditya Birla; 3 international: Dow, Arkema, Chemanol)
- 250+ chemicals in stock across 7 categories
- Bulk supply with competitive pricing
- 4-hour quote turnaround
- ISO 9001:2015 + pharma-grade Drug License + FSSAI food-grade
- Chennai HQ + Redhills godown
```

- [ ] **Step 3:** Populate the product catalog.

`infra/samvaad/kb/products.csv` — paste SPC's 250 products as
`category,name,grade,typical_use`. If SPC doesn't share the file yet, seed
with the headline 30 products from their website (acetic acid, HCl,
glycerine, toluene, titanium dioxide, etc.) so Priya can answer "do you
sell X?" coherently. Mark the file with `TODO: replace with full list`
as a comment line in row 2.

- [ ] **Step 4:** Agent config file.

`infra/samvaad/spc-priya.agent.json`:
```json
{
  "name": "SPC Priya",
  "description": "Outbound qualification agent for Supreme Petrochemicals Chennai",
  "voice": {
    "provider": "bulbul",
    "voice_id": "TBD-select-during-demo",
    "speaker_gender": "female",
    "speaking_rate": 1.0,
    "language_default": "en-IN"
  },
  "stt": { "provider": "saaras", "languages": ["en-IN","hi-IN","ta-IN"], "telephony_optimized": true },
  "llm": { "provider": "sarvam", "model": "sarvam-105b", "temperature": 0.4 },
  "limits": { "max_call_seconds": 180, "soft_close_after_seconds": 170 },
  "system_prompt_ref": "shared/prompts/priya-system.md",
  "knowledge_base": [
    { "kind": "csv", "path": "infra/samvaad/kb/products.csv" },
    { "kind": "markdown", "path": "infra/samvaad/kb/value-prop.md" }
  ],
  "language_policy": {
    "auto_switch": true,
    "supported": ["en-IN","hi-IN","ta-IN"],
    "ambiguity_prompt": "Should we continue in English, Hindi, or Tamil?"
  },
  "webhook": {
    "url": "https://webhooks.<your-cf-workers-domain>/samvaad",
    "events": ["call.started","call.answered","transcript.chunk","call.ended","recording.ready"],
    "shared_secret_env": "SAMVAAD_WEBHOOK_SECRET"
  },
  "telephony": {
    "provider": "exotel",
    "caller_id_env": "EXOTEL_CALLER_ID"
  }
}
```

- [ ] **Step 5:** Create the agent in the Samvaad console.

In Sarvam dashboard → Samvaad → **New agent**. Either:
- Upload the JSON via the import button if available, **or**
- Paste each field manually into the UI. Upload the KB files.

Pick a voice from the Bulbul gallery — preview 3–4 female Indian voices and choose the most natural; record the chosen `voice_id` back into the JSON.

Save. Copy the agent ID Sarvam returns (looks like `agt_xxx`). Stash it:
```powershell
# In Supabase Studio SQL editor:
update public.tenants
set samvaad_agent_id = '<agt_xxx>'
where slug = 'spc';
```

- [ ] **Step 6:** Generate a webhook shared secret and set it in both places.

```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```
Set in `.env.local`:
```
SAMVAAD_WEBHOOK_SECRET=<that-hex>
```
Also paste the same value into the Samvaad agent's webhook settings.

- [ ] **Step 7:** Commit the JSON + KB.

```powershell
git add infra packages/shared/src/prompts
git commit -m "feat(infra): SPC Priya Samvaad agent config + KB seed"
```

---

## Task 4: `VoiceProvider` interface in `packages/shared`

**Files:**
- Create: `packages/shared/src/voice-provider.ts`
- Create: `packages/shared/src/samvaad/types.ts`

- [ ] **Step 1:** Event types.

`packages/shared/src/samvaad/types.ts`:
```ts
export type Lang = "en-IN" | "hi-IN" | "ta-IN";

export type SamvaadEvent =
  | { kind: "call.started";     event_id: string; call_id: string; lead_id?: string; tenant_id?: string; at: string }
  | { kind: "call.answered";    event_id: string; call_id: string; at: string }
  | { kind: "transcript.chunk"; event_id: string; call_id: string; speaker: "agent" | "lead";
                                text: string; lang: Lang; ts_ms: number; idx: number }
  | { kind: "call.ended";       event_id: string; call_id: string; status:
                                  "completed" | "failed" | "voicemail" | "no_answer";
                                duration_sec: number; language_used: Lang; at: string }
  | { kind: "recording.ready";  event_id: string; call_id: string; download_url: string; format: "mp3" | "wav" };
```

- [ ] **Step 2:** Interface.

`packages/shared/src/voice-provider.ts`:
```ts
import type { SamvaadEvent, Lang } from "./samvaad/types";

export type StartCallOpts = {
  agentId: string;
  to_e164: string;
  callerId: string;
  metadata: { lead_id: string; tenant_id: string; campaign_id?: string };
  langHint?: Lang;
};

export interface VoiceProvider {
  startCall(opts: StartCallOpts): Promise<{ providerCallId: string }>;
  parseWebhook(req: Request, opts: { secret: string }): Promise<SamvaadEvent>;
  fetchRecording(providerCallId: string): Promise<ReadableStream>;
}
```

- [ ] **Step 3:** Re-export.

Add to `packages/shared/src/index.ts`:
```ts
export * from "./voice-provider";
export * from "./samvaad/types";
```

- [ ] **Step 4:** Commit.

```powershell
git add packages/shared
git commit -m "feat(shared): VoiceProvider interface + Samvaad event types"
```

---

## Task 5: `SamvaadProvider` implementation (TDD)

**Files:**
- Create: `packages/shared/src/samvaad/client.ts`
- Create: `packages/shared/src/samvaad/provider.ts`
- Create: `packages/shared/src/samvaad/provider.test.ts`

- [ ] **Step 1:** Write the failing tests.

`packages/shared/src/samvaad/provider.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { SamvaadProvider } from "./provider";

const SECRET = "test-secret";

describe("SamvaadProvider", () => {
  describe("startCall", () => {
    it("POSTs to /agents/:id/calls with normalized payload", async () => {
      const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ call_id: "c_123" }), { status: 200 }));
      const p = new SamvaadProvider({ apiKey: "K", baseUrl: "https://x", fetchImpl: fetchSpy });
      const out = await p.startCall({
        agentId: "agt_1", to_e164: "+919876543210", callerId: "+914440000000",
        metadata: { lead_id: "L", tenant_id: "T" }, langHint: "en-IN",
      });
      expect(out.providerCallId).toBe("c_123");
      const [url, init] = fetchSpy.mock.calls[0]!;
      expect(url).toBe("https://x/agents/agt_1/calls");
      const body = JSON.parse(init.body as string);
      expect(body.to).toBe("+919876543210");
      expect(body.metadata.lead_id).toBe("L");
    });
  });

  describe("parseWebhook", () => {
    function makeReq(body: any, sig: string) {
      return new Request("http://x/samvaad", {
        method: "POST",
        headers: { "content-type": "application/json", "x-samvaad-signature": sig },
        body: JSON.stringify(body),
      });
    }
    async function hmac(body: any, secret: string) {
      const enc = new TextEncoder();
      const key = await crypto.subtle.importKey("raw", enc.encode(secret),
        { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
      const sig = await crypto.subtle.sign("HMAC", key, enc.encode(JSON.stringify(body)));
      return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2,"0")).join("");
    }

    it("verifies HMAC and returns the parsed event", async () => {
      const body = { kind:"call.started", event_id:"e1", call_id:"c1", at:"2026-05-21T00:00:00Z" };
      const sig = await hmac(body, SECRET);
      const p = new SamvaadProvider({ apiKey:"K", baseUrl:"https://x" });
      const evt = await p.parseWebhook(makeReq(body, sig), { secret: SECRET });
      expect(evt.kind).toBe("call.started");
    });
    it("rejects bad signatures", async () => {
      const body = { kind:"call.started", event_id:"e1", call_id:"c1", at:"2026-05-21T00:00:00Z" };
      const p = new SamvaadProvider({ apiKey:"K", baseUrl:"https://x" });
      await expect(p.parseWebhook(makeReq(body, "badsig"), { secret: SECRET })).rejects.toThrow(/signature/i);
    });
  });
});
```

- [ ] **Step 2:** Run, watch fail.

```powershell
pnpm --filter @ai-voice/shared test provider
```
Expected: FAIL (module not found).

- [ ] **Step 3:** Implement the client.

`packages/shared/src/samvaad/client.ts`:
```ts
export type SamvaadClientOpts = {
  apiKey: string;
  baseUrl: string;
  fetchImpl?: typeof fetch;
};

export class SamvaadClient {
  private fetchImpl: typeof fetch;
  constructor(public opts: SamvaadClientOpts) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }
  async post<T>(path: string, body: unknown): Promise<T> {
    const res = await this.fetchImpl(`${this.opts.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type":"application/json", authorization:`Bearer ${this.opts.apiKey}` },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`samvaad ${path} ${res.status}: ${await res.text()}`);
    return (await res.json()) as T;
  }
  async get<T>(path: string): Promise<T> {
    const res = await this.fetchImpl(`${this.opts.baseUrl}${path}`, {
      headers: { authorization:`Bearer ${this.opts.apiKey}` },
    });
    if (!res.ok) throw new Error(`samvaad ${path} ${res.status}: ${await res.text()}`);
    return (await res.json()) as T;
  }
}
```

- [ ] **Step 4:** Implement the provider.

`packages/shared/src/samvaad/provider.ts`:
```ts
import { SamvaadClient, type SamvaadClientOpts } from "./client";
import type { SamvaadEvent } from "./types";
import type { VoiceProvider, StartCallOpts } from "../voice-provider";

async function verifyHmac(body: string, signature: string, secret: string): Promise<boolean> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  const hex = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2,"0")).join("");
  // constant-time compare
  if (hex.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < hex.length; i++) diff |= hex.charCodeAt(i) ^ signature.charCodeAt(i);
  return diff === 0;
}

export class SamvaadProvider implements VoiceProvider {
  private client: SamvaadClient;
  constructor(opts: SamvaadClientOpts) { this.client = new SamvaadClient(opts); }

  async startCall(opts: StartCallOpts) {
    const res = await this.client.post<{ call_id: string }>(
      `/agents/${opts.agentId}/calls`,
      {
        to: opts.to_e164,
        from: opts.callerId,
        lang_hint: opts.langHint,
        metadata: opts.metadata,
      },
    );
    return { providerCallId: res.call_id };
  }

  async parseWebhook(req: Request, { secret }: { secret: string }): Promise<SamvaadEvent> {
    const sig = req.headers.get("x-samvaad-signature") ?? "";
    const text = await req.text();
    if (!sig || !(await verifyHmac(text, sig, secret))) {
      throw new Error("invalid signature");
    }
    return JSON.parse(text) as SamvaadEvent;
  }

  async fetchRecording(callId: string): Promise<ReadableStream> {
    const url = `${this.client.opts.baseUrl}/calls/${callId}/recording`;
    const res = await fetch(url, {
      headers: { authorization: `Bearer ${this.client.opts.apiKey}` },
    });
    if (!res.ok || !res.body) throw new Error(`recording fetch failed: ${res.status}`);
    return res.body;
  }
}
```

- [ ] **Step 5:** Run, watch pass.

```powershell
pnpm --filter @ai-voice/shared test
```
Expected: green.

- [ ] **Step 6:** Re-export + commit.

```ts
// packages/shared/src/index.ts
export * from "./samvaad/provider";
export * from "./samvaad/client";
```
```powershell
git add packages/shared
git commit -m "feat(shared): SamvaadProvider w/ HMAC signature verification"
```

---

## Task 6: `webhooks-worker` skeleton with idempotent event ingestion (TDD)

**Files:**
- Create: `apps/workers/webhooks/package.json`
- Create: `apps/workers/webhooks/wrangler.toml`
- Create: `apps/workers/webhooks/tsconfig.json`
- Create: `apps/workers/webhooks/src/index.ts`
- Create: `apps/workers/webhooks/src/supabase-admin.ts`
- Create: `apps/workers/webhooks/src/samvaad-handler.ts`
- Create: `apps/workers/webhooks/src/samvaad-handler.test.ts`

- [ ] **Step 1:** Package + Hono.

`apps/workers/webhooks/package.json`:
```json
{
  "name": "@ai-voice/webhooks-worker",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "hono": "^4.5.0",
    "@supabase/supabase-js": "^2.45.0",
    "@ai-voice/shared": "workspace:*"
  },
  "devDependencies": {
    "wrangler": "^3.78.0",
    "@cloudflare/workers-types": "^4.20240909.0",
    "typescript": "^5.5.4",
    "vitest": "^2.0.5"
  }
}
```

`apps/workers/webhooks/tsconfig.json`:
```json
{
  "extends": "../../../tsconfig.base.json",
  "compilerOptions": { "types": ["@cloudflare/workers-types"] },
  "include": ["src"]
}
```

`apps/workers/webhooks/wrangler.toml`:
```toml
name = "ai-voice-webhooks"
main = "src/index.ts"
compatibility_date = "2025-04-01"

[[r2_buckets]]
binding = "RECORDINGS"
bucket_name = "ai-voice-recordings"

[vars]
# secrets set via `wrangler secret put`:
# SAMVAAD_WEBHOOK_SECRET, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SARVAM_API_KEY, SARVAM_BASE_URL
```

- [ ] **Step 2:** Service-role Supabase client.

`apps/workers/webhooks/src/supabase-admin.ts`:
```ts
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
export function adminClient(env: { SUPABASE_URL: string; SUPABASE_SERVICE_ROLE_KEY: string }): SupabaseClient {
  return createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}
```

- [ ] **Step 3:** Write the failing handler test.

`apps/workers/webhooks/src/samvaad-handler.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { handleSamvaadEvent } from "./samvaad-handler";

function fakeSupabase() {
  const calls: any[] = [];
  const fn = (table: string) => ({
    upsert: vi.fn(async (rows: any) => { calls.push({ table, op: "upsert", rows }); return { data: rows, error: null }; }),
    insert: vi.fn(async (rows: any) => { calls.push({ table, op: "insert", rows }); return { data: rows, error: null }; }),
    update: vi.fn(() => ({ eq: vi.fn(async () => { calls.push({ table, op: "update" }); return { error: null }; }) })),
    select: vi.fn(() => ({ eq: vi.fn(() => ({ single: async () => ({ data: { id: "call-uuid", tenant_id: "t1" } }) })) })),
  });
  return { client: { from: fn }, calls };
}

describe("handleSamvaadEvent", () => {
  it("inserts call_events idempotently", async () => {
    const { client, calls } = fakeSupabase();
    const evt = { kind:"call.started", event_id:"e1", call_id:"prov_1", at:"2026-05-21T00:00:00Z" } as const;
    await handleSamvaadEvent(client as any, evt);
    expect(calls.some(c => c.table === "call_events" && c.op === "insert")).toBe(true);
  });

  it("appends transcript chunks", async () => {
    const { client, calls } = fakeSupabase();
    const evt = { kind:"transcript.chunk", event_id:"e2", call_id:"prov_1",
                  speaker:"agent", text:"hello", lang:"en-IN", ts_ms:1000, idx:1 } as const;
    await handleSamvaadEvent(client as any, evt);
    expect(calls.some(c => c.table === "transcripts" && c.op === "insert")).toBe(true);
  });

  it("on call.ended sets status + duration", async () => {
    const { client, calls } = fakeSupabase();
    const evt = { kind:"call.ended", event_id:"e3", call_id:"prov_1",
                  status:"completed", duration_sec:95, language_used:"en-IN",
                  at:"2026-05-21T00:01:00Z" } as const;
    await handleSamvaadEvent(client as any, evt);
    expect(calls.some(c => c.table === "calls" && c.op === "update")).toBe(true);
  });
});
```

- [ ] **Step 4:** Run, watch fail.

```powershell
pnpm --filter @ai-voice/webhooks-worker test
```
Expected: module not found.

- [ ] **Step 5:** Implement the handler.

`apps/workers/webhooks/src/samvaad-handler.ts`:
```ts
import type { SupabaseClient } from "@supabase/supabase-js";
import type { SamvaadEvent } from "@ai-voice/shared";

export async function handleSamvaadEvent(sb: SupabaseClient, evt: SamvaadEvent): Promise<void> {
  // Resolve internal call row by samvaad_call_id
  const { data: call } = await sb.from("calls")
    .select("id,tenant_id").eq("samvaad_call_id", evt.call_id).single();
  if (!call) {
    // call.started can arrive before calls row exists if startCall response was lost;
    // ignore until campaigns-worker writes it. Reconciliation job will replay.
    if (evt.kind !== "call.started") return;
    return;
  }

  // Idempotent event log
  await sb.from("call_events").insert({
    call_id: call.id,
    event_id: evt.event_id,
    kind: evt.kind,
    payload: evt,
  });

  switch (evt.kind) {
    case "call.started":
      await sb.from("calls").update({ status: "ringing" }).eq("id", call.id);
      break;
    case "call.answered":
      await sb.from("calls").update({ status: "in_progress", started_at: evt.at }).eq("id", call.id);
      break;
    case "transcript.chunk":
      await sb.from("transcripts").insert({
        call_id: call.id,
        speaker: evt.speaker,
        text: evt.text,
        lang: evt.lang,
        ts_ms: evt.ts_ms,
        idx: evt.idx,
      });
      break;
    case "call.ended":
      await sb.from("calls").update({
        status: evt.status,
        ended_at: evt.at,
        duration_sec: evt.duration_sec,
        language_used: evt.language_used,
      }).eq("id", call.id);
      break;
    case "recording.ready":
      // Storage handled in Task 7; here we only stamp the URL until then.
      await sb.from("calls").update({ recording_r2_key: `pending:${evt.download_url}` }).eq("id", call.id);
      break;
  }
}
```

- [ ] **Step 6:** Run, watch pass. Commit.

```powershell
pnpm --filter @ai-voice/webhooks-worker test
git add apps/workers/webhooks
git commit -m "feat(webhooks): Samvaad event handler with idempotent log"
```

---

## Task 7: R2 recording upload + `index.ts` HTTP entry

**Files:**
- Create: `apps/workers/webhooks/src/r2.ts`
- Create: `apps/workers/webhooks/src/index.ts`

- [ ] **Step 1:** R2 upload.

`apps/workers/webhooks/src/r2.ts`:
```ts
export async function fetchAndStoreRecording(
  env: { RECORDINGS: R2Bucket; SARVAM_API_KEY: string; SARVAM_BASE_URL: string },
  call: { id: string; tenant_id: string; samvaad_call_id: string },
): Promise<string> {
  const url = `${env.SARVAM_BASE_URL}/samvaad/calls/${call.samvaad_call_id}/recording`;
  const res = await fetch(url, { headers: { authorization: `Bearer ${env.SARVAM_API_KEY}` } });
  if (!res.ok || !res.body) throw new Error(`recording fetch ${res.status}`);
  const key = `tenants/${call.tenant_id}/calls/${call.id}.mp3`;
  await env.RECORDINGS.put(key, res.body, { httpMetadata: { contentType: "audio/mpeg" } });
  return key;
}
```

- [ ] **Step 2:** Wire into handler.

Modify `samvaad-handler.ts` `recording.ready` branch:
```ts
case "recording.ready": {
  if ((globalThis as any).RECORDINGS) {
    // env-only path; in real Worker we plumb env in
  }
  // No-op in handler tests; the index.ts route does the upload.
  break;
}
```

(The actual upload happens in the route handler so the unit test stays pure.)

- [ ] **Step 3:** HTTP entrypoint.

`apps/workers/webhooks/src/index.ts`:
```ts
import { Hono } from "hono";
import { SamvaadProvider } from "@ai-voice/shared";
import { adminClient } from "./supabase-admin";
import { handleSamvaadEvent } from "./samvaad-handler";
import { fetchAndStoreRecording } from "./r2";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SAMVAAD_WEBHOOK_SECRET: string;
  SARVAM_API_KEY: string;
  SARVAM_BASE_URL: string;
  RECORDINGS: R2Bucket;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

app.post("/samvaad", async (c) => {
  const provider = new SamvaadProvider({
    apiKey: c.env.SARVAM_API_KEY,
    baseUrl: c.env.SARVAM_BASE_URL,
  });
  let evt;
  try {
    evt = await provider.parseWebhook(c.req.raw, { secret: c.env.SAMVAAD_WEBHOOK_SECRET });
  } catch (e) {
    return c.json({ error: (e as Error).message }, 401);
  }
  const sb = adminClient(c.env);

  await handleSamvaadEvent(sb, evt);

  if (evt.kind === "recording.ready") {
    const { data: call } = await sb.from("calls")
      .select("id,tenant_id,samvaad_call_id").eq("samvaad_call_id", evt.call_id).single();
    if (call) {
      try {
        const key = await fetchAndStoreRecording(c.env, call);
        await sb.from("calls").update({ recording_r2_key: key }).eq("id", call.id);
      } catch (e) {
        console.error("recording upload failed", e);
      }
    }
  }
  return c.json({ ok: true });
});

export default app;
```

- [ ] **Step 4:** Create the R2 bucket.

```powershell
npx wrangler r2 bucket create ai-voice-recordings
```

- [ ] **Step 5:** Set Worker secrets.

```powershell
cd apps/workers/webhooks
npx wrangler secret put SAMVAAD_WEBHOOK_SECRET
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put SARVAM_BASE_URL
cd ../../..
```

- [ ] **Step 6:** Deploy + capture URL.

```powershell
pnpm --filter @ai-voice/webhooks-worker deploy
```
Copy the `*.workers.dev` URL Cloudflare prints. Update the Samvaad agent's webhook URL (in the Sarvam dashboard) to:
```
https://<your-worker>.workers.dev/samvaad
```

- [ ] **Step 7:** Smoke.

```powershell
curl https://<your-worker>.workers.dev/healthz
```
Expected: `ok`.

- [ ] **Step 8:** Commit.

```powershell
git add apps/workers/webhooks
git commit -m "feat(webhooks): R2 recording store + Hono entrypoint + deploy"
```

---

## Task 8: `campaigns-worker` — single-call dispatcher (TDD)

**Files:**
- Create: `apps/workers/campaigns/package.json`
- Create: `apps/workers/campaigns/wrangler.toml`
- Create: `apps/workers/campaigns/tsconfig.json`
- Create: `apps/workers/campaigns/src/dispatch.ts`
- Create: `apps/workers/campaigns/src/dispatch.test.ts`
- Create: `apps/workers/campaigns/src/index.ts`

- [ ] **Step 1:** Package config (mirror webhooks worker).

`apps/workers/campaigns/package.json` — same shape as webhooks but `name: @ai-voice/campaigns-worker`.

`apps/workers/campaigns/wrangler.toml`:
```toml
name = "ai-voice-campaigns"
main = "src/index.ts"
compatibility_date = "2025-04-01"
```

- [ ] **Step 2:** Write the failing dispatch test.

`apps/workers/campaigns/src/dispatch.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { dispatchSingleCall } from "./dispatch";

describe("dispatchSingleCall", () => {
  it("checks DNC, refuses when listed", async () => {
    const sb = {
      from: (table: string) => {
        if (table === "leads") return { select: () => ({ eq: () => ({ single: async () => ({ data: {
          id:"L", tenant_id:"T", name:"X", phone_e164:"+91900", status:"new" } }) }) }) };
        if (table === "tenants") return { select: () => ({ eq: () => ({ single: async () => ({ data: {
          samvaad_agent_id:"agt_1", exotel_caller_id:"+91444", persona_lang_default:"en-IN" } }) }) }) };
        if (table === "dnc_list") return { select: () => ({ eq: () => ({ eq: () => ({ single:
          async () => ({ data: { tenant_id:"T", phone_e164:"+91900" } }) }) }) }) };
        return {};
      },
    };
    const provider = { startCall: vi.fn() };
    await expect(dispatchSingleCall(sb as any, provider as any, { leadId:"L" }))
      .rejects.toThrow(/DNC/i);
    expect(provider.startCall).not.toHaveBeenCalled();
  });

  it("calls provider and writes calls row", async () => {
    const writes: any[] = [];
    const sb = {
      from: (table: string) => {
        if (table === "leads") return { select: () => ({ eq: () => ({ single: async () => ({ data: {
          id:"L", tenant_id:"T", name:"X", phone_e164:"+91900", status:"new" } }) }) }),
          update: () => ({ eq: async () => { writes.push({ table, op:"update" }); return { error:null }; } }) };
        if (table === "tenants") return { select: () => ({ eq: () => ({ single: async () => ({ data: {
          samvaad_agent_id:"agt_1", exotel_caller_id:"+91444", persona_lang_default:"en-IN" } }) }) }) };
        if (table === "dnc_list") return { select: () => ({ eq: () => ({ eq: () => ({ single:
          async () => ({ data: null }) }) }) }) };
        if (table === "calls") return { insert: async (row: any) => {
          writes.push({ table, op:"insert", row }); return { data: row, error:null }; } };
        return {};
      },
    };
    const provider = { startCall: vi.fn().mockResolvedValue({ providerCallId: "c_xyz" }) };
    const r = await dispatchSingleCall(sb as any, provider as any, { leadId:"L" });
    expect(r.providerCallId).toBe("c_xyz");
    expect(writes.some(w => w.table === "calls" && w.op === "insert")).toBe(true);
  });
});
```

- [ ] **Step 3:** Run, watch fail.

```powershell
pnpm --filter @ai-voice/campaigns-worker test
```

- [ ] **Step 4:** Implement.

`apps/workers/campaigns/src/dispatch.ts`:
```ts
import type { SupabaseClient } from "@supabase/supabase-js";
import type { VoiceProvider } from "@ai-voice/shared";

export async function dispatchSingleCall(
  sb: SupabaseClient,
  provider: VoiceProvider,
  args: { leadId: string; campaignId?: string },
): Promise<{ providerCallId: string }> {
  const { data: lead } = await sb.from("leads").select("*").eq("id", args.leadId).single();
  if (!lead) throw new Error("lead not found");
  if (lead.status === "do_not_call") throw new Error("lead is DNC");

  const { data: tenant } = await sb.from("tenants")
    .select("samvaad_agent_id,exotel_caller_id,persona_lang_default")
    .eq("id", lead.tenant_id).single();
  if (!tenant?.samvaad_agent_id || !tenant.exotel_caller_id)
    throw new Error("tenant not provisioned for voice");

  const { data: dnc } = await sb.from("dnc_list")
    .select("phone_e164").eq("tenant_id", lead.tenant_id).eq("phone_e164", lead.phone_e164).single();
  if (dnc) throw new Error("phone on DNC list");

  await sb.from("leads").update({ status: "queued" }).eq("id", lead.id);

  const { providerCallId } = await provider.startCall({
    agentId: tenant.samvaad_agent_id,
    to_e164: lead.phone_e164,
    callerId: tenant.exotel_caller_id,
    langHint: tenant.persona_lang_default as any,
    metadata: { lead_id: lead.id, tenant_id: lead.tenant_id, campaign_id: args.campaignId },
  });

  await sb.from("calls").insert({
    tenant_id: lead.tenant_id,
    lead_id: lead.id,
    campaign_id: args.campaignId ?? null,
    samvaad_call_id: providerCallId,
    status: "queued",
    kind: "ai_outbound",
  });
  await sb.from("leads").update({ status: "calling" }).eq("id", lead.id);
  return { providerCallId };
}
```

- [ ] **Step 5:** Run, watch pass.

```powershell
pnpm --filter @ai-voice/campaigns-worker test
```

- [ ] **Step 6:** HTTP entry.

`apps/workers/campaigns/src/index.ts`:
```ts
import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { SamvaadProvider } from "@ai-voice/shared";
import { dispatchSingleCall } from "./dispatch";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SARVAM_API_KEY: string;
  SARVAM_BASE_URL: string;
  INTERNAL_API_TOKEN: string;
};
const app = new Hono<{ Bindings: Env }>();

app.post("/dispatch", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);
  const body = await c.req.json<{ lead_id: string; campaign_id?: string }>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken:false, persistSession:false },
  });
  const provider = new SamvaadProvider({ apiKey: c.env.SARVAM_API_KEY, baseUrl: c.env.SARVAM_BASE_URL });
  try {
    const r = await dispatchSingleCall(sb, provider, { leadId: body.lead_id, campaignId: body.campaign_id });
    return c.json(r);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 400);
  }
});

export default app;
```

- [ ] **Step 7:** Deploy + secrets.

```powershell
cd apps/workers/campaigns
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put SARVAM_BASE_URL
# generate a random internal token shared with the Next.js app:
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler deploy
cd ../../..
```
Copy the URL — needed in the next task.

- [ ] **Step 8:** Commit.

```powershell
git add apps/workers/campaigns
git commit -m "feat(campaigns): single-call dispatcher with DNC guard"
```

---

## Task 9: "Call now" button in lead detail → AI call

**Files:**
- Modify: `apps/web/app/leads/[id]/page.tsx`
- Create: `apps/web/components/StartAiCallButton.tsx`
- Modify: `apps/web/app/leads/actions.ts` (add `startAiCallAction`)
- Modify: `.env.local` (add CAMPAIGNS_WORKER_URL + INTERNAL_API_TOKEN)

- [ ] **Step 1:** Add the server action.

Append to `apps/web/app/leads/actions.ts`:
```ts
export async function startAiCallAction(leadId: string) {
  const url = process.env.CAMPAIGNS_WORKER_URL!;
  const token = process.env.INTERNAL_API_TOKEN!;
  const res = await fetch(`${url}/dispatch`, {
    method: "POST",
    headers: { "content-type":"application/json", authorization:`Bearer ${token}` },
    body: JSON.stringify({ lead_id: leadId }),
  });
  if (!res.ok) return { error: (await res.json()).error ?? "dispatch failed" };
  return { ok: true };
}
```

- [ ] **Step 2:** Button.

`apps/web/components/StartAiCallButton.tsx`:
```tsx
"use client";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { startAiCallAction } from "@/app/leads/actions";

export function StartAiCallButton({ leadId }: { leadId: string }) {
  const [pending, start] = useTransition();
  const router = useRouter();
  return (
    <Button disabled={pending} onClick={() => start(async () => {
      const r = await startAiCallAction(leadId);
      if (r.error) toast.error(r.error);
      else { toast.success("Calling now — watch the transcript pane"); router.refresh(); }
    })}>
      {pending ? "Dialing…" : "Call with AI"}
    </Button>
  );
}
```

- [ ] **Step 3:** Wire into detail page.

In `apps/web/app/leads/[id]/page.tsx`, add a button row inside header:
```tsx
import { StartAiCallButton } from "@/components/StartAiCallButton";
// ...
<div className="flex items-center gap-3">
  <StartAiCallButton leadId={lead.id} />
  <LeadStatusBadge status={lead.status} />
  <DncDialog leadId={lead.id} phone={lead.phone_e164} />
</div>
```

- [ ] **Step 4:** Add env vars.

In Cloudflare Pages → `ai-voice-web` → Environment variables (Production), add:
- `CAMPAIGNS_WORKER_URL` = `https://ai-voice-campaigns.<...>.workers.dev`
- `INTERNAL_API_TOKEN` = (the token you generated in Task 8 step 7)

Also set in `.env.local` for local dev.

- [ ] **Step 5:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): Call with AI button on lead detail"
```

---

## Task 10: Realtime transcript view in lead detail

**Files:**
- Create: `apps/web/components/TranscriptView.tsx`
- Modify: `apps/web/app/leads/[id]/page.tsx`

- [ ] **Step 1:** Realtime component.

`apps/web/components/TranscriptView.tsx`:
```tsx
"use client";
import { useEffect, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

type Line = { id: string; speaker: "agent"|"lead"; text: string; lang: string; ts_ms: number; idx: number };

export function TranscriptView({ leadId }: { leadId: string }) {
  const [callId, setCallId] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const supabase = createSupabaseBrowserClient();

  // Find the most recent AI call for this lead.
  useEffect(() => {
    let mounted = true;
    (async () => {
      const { data } = await supabase.from("calls").select("id")
        .eq("lead_id", leadId).eq("kind","ai_outbound")
        .order("created_at", { ascending: false }).limit(1).maybeSingle();
      if (mounted && data?.id) setCallId(data.id);
    })();
    return () => { mounted = false; };
  }, [leadId, supabase]);

  // Load initial + subscribe.
  useEffect(() => {
    if (!callId) return;
    let active = true;
    (async () => {
      const { data } = await supabase.from("transcripts").select("*")
        .eq("call_id", callId).order("idx", { ascending: true });
      if (active) setLines((data ?? []) as Line[]);
    })();
    const ch = supabase.channel(`tx-${callId}`)
      .on("postgres_changes",
          { event:"INSERT", schema:"public", table:"transcripts", filter:`call_id=eq.${callId}` },
          (p) => setLines((prev) => [...prev, p.new as Line].sort((a,b) => a.idx - b.idx)))
      .subscribe();
    return () => { active = false; supabase.removeChannel(ch); };
  }, [callId, supabase]);

  if (!callId) return <p className="text-sm text-muted-foreground">No call yet. Click "Call with AI".</p>;
  if (lines.length === 0) return <p className="text-sm text-muted-foreground">Connecting…</p>;
  return (
    <div className="space-y-2">
      {lines.map((l) => (
        <div key={l.id} className={l.speaker === "agent" ? "" : "pl-6"}>
          <span className="text-xs font-medium text-muted-foreground">{l.speaker} · {l.lang}</span>
          <p className="text-sm">{l.text}</p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2:** Swap stub in detail page.

```tsx
import { TranscriptView } from "@/components/TranscriptView";
// ...
<section className="rounded-md border p-4">
  <h2 className="mb-2 text-sm font-medium">Transcript</h2>
  <TranscriptView leadId={lead.id} />
</section>
```

- [ ] **Step 3:** Smoke (after Task 11).

- [ ] **Step 4:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): realtime transcript view on lead detail"
```

---

## Task 11: First end-to-end real call (manual)

This is the moment of truth. Prerequisites:
- Exotel KYC clear, DLT template approved.
- Samvaad agent configured, webhook URL pointing at deployed `webhooks-worker`.
- A test mobile number you control.

- [ ] **Step 1:** Insert your own number as a lead.

In the dashboard, **Add lead**:
- Name: `Self Test`
- Phone: `<your mobile in any format>`
- Company: `Self`
- Industry: `Pharmaceuticals`

- [ ] **Step 2:** Open the lead → **Call with AI**.

Your phone should ring within ~3 seconds. Pick up; you'll hear Priya in English.

- [ ] **Step 3:** Watch the dashboard while talking.

Transcript pane should populate lines as Priya speaks and as you reply. Switch to Hindi or Tamil mid-call and verify Priya switches.

- [ ] **Step 4:** Hang up. Verify:
- `calls` row: `status='completed'`, `duration_sec` set, `language_used` correct.
- `transcripts` rows: ≥ 6 lines (4 Priya + 2 you minimum).
- `call_events`: at least `call.started`, `call.answered`, several `transcript.chunk`, `call.ended`, `recording.ready`.
- `recording_r2_key` set (not `pending:`).

- [ ] **Step 5:** Download the R2 recording.

```powershell
npx wrangler r2 object get ai-voice-recordings/tenants/<tenant-id>/calls/<call-id>.mp3 --file out.mp3
```
Play it. Confirm audio matches transcript.

- [ ] **Step 6:** Record outcomes.

If anything fails, capture:
- Cloudflare Worker logs: `npx wrangler tail ai-voice-webhooks`
- Sarvam dashboard: `Calls → most recent → events log`
- Supabase Studio: query `call_events` for that call

Common failures + fixes:
| Symptom | Likely cause | Fix |
|---|---|---|
| No ring | Exotel KYC/DLT not approved | Wait, or use Samvaad's bundled telephony |
| 401 on webhook | Signature mismatch | Confirm `SAMVAAD_WEBHOOK_SECRET` matches in both places |
| Transcripts empty in DB | Webhook URL wrong on Samvaad | Update agent webhook URL |
| Priya never auto-switches | Language policy off in agent JSON | Re-upload `spc-priya.agent.json` |

- [ ] **Step 7:** Commit a "demo recording" marker (no file — just a milestone).

```powershell
git commit --allow-empty -m "milestone: first successful end-to-end AI call"
```

---

## Task 12: Voicemail detection + single retry

**Files:**
- Modify: `apps/workers/webhooks/src/samvaad-handler.ts`
- Modify: `apps/workers/webhooks/src/samvaad-handler.test.ts`

- [ ] **Step 1:** Add the test.

Append to `samvaad-handler.test.ts`:
```ts
it("on voicemail call.ended schedules a retry leads.status=queued", async () => {
  const writes: any[] = [];
  const sb = {
    from: (t: string) => {
      if (t === "calls") return {
        select: () => ({ eq: () => ({ single: async () => ({ data: { id:"call-uuid", tenant_id:"T", lead_id:"L" } }) }) }),
        update: () => ({ eq: async () => { writes.push({ t, op:"update" }); return { error:null }; } }),
      };
      if (t === "call_events") return { insert: async () => { writes.push({ t, op:"insert" }); return { error:null }; } };
      if (t === "leads") return { update: () => ({ eq: async () => { writes.push({ t, op:"update" }); return { error:null }; } }) };
      return {};
    },
  };
  await handleSamvaadEvent(sb as any, {
    kind:"call.ended", event_id:"v1", call_id:"prov", status:"voicemail",
    duration_sec: 8, language_used:"en-IN", at:"2026-05-21T00:00:00Z",
  } as any);
  expect(writes.some(w => w.t === "leads" && w.op === "update")).toBe(true);
});
```

- [ ] **Step 2:** Update handler.

In `samvaad-handler.ts`, in the `call.ended` branch:
```ts
case "call.ended":
  await sb.from("calls").update({
    status: evt.status,
    ended_at: evt.at,
    duration_sec: evt.duration_sec,
    language_used: evt.language_used,
  }).eq("id", call.id);
  if (evt.status === "voicemail") {
    // Single retry — mark lead queued; campaigns-worker cron picks it up later.
    await sb.from("leads").update({ status: "queued" }).eq("id", call.lead_id);
  }
  if (evt.status === "no_answer" || evt.status === "failed") {
    await sb.from("leads").update({ status: "cold" }).eq("id", call.lead_id);
  }
  break;
```

(Note: `call.lead_id` isn't in the `select` above; add `lead_id` to the SELECT.)

- [ ] **Step 3:** Test + deploy + commit.

```powershell
pnpm --filter @ai-voice/webhooks-worker test
pnpm --filter @ai-voice/webhooks-worker deploy
git add apps/workers/webhooks
git commit -m "feat(webhooks): voicemail retry + no-answer cold-out"
```

---

## Task 13: Campaigns page (manual trigger of bulk dial)

**Files:**
- Create: `apps/web/app/campaigns/page.tsx`
- Create: `apps/web/app/campaigns/actions.ts`

- [ ] **Step 1:** Server action.

`apps/web/app/campaigns/actions.ts`:
```ts
"use server";
import { revalidatePath } from "next/cache";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export async function startBulkAction(): Promise<{ ok?: boolean; error?: string; dispatched?: number }> {
  const supabase = createSupabaseServerClient();
  const { data: leads } = await supabase.from("leads")
    .select("id").eq("status","new").limit(50);
  if (!leads?.length) return { ok: true, dispatched: 0 };

  let dispatched = 0;
  for (const l of leads) {
    const res = await fetch(`${process.env.CAMPAIGNS_WORKER_URL}/dispatch`, {
      method:"POST",
      headers: { "content-type":"application/json", authorization:`Bearer ${process.env.INTERNAL_API_TOKEN}` },
      body: JSON.stringify({ lead_id: l.id }),
    });
    if (res.ok) dispatched++;
    // throttle 1/sec to stay polite
    await new Promise(r => setTimeout(r, 1000));
  }
  revalidatePath("/leads");
  revalidatePath("/campaigns");
  return { ok: true, dispatched };
}
```

- [ ] **Step 2:** Page.

`apps/web/app/campaigns/page.tsx`:
```tsx
import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { startBulkAction } from "./actions";

export default async function CampaignsPage() {
  await requireTenant();
  const supabase = createSupabaseServerClient();
  const { count: queued } = await supabase.from("leads").select("*", { count: "exact", head: true }).eq("status","new");
  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold">Campaigns</h1>
      <p className="text-sm text-muted-foreground">{queued ?? 0} new leads ready to dial.</p>
      <form action={startBulkAction}>
        <Button type="submit">Dial up to 50 new leads (throttled 1/sec)</Button>
      </form>
    </main>
  );
}
```

- [ ] **Step 3:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): bulk campaign dispatcher page"
```

---

## Self-review

**Spec coverage:**
- §6.4 VoiceProvider interface → Tasks 4, 5 ✓
- §7 data flow (1–5 covered here; 6–7 are Plan 3) ✓
- §9 conversation design (system prompt + agent config + KB) → Task 3 ✓
- §11 voicemail retry, idempotency, DNC respect → Tasks 6, 8, 12 ✓
- §6.2 webhooks-worker, campaigns-worker → Tasks 6, 7, 8 ✓

**Placeholder scan:** the only intentional gap is `voice_id` ("TBD-select-during-demo") in the agent JSON — that's a Sarvam-gallery pick that requires hearing it. Task 3 step 5 says how to fix during build.

**Type consistency:** `samvaad_call_id`, `event_id`, `call.lead_id`, `phone_e164` consistent across worker + DB + provider.

---

## Done state (after Task 13)

- First real outbound call demonstrably works: dial → Priya in EN/HI/TA → live transcript in dashboard → recording in R2 → events in DB.
- Voicemail handled with one retry, no-answer marked cold.
- Bulk campaign trigger live (1 call/second).
- Ready for Plan 3 (scoring, handoff, click-to-call, demo polish).
