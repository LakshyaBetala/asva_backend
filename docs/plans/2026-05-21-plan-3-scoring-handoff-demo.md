# Plan 3 of 3 — Scoring, Handoff, Click-to-Call, Demo Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`.

**Goal:** Close the loop. After each call: a scoring worker classifies Hot/Warm/Cold, extracts structured fields, writes a 2–4 sentence summary, and saves all of it to the CRM. Hot leads ping a human rep on WhatsApp + email. The rep opens the lead and either taps **Call now** (mobile → tel:, desktop → Exotel bridge) to convert. We finish with a 6-scenario E2E demo run and pitch polish for SPC.

**Prerequisites:** Plans 1 & 2 complete. Real calls work end-to-end.

**Architecture:** A new `score-worker` triggers on `call.ended` (invoked by `webhooks-worker`), pulls the transcript, calls Sarvam LLM with the scoring prompt, validates JSON, writes `lead_scores`. A `handoff-worker` generates wa.me + Resend email on Hot. The dashboard adds a Score Badge, an AI Summary card, and a **Call now** human-takeover button that uses Exotel `connect_two_numbers` (desktop) or a `tel:` link (mobile).

**Tech Stack:** Cloudflare Workers (Hono), Sarvam LLM API, Resend, wa.me deeplinks, Exotel REST API.

**Spec reference:** `docs/specs/2026-05-21-spc-voice-agent-design.md` §6.2, §7 (steps 6–7), §9.5 (scoring rubric), §12 (testing), §13 (M5 polish).

---

## File structure added by this plan

```
apps/workers/
├── score/
│   ├── package.json
│   ├── wrangler.toml
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts
│       ├── score.ts
│       ├── score.test.ts
│       └── prompt.ts
├── handoff/
│   ├── package.json
│   ├── wrangler.toml
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts
│       ├── handoff.ts
│       ├── handoff.test.ts
│       └── wa-email.ts
└── clicktocall/
    ├── package.json
    ├── wrangler.toml
    ├── tsconfig.json
    └── src/
        ├── index.ts
        ├── exotel.ts
        └── exotel.test.ts

packages/shared/src/
├── prompts/scoring.md
└── scoring-schema.ts

tests/fixtures/golden-transcripts/
├── hot_01.json     (transcript + expected score)
├── hot_02.json
├── ...
├── warm_01.json
├── ...
└── cold_01.json
(5 hot, 7 warm, 8 cold = 20 fixtures)

apps/web/
├── components/
│   ├── ScoreBadge.tsx
│   ├── SummaryCard.tsx
│   ├── CallNowButton.tsx
│   └── ExtractedFields.tsx
└── app/leads/[id]/page.tsx              (UPDATED — adds Summary, Score, Call now)
```

---

## Task 1: Scoring schema + prompt

**Files:**
- Create: `packages/shared/src/scoring-schema.ts`
- Create: `packages/shared/src/prompts/scoring.md`

- [ ] **Step 1:** Zod schema.

`packages/shared/src/scoring-schema.ts`:
```ts
import { z } from "zod";

export const LeadScore = z.object({
  decision_maker: z.boolean(),
  industry: z.string().nullable(),
  chemicals: z.array(z.string()),
  monthly_volume_kg: z.number().nullable(),
  current_supplier: z.string().nullable(),
  supplier_pain: z.array(z.enum(["price","delivery","quality","support","none"])),
  timeline: z.enum(["now","1-3mo","exploring","unknown"]),
  decision_maker_email: z.string().email().nullable(),
  decision_maker_whatsapp: z.string().nullable(),
  classification: z.enum(["hot","warm","cold"]),
  score_0_100: z.number().int().min(0).max(100),
  reason: z.string().min(1),
  summary: z.string().min(1),
  next_action: z.string().min(1),
  call_quality_flags: z.array(z.enum(["voicemail","wrong_number","language_struggle","audio_poor","none"])),
});
export type LeadScore = z.infer<typeof LeadScore>;
```

- [ ] **Step 2:** Prompt.

`packages/shared/src/prompts/scoring.md`:
```markdown
You are an analyst scoring a sales-qualification call for Supreme
Petrochemicals (SPC), a Chennai chemical distributor.

You will receive a full call transcript. Output ONLY a JSON object
matching this schema (no prose, no markdown fences):

{
  "decision_maker": boolean,
  "industry": string | null,
  "chemicals": string[],
  "monthly_volume_kg": number | null,
  "current_supplier": string | null,
  "supplier_pain": ("price"|"delivery"|"quality"|"support"|"none")[],
  "timeline": "now" | "1-3mo" | "exploring" | "unknown",
  "decision_maker_email": string | null,
  "decision_maker_whatsapp": string | null,
  "classification": "hot" | "warm" | "cold",
  "score_0_100": integer 0..100,
  "reason": "one sentence",
  "summary": "2-4 sentences for the human rep",
  "next_action": "one sentence recommended next step",
  "call_quality_flags": ("voicemail"|"wrong_number"|"language_struggle"|"audio_poor"|"none")[]
}

Classification rules:
- HOT (score 70-100): is decision-maker AND timeline in {now, 1-3mo}
  AND (uses bulk volumes OR has supplier_pain not "none").
- COLD (0-30): says "not interested" / wrong number / clearly
  off-target / not a decision-maker with no referral path.
- WARM (31-69): everything else.

LANGUAGE NORMALIZATION (mandatory):
The conversation may be in English, Hindi, or Tamil — possibly mixed.
You MUST produce ALL outputs in English. Translate any Hindi or Tamil
content into clear English. This includes:
  - summary, reason, next_action: written in English prose.
  - industry, current_supplier: English nouns.
  - chemicals[]: English chemical names (e.g. "glycerine" not "ग्लिसरीन").
  - supplier_pain[], timeline, classification, call_quality_flags:
    must use the exact English enum values from the schema.
The verbatim Hindi/Tamil utterances are preserved separately in the
transcripts table — do NOT include foreign-script text in any JSON
field you return.

Be conservative. If the transcript is too short or unclear,
classification = cold, score ≤ 25, reason = "insufficient signal".
Always populate summary and next_action even on cold.
```

- [ ] **Step 3:** Re-export + commit.

```ts
// packages/shared/src/index.ts
export * from "./scoring-schema";
```
```powershell
git add packages/shared
git commit -m "feat(shared): scoring schema + LLM prompt"
```

---

## Task 2: Golden transcripts (20 fixtures)

**Files:**
- Create: `tests/fixtures/golden-transcripts/hot_01.json` … `cold_08.json` (20 files)

- [ ] **Step 1:** Fixture format.

Each file:
```json
{
  "transcript": [
    {"speaker":"agent","text":"Namaste, I'm Priya from Supreme Petrochemicals...","lang":"en-IN"},
    {"speaker":"lead","text":"Yes, I'm the procurement head at Acme Pharma","lang":"en-IN"},
    ...
  ],
  "expected": {
    "classification":"hot",
    "score_range":[75,95],
    "decision_maker":true,
    "timeline":"now"
  }
}
```

- [ ] **Step 2:** Write all 20. Use the same JSON shape. The five HOT fixtures should depict engaged procurement decision-makers in target industries with concrete chemicals + bulk volume + supplier pain + immediate timeline. The eight COLD fixtures depict early hangups, wrong numbers, non-decision-makers, voicemail. The seven WARM fixtures are partials — decision-maker but exploring, or interested but unclear volume. Write them as a single batch so the rubric judges them consistently. To keep this concrete, here is one of each:

`tests/fixtures/golden-transcripts/hot_01.json`:
```json
{
  "transcript": [
    {"speaker":"agent","text":"Namaste, I'm Priya from Supreme Petrochemicals, Chennai. Is this a good time for a quick 30-second conversation?","lang":"en-IN"},
    {"speaker":"lead","text":"Yes go ahead, I am Ravi, head of procurement at Acme Pharma","lang":"en-IN"},
    {"speaker":"agent","text":"Thank you Ravi. We supply industrial chemicals to pharma companies — may I ask which chemicals you currently source?","lang":"en-IN"},
    {"speaker":"lead","text":"Mainly glycerine and acetic acid, around 8 tonnes per month combined","lang":"en-IN"},
    {"speaker":"agent","text":"And how is your current supplier doing on pricing and delivery?","lang":"en-IN"},
    {"speaker":"lead","text":"Delivery has been delayed twice this quarter, that hurts our production. We are looking at alternatives right now","lang":"en-IN"},
    {"speaker":"agent","text":"That's exactly where SPC's 4-hour quote SLA helps. Can we send you a quote within 4 hours for glycerine and acetic acid?","lang":"en-IN"},
    {"speaker":"lead","text":"Yes please. My email is ravi@acmepharma.in","lang":"en-IN"}
  ],
  "expected": {
    "classification":"hot",
    "score_range":[80,95],
    "decision_maker":true,
    "timeline":"now",
    "must_include": {"chemicals":["glycerine","acetic acid"], "supplier_pain":["delivery"]}
  }
}
```

`tests/fixtures/golden-transcripts/cold_01.json`:
```json
{
  "transcript": [
    {"speaker":"agent","text":"Namaste, I'm Priya from Supreme Petrochemicals...","lang":"en-IN"},
    {"speaker":"lead","text":"Not interested, do not call this number again","lang":"en-IN"},
    {"speaker":"agent","text":"Understood, thanks for your time. We won't contact you again.","lang":"en-IN"}
  ],
  "expected": {
    "classification":"cold",
    "score_range":[0,20],
    "decision_maker":false,
    "timeline":"unknown",
    "must_include": {"call_quality_flags":["none"]}
  }
}
```

`tests/fixtures/golden-transcripts/warm_01.json`:
```json
{
  "transcript": [
    {"speaker":"agent","text":"Namaste, I'm Priya from Supreme Petrochemicals...","lang":"en-IN"},
    {"speaker":"lead","text":"I am the lab head, not procurement but we do buy chemicals","lang":"en-IN"},
    {"speaker":"agent","text":"What chemicals does your lab use?","lang":"en-IN"},
    {"speaker":"lead","text":"Some titanium dioxide, but only small quantities, maybe 50 kg a month","lang":"en-IN"},
    {"speaker":"agent","text":"Are you exploring new suppliers right now?","lang":"en-IN"},
    {"speaker":"lead","text":"Not actively, but you can send information. I will share with our procurement team","lang":"en-IN"}
  ],
  "expected": {
    "classification":"warm",
    "score_range":[35,60],
    "decision_maker":false,
    "timeline":"exploring"
  }
}
```

(Write the remaining 17 in the same shape — vary languages: 4 in `hi-IN`, 4 in `ta-IN`, the rest `en-IN`.)

- [ ] **Step 3:** Commit.

```powershell
git add tests/fixtures
git commit -m "test(fixtures): 20 golden transcripts for scoring rubric"
```

---

## Task 3: `score-worker` (TDD against golden fixtures)

**Files:**
- Create: `apps/workers/score/package.json`
- Create: `apps/workers/score/wrangler.toml`
- Create: `apps/workers/score/tsconfig.json`
- Create: `apps/workers/score/src/prompt.ts`
- Create: `apps/workers/score/src/score.ts`
- Create: `apps/workers/score/src/score.test.ts`
- Create: `apps/workers/score/src/index.ts`

- [ ] **Step 1:** Package config (same pattern as webhooks worker). Add deps: `hono`, `@supabase/supabase-js`, `@ai-voice/shared`, `zod`.

- [ ] **Step 2:** Prompt loader.

`apps/workers/score/src/prompt.ts`:
```ts
// In production we read the markdown via shared package; for Workers the
// markdown is inlined at build via `?raw` import or simply copied as a
// string. Hard-code here to keep the Worker self-contained.
export const SCORING_PROMPT = `... full text from packages/shared/src/prompts/scoring.md ...`;
```
**Implementation note:** Paste the prompt text from Task 1. Keep one source of truth — the markdown file — and use a tiny build step (`pnpm tsx scripts/inline-prompt.ts`) or accept duplication for now and remember to sync.

- [ ] **Step 3:** Failing test against golden fixtures.

`apps/workers/score/src/score.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { scoreTranscript } from "./score";

// Mock Sarvam LLM — for unit tests we stub the network call and assert
// shape; the rubric quality bar runs as a separate evaluation script.
const FIXTURE_DIR = join(__dirname, "../../../../tests/fixtures/golden-transcripts");

describe("scoreTranscript (shape only)", () => {
  it("validates and returns a LeadScore for a stub LLM", async () => {
    const fixture = JSON.parse(readFileSync(join(FIXTURE_DIR, "hot_01.json"), "utf8"));
    const llm = async () => JSON.stringify({
      decision_maker: true, industry: "Pharmaceuticals",
      chemicals: ["glycerine","acetic acid"], monthly_volume_kg: 8000,
      current_supplier: "competitor", supplier_pain: ["delivery"],
      timeline: "now", decision_maker_email: "ravi@acmepharma.in",
      decision_maker_whatsapp: null, classification: "hot",
      score_0_100: 85, reason: "decision-maker, now, bulk, supplier pain",
      summary: "Ravi at Acme Pharma...", next_action: "Send quote for glycerine + acetic acid",
      call_quality_flags: ["none"],
    });
    const score = await scoreTranscript(fixture.transcript, { callLlm: llm });
    expect(score.classification).toBe("hot");
    expect(score.score_0_100).toBeGreaterThanOrEqual(80);
  });

  it("retries once on invalid JSON, falls back to needs_review", async () => {
    let calls = 0;
    const llm = async () => { calls++; return "not json"; };
    await expect(scoreTranscript([{ speaker:"agent", text:"hi", lang:"en-IN" }], { callLlm: llm }))
      .rejects.toThrow(/needs_review/i);
    expect(calls).toBe(2);
  });
});

// Evaluation suite — runs LLM live; skipped in CI without API key.
const fixtures = readdirSync(FIXTURE_DIR).filter(f => f.endsWith(".json"));
describe.skipIf(!process.env.SARVAM_API_KEY)("rubric quality (live LLM)", () => {
  it.each(fixtures)("%s — classification matches expected", async (file) => {
    const fixture = JSON.parse(readFileSync(join(FIXTURE_DIR, file), "utf8"));
    const llm = async (prompt: string) => {
      // call Sarvam LLM here using fetch; keep config in env.
      const res = await fetch(`${process.env.SARVAM_BASE_URL}/chat/completions`, {
        method:"POST",
        headers: { authorization:`Bearer ${process.env.SARVAM_API_KEY}`, "content-type":"application/json" },
        body: JSON.stringify({
          model: "sarvam-105b", temperature: 0,
          response_format: { type: "json_object" },
          messages: [{ role: "user", content: prompt }],
        }),
      });
      const j = await res.json();
      return j.choices[0].message.content;
    };
    const score = await scoreTranscript(fixture.transcript, { callLlm: llm });
    expect(score.classification).toBe(fixture.expected.classification);
    expect(score.score_0_100).toBeGreaterThanOrEqual(fixture.expected.score_range[0]);
    expect(score.score_0_100).toBeLessThanOrEqual(fixture.expected.score_range[1]);
  });
});
```

- [ ] **Step 4:** Implementation.

`apps/workers/score/src/score.ts`:
```ts
import { LeadScore } from "@ai-voice/shared";
import { SCORING_PROMPT } from "./prompt";

export type TranscriptLine = { speaker: "agent" | "lead"; text: string; lang: string };

function buildPrompt(transcript: TranscriptLine[]): string {
  const body = transcript.map(l => `${l.speaker.toUpperCase()} (${l.lang}): ${l.text}`).join("\n");
  return `${SCORING_PROMPT}\n\n--- TRANSCRIPT ---\n${body}\n--- END ---`;
}

export async function scoreTranscript(
  transcript: TranscriptLine[],
  opts: { callLlm: (prompt: string) => Promise<string> },
) {
  const prompt = buildPrompt(transcript);
  for (let attempt = 0; attempt < 2; attempt++) {
    const raw = await opts.callLlm(prompt);
    try {
      const json = JSON.parse(raw);
      const parsed = LeadScore.parse(json);
      // Reject if any field still contains Devanagari (Hindi) or Tamil script —
      // forces the LLM to actually normalize, not just label.
      const haystack = JSON.stringify({
        s: parsed.summary, r: parsed.reason, n: parsed.next_action,
        ind: parsed.industry, cs: parsed.current_supplier, ch: parsed.chemicals,
      });
      if (/[ऀ-ॿ]|[஀-௿]/.test(haystack)) {
        if (attempt === 1) throw new Error("scoring failed: non-English content in summary fields — needs_review");
        continue;
      }
      return parsed;
    } catch (_) {
      if (attempt === 1) throw new Error("scoring failed: needs_review");
    }
  }
  throw new Error("unreachable");
}
```

- [ ] **Step 5:** Sarvam LLM call from Worker.

Add to `score.ts`:
```ts
export async function callSarvamLlm(
  env: { SARVAM_BASE_URL: string; SARVAM_API_KEY: string },
  prompt: string,
): Promise<string> {
  const res = await fetch(`${env.SARVAM_BASE_URL}/chat/completions`, {
    method:"POST",
    headers: { authorization:`Bearer ${env.SARVAM_API_KEY}`, "content-type":"application/json" },
    body: JSON.stringify({
      model: "sarvam-105b",
      temperature: 0,
      response_format: { type: "json_object" },
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!res.ok) throw new Error(`sarvam llm ${res.status}: ${await res.text()}`);
  const j = await res.json<any>();
  return j.choices[0].message.content as string;
}
```

- [ ] **Step 6:** HTTP entry.

`apps/workers/score/src/index.ts`:
```ts
import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { scoreTranscript, callSarvamLlm } from "./score";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SARVAM_BASE_URL: string;
  SARVAM_API_KEY: string;
  INTERNAL_API_TOKEN: string;
  HANDOFF_WORKER_URL: string;
};
const app = new Hono<{ Bindings: Env }>();

app.post("/score", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);
  const { call_id } = await c.req.json<{ call_id: string }>();

  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken:false, persistSession:false },
  });

  const { data: call } = await sb.from("calls").select("id,lead_id,tenant_id").eq("id", call_id).single();
  if (!call) return c.json({ error: "call not found" }, 404);

  const { data: lines } = await sb.from("transcripts").select("speaker,text,lang").eq("call_id", call.id).order("idx");
  if (!lines || lines.length === 0) {
    await sb.from("leads").update({ status: "needs_review" }).eq("id", call.lead_id);
    return c.json({ error: "empty transcript" }, 400);
  }

  let score;
  try {
    score = await scoreTranscript(lines as any, { callLlm: (p) => callSarvamLlm(c.env, p) });
  } catch (e) {
    await sb.from("leads").update({ status: "needs_review" }).eq("id", call.lead_id);
    return c.json({ error: (e as Error).message }, 500);
  }

  await sb.from("lead_scores").insert({
    lead_id: call.lead_id,
    call_id: call.id,
    classification: score.classification,
    score_0_100: score.score_0_100,
    reason: score.reason,
    summary: score.summary,
    next_action: score.next_action,
    extracted: {
      decision_maker: score.decision_maker,
      industry: score.industry,
      chemicals: score.chemicals,
      monthly_volume_kg: score.monthly_volume_kg,
      current_supplier: score.current_supplier,
      supplier_pain: score.supplier_pain,
      timeline: score.timeline,
      decision_maker_email: score.decision_maker_email,
      decision_maker_whatsapp: score.decision_maker_whatsapp,
    },
    call_quality_flags: score.call_quality_flags,
  });
  await sb.from("leads").update({ status: score.classification }).eq("id", call.lead_id);

  if (score.classification === "hot") {
    await fetch(`${c.env.HANDOFF_WORKER_URL}/handoff`, {
      method: "POST",
      headers: { "content-type":"application/json", authorization:`Bearer ${c.env.INTERNAL_API_TOKEN}` },
      body: JSON.stringify({ lead_id: call.lead_id, call_id: call.id }),
    });
  }

  return c.json({ ok: true, classification: score.classification });
});

export default app;
```

- [ ] **Step 7:** Run tests, deploy, commit.

```powershell
pnpm --filter @ai-voice/score-worker test
cd apps/workers/score
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put SARVAM_BASE_URL
npx wrangler secret put SARVAM_API_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put HANDOFF_WORKER_URL  # placeholder for now; set after Task 4 deploys
npx wrangler deploy
cd ../../..
git add apps/workers/score
git commit -m "feat(score): LLM scoring worker with golden-fixture tests"
```

- [ ] **Step 8:** Wire `webhooks-worker` to call the score worker on `call.ended`.

Modify `apps/workers/webhooks/src/samvaad-handler.ts` — accept an env-bound notify function:
```ts
export async function handleSamvaadEvent(
  sb: SupabaseClient,
  evt: SamvaadEvent,
  triggers?: { onCallEnded?: (callId: string) => Promise<void> },
): Promise<void> {
  // ... existing code ...
  case "call.ended":
    // ... existing update ...
    if (evt.status === "completed" && triggers?.onCallEnded) {
      // fire and forget; idempotency safe because score-worker checks transcript count
      await triggers.onCallEnded(call.id);
    }
    break;
}
```

Modify `apps/workers/webhooks/src/index.ts` to pass:
```ts
await handleSamvaadEvent(sb, evt, {
  onCallEnded: async (callId) => {
    await fetch(`${c.env.SCORE_WORKER_URL}/score`, {
      method:"POST",
      headers: { "content-type":"application/json", authorization:`Bearer ${c.env.INTERNAL_API_TOKEN}` },
      body: JSON.stringify({ call_id: callId }),
    });
  },
});
```

Add `SCORE_WORKER_URL` + `INTERNAL_API_TOKEN` secrets to webhooks worker. Redeploy.

```powershell
cd apps/workers/webhooks
npx wrangler secret put SCORE_WORKER_URL
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler deploy
cd ../../..
git add apps/workers/webhooks
git commit -m "feat(webhooks): trigger score-worker on call.ended"
```

---

## Task 4: `handoff-worker` — WhatsApp + email (TDD)

**Files:**
- Create: `apps/workers/handoff/package.json`, `wrangler.toml`, `tsconfig.json`
- Create: `apps/workers/handoff/src/wa-email.ts`
- Create: `apps/workers/handoff/src/handoff.ts`
- Create: `apps/workers/handoff/src/handoff.test.ts`
- Create: `apps/workers/handoff/src/index.ts`

- [ ] **Step 1:** Helpers.

`apps/workers/handoff/src/wa-email.ts`:
```ts
export function buildWaLink(repWhatsapp: string, message: string): string {
  const e164 = repWhatsapp.replace(/[^\d]/g,"");
  return `https://wa.me/${e164}?text=${encodeURIComponent(message)}`;
}

export function buildHotLeadMessage(args: {
  leadName: string; company: string | null; phone: string; score: number;
  summary: string; chemicals: string[]; timeline: string; nextAction: string;
  leadUrl: string;
}): string {
  return [
    `🔥 Hot lead — score ${args.score}/100`,
    `${args.leadName} · ${args.company ?? "—"} · ${args.phone}`,
    `Interested in: ${args.chemicals.join(", ") || "—"} · Timeline: ${args.timeline}`,
    ``,
    args.summary,
    ``,
    `Next action: ${args.nextAction}`,
    `Open lead: ${args.leadUrl}`,
  ].join("\n");
}

export async function sendResendEmail(
  apiKey: string,
  args: { to: string; from: string; subject: string; text: string },
): Promise<void> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!res.ok) throw new Error(`resend ${res.status}: ${await res.text()}`);
}
```

- [ ] **Step 2:** Failing test.

`apps/workers/handoff/src/handoff.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { handleHandoff } from "./handoff";

describe("handleHandoff", () => {
  it("inserts WhatsApp + email handoff rows for a hot lead", async () => {
    const writes: any[] = [];
    const sb = {
      from: (t: string) => {
        if (t === "leads") return { select: () => ({ eq: () => ({ single: async () => ({
          data: { id:"L", tenant_id:"T", name:"Ravi", phone_e164:"+919876543210", company:"Acme", assigned_to:"u1" } }) }) }) };
        if (t === "users") return { select: () => ({ eq: () => ({ single: async () => ({
          data: { id:"u1", email:"rep@spc.test", whatsapp:"+919000000000" } }) }) }) };
        if (t === "tenants") return { select: () => ({ eq: () => ({ single: async () => ({
          data: { whatsapp_handoff_number:"+919000000000" } }) }) }) };
        if (t === "lead_scores") return { select: () => ({ eq: () => ({ order: () => ({ limit: () => ({ maybeSingle:
          async () => ({ data: { score_0_100: 85, summary: "Good", next_action:"Quote",
            extracted: { chemicals:["glycerine"], timeline:"now" } } }) }) }) }) }) };
        if (t === "handoffs") return { insert: async (row: any) => { writes.push({ t, row }); return { error:null }; } };
        return {};
      },
    };
    const send = vi.fn();
    await handleHandoff(sb as any, { leadId:"L", callId:"C", appBaseUrl:"https://app", resendKey:"rk", emailSender: send });
    const channels = writes.map(w => w.row.channel);
    expect(channels).toContain("whatsapp");
    expect(channels).toContain("email");
    expect(send).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3:** Implementation.

`apps/workers/handoff/src/handoff.ts`:
```ts
import type { SupabaseClient } from "@supabase/supabase-js";
import { buildHotLeadMessage, buildWaLink, sendResendEmail } from "./wa-email";

export async function handleHandoff(
  sb: SupabaseClient,
  args: {
    leadId: string; callId: string; appBaseUrl: string;
    resendKey: string;
    emailSender?: (a: { to:string; from:string; subject:string; text:string }) => Promise<void>;
  },
): Promise<{ wa: string; email: string | null }> {
  const { data: lead } = await sb.from("leads")
    .select("id,tenant_id,name,phone_e164,company,assigned_to")
    .eq("id", args.leadId).single();
  if (!lead) throw new Error("lead not found");

  const { data: tenant } = await sb.from("tenants")
    .select("whatsapp_handoff_number").eq("id", lead.tenant_id).single();

  // Pick rep WhatsApp: assigned_to user, else tenant default
  let repWa = tenant?.whatsapp_handoff_number ?? "";
  let repEmail: string | null = null;
  if (lead.assigned_to) {
    const { data: rep } = await sb.from("users")
      .select("email,whatsapp").eq("id", lead.assigned_to).single();
    if (rep?.whatsapp) repWa = rep.whatsapp;
    if (rep?.email) repEmail = rep.email;
  }
  if (!repWa) throw new Error("no handoff WhatsApp configured");

  const { data: score } = await sb.from("lead_scores")
    .select("score_0_100,summary,next_action,extracted")
    .eq("call_id", args.callId).order("scored_at",{ascending:false}).limit(1).maybeSingle();
  if (!score) throw new Error("no score");

  const ex: any = score.extracted ?? {};
  const message = buildHotLeadMessage({
    leadName: lead.name, company: lead.company, phone: lead.phone_e164,
    score: score.score_0_100, summary: score.summary,
    chemicals: ex.chemicals ?? [], timeline: ex.timeline ?? "unknown",
    nextAction: score.next_action ?? "Follow up",
    leadUrl: `${args.appBaseUrl}/leads/${lead.id}`,
  });
  const wa = buildWaLink(repWa, message);

  await sb.from("handoffs").insert({
    lead_id: lead.id, call_id: args.callId, channel: "whatsapp", sent_to: repWa,
  });

  let emailUrl: string | null = null;
  if (repEmail) {
    const sender = args.emailSender ?? ((a) => sendResendEmail(args.resendKey, a));
    await sender({
      to: repEmail, from: "AI Voice <no-reply@aivoice.dev>",
      subject: `🔥 Hot lead: ${lead.name} (${lead.company ?? ""})`,
      text: message,
    });
    await sb.from("handoffs").insert({
      lead_id: lead.id, call_id: args.callId, channel: "email", sent_to: repEmail,
    });
    emailUrl = repEmail;
  }
  return { wa, email: emailUrl };
}
```

- [ ] **Step 4:** Run, watch pass. HTTP entry.

`apps/workers/handoff/src/index.ts`:
```ts
import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { handleHandoff } from "./handoff";

type Env = {
  SUPABASE_URL: string; SUPABASE_SERVICE_ROLE_KEY: string;
  INTERNAL_API_TOKEN: string; APP_BASE_URL: string; RESEND_API_KEY: string;
};
const app = new Hono<{ Bindings: Env }>();
app.post("/handoff", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ","");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error:"unauthorized" }, 401);
  const { lead_id, call_id } = await c.req.json<{lead_id:string;call_id:string}>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY,
    { auth:{autoRefreshToken:false,persistSession:false} });
  try {
    const out = await handleHandoff(sb, {
      leadId: lead_id, callId: call_id,
      appBaseUrl: c.env.APP_BASE_URL, resendKey: c.env.RESEND_API_KEY,
    });
    return c.json(out);
  } catch (e) { return c.json({ error: (e as Error).message }, 500); }
});
export default app;
```

- [ ] **Step 5:** Resend signup + API key.

Sign up at https://resend.com, add a domain or use Resend's test sender (`onboarding@resend.dev`) for the demo. Copy API key.

- [ ] **Step 6:** Deploy + secrets.

```powershell
cd apps/workers/handoff
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put APP_BASE_URL   # e.g. https://ai-voice-web.pages.dev
npx wrangler secret put RESEND_API_KEY
npx wrangler deploy
cd ../../..
```
Then update score-worker's `HANDOFF_WORKER_URL` secret to the deployed URL:
```powershell
cd apps/workers/score
npx wrangler secret put HANDOFF_WORKER_URL
cd ../../..
```

- [ ] **Step 7:** Commit.

```powershell
git add apps/workers/handoff
git commit -m "feat(handoff): WhatsApp + Resend email for hot leads"
```

---

## Task 5: `clicktocall-worker` — Exotel bridge (TDD)

**Files:**
- Create: `apps/workers/clicktocall/package.json`, `wrangler.toml`, `tsconfig.json`
- Create: `apps/workers/clicktocall/src/exotel.ts`
- Create: `apps/workers/clicktocall/src/exotel.test.ts`
- Create: `apps/workers/clicktocall/src/index.ts`

- [ ] **Step 1:** Failing test.

`apps/workers/clicktocall/src/exotel.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { connectTwoNumbers } from "./exotel";

describe("connectTwoNumbers", () => {
  it("POSTs to Exotel Connect endpoint with form-encoded body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      Call: { Sid: "CA123" } }), { status: 200 }));
    const out = await connectTwoNumbers({
      sid:"SID", apiKey:"K", apiToken:"T",
      from:"+919000000001", to:"+919876543210", callerId:"+914440000000",
      fetchImpl: fetchSpy,
    });
    expect(out.callSid).toBe("CA123");
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(String(url)).toMatch(/twilix\.exotel\.com.*SID\/Calls\/connect/);
    expect(init.method).toBe("POST");
    const body = init.body as string;
    expect(body).toContain("From=%2B919000000001");
    expect(body).toContain("To=%2B919876543210");
  });
});
```

- [ ] **Step 2:** Run, watch fail.

- [ ] **Step 3:** Implement.

`apps/workers/clicktocall/src/exotel.ts`:
```ts
export async function connectTwoNumbers(args: {
  sid: string; apiKey: string; apiToken: string;
  from: string; to: string; callerId: string;
  fetchImpl?: typeof fetch;
}): Promise<{ callSid: string }> {
  const auth = btoa(`${args.apiKey}:${args.apiToken}`);
  const url = `https://api.exotel.com/v1/Accounts/${args.sid}/Calls/connect.json`;
  const body = new URLSearchParams({
    From: args.from, To: args.to, CallerId: args.callerId, CallType: "trans",
    TimeLimit: "600", TimeOut: "30",
  });
  const f = args.fetchImpl ?? fetch;
  // Note: form parameter names are PascalCase but URLSearchParams encodes them as %2B etc — fine.
  const res = await f(url, {
    method: "POST",
    headers: { authorization: `Basic ${auth}`, "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!res.ok) throw new Error(`exotel connect ${res.status}: ${await res.text()}`);
  const j: any = await res.json();
  return { callSid: j.Call?.Sid ?? j.Call?.CallSid };
}
```

Note: Exotel uses `api.exotel.com` for some accounts and `twilix.exotel.com` for older accounts — the test currently checks for `twilix` in the URL; update either the URL or the test regex to match your actual Exotel account dashboard.

Update test regex to allow either:
```ts
expect(String(url)).toMatch(/exotel\.com.*Accounts\/SID\/Calls\/connect/);
```

- [ ] **Step 4:** HTTP entry.

`apps/workers/clicktocall/src/index.ts`:
```ts
import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { connectTwoNumbers } from "./exotel";

type Env = {
  SUPABASE_URL: string; SUPABASE_SERVICE_ROLE_KEY: string;
  INTERNAL_API_TOKEN: string;
  EXOTEL_SID: string; EXOTEL_API_KEY: string; EXOTEL_API_TOKEN: string;
};
const app = new Hono<{ Bindings: Env }>();

app.post("/bridge", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ","");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error:"unauthorized" }, 401);
  const { lead_id, rep_user_id } = await c.req.json<{lead_id:string; rep_user_id:string}>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY,
    { auth:{autoRefreshToken:false,persistSession:false} });
  const { data: lead } = await sb.from("leads").select("id,tenant_id,phone_e164").eq("id", lead_id).single();
  if (!lead) return c.json({ error:"lead not found" }, 404);
  const { data: rep } = await sb.from("users").select("whatsapp").eq("id", rep_user_id).single();
  if (!rep?.whatsapp) return c.json({ error:"rep has no phone" }, 400);
  const { data: tenant } = await sb.from("tenants").select("exotel_caller_id").eq("id", lead.tenant_id).single();
  if (!tenant?.exotel_caller_id) return c.json({ error:"tenant has no caller id" }, 400);

  try {
    const { callSid } = await connectTwoNumbers({
      sid: c.env.EXOTEL_SID, apiKey: c.env.EXOTEL_API_KEY, apiToken: c.env.EXOTEL_API_TOKEN,
      from: rep.whatsapp, to: lead.phone_e164, callerId: tenant.exotel_caller_id,
    });
    await sb.from("calls").insert({
      tenant_id: lead.tenant_id, lead_id: lead.id, samvaad_call_id: `exotel:${callSid}`,
      status: "ringing", kind: "human_followup",
    });
    return c.json({ ok:true, callSid });
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

export default app;
```

- [ ] **Step 5:** Deploy + secrets.

```powershell
cd apps/workers/clicktocall
npx wrangler secret put SUPABASE_URL
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put INTERNAL_API_TOKEN
npx wrangler secret put EXOTEL_SID
npx wrangler secret put EXOTEL_API_KEY
npx wrangler secret put EXOTEL_API_TOKEN
npx wrangler deploy
cd ../../..
```

- [ ] **Step 6:** Commit.

```powershell
git add apps/workers/clicktocall
git commit -m "feat(clicktocall): Exotel two-number bridge"
```

---

## Task 6: "Call now" UI (mobile tel: + desktop bridge)

**Files:**
- Create: `apps/web/components/CallNowButton.tsx`
- Modify: `apps/web/app/leads/actions.ts` (add `bridgeCallAction`)
- Modify: `apps/web/app/leads/[id]/page.tsx`

- [ ] **Step 1:** Action.

Append to `apps/web/app/leads/actions.ts`:
```ts
export async function bridgeCallAction(leadId: string) {
  const supabase = createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { error: "unauthorized" };

  const res = await fetch(`${process.env.CLICKTOCALL_WORKER_URL}/bridge`, {
    method: "POST",
    headers: { "content-type":"application/json", authorization:`Bearer ${process.env.INTERNAL_API_TOKEN}` },
    body: JSON.stringify({ lead_id: leadId, rep_user_id: user.id }),
  });
  if (!res.ok) return { error: (await res.json()).error ?? "bridge failed" };
  return { ok: true };
}
```

- [ ] **Step 2:** Button.

`apps/web/components/CallNowButton.tsx`:
```tsx
"use client";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { bridgeCallAction } from "@/app/leads/actions";

export function CallNowButton({ leadId, phone }: { leadId: string; phone: string }) {
  const [pending, start] = useTransition();
  const isMobile = typeof navigator !== "undefined" &&
    /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

  if (isMobile) {
    return (
      <a href={`tel:${phone}`} className="inline-flex">
        <Button variant="default">📞 Call now ({phone})</Button>
      </a>
    );
  }
  return (
    <Button disabled={pending} onClick={() => start(async () => {
      const r = await bridgeCallAction(leadId);
      if (r.error) toast.error(r.error);
      else toast.success("Your phone will ring — pick up to be connected to the lead");
    })}>
      {pending ? "Bridging…" : "📞 Call now"}
    </Button>
  );
}
```

- [ ] **Step 3:** Place on lead detail.

In `apps/web/app/leads/[id]/page.tsx` header buttons row:
```tsx
import { CallNowButton } from "@/components/CallNowButton";
// ...
<div className="flex items-center gap-3">
  <CallNowButton leadId={lead.id} phone={lead.phone_e164} />
  <StartAiCallButton leadId={lead.id} />
  <LeadStatusBadge status={lead.status} />
  <DncDialog leadId={lead.id} phone={lead.phone_e164} />
</div>
```

- [ ] **Step 4:** Add Pages env vars.

In CF Pages settings + `.env.local`:
- `CLICKTOCALL_WORKER_URL` = `https://ai-voice-clicktocall.<...>.workers.dev`

- [ ] **Step 5:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): one-click human takeover (mobile tel: + desktop bridge)"
```

---

## Task 7: Score badge, summary card, extracted fields UI

**Files:**
- Create: `apps/web/components/ScoreBadge.tsx`
- Create: `apps/web/components/SummaryCard.tsx`
- Create: `apps/web/components/ExtractedFields.tsx`
- Modify: `apps/web/app/leads/[id]/page.tsx`

- [ ] **Step 1:** Score badge.

`apps/web/components/ScoreBadge.tsx`:
```tsx
import { Badge } from "@/components/ui/badge";
const tone = (c: string) => c === "hot" ? "bg-red-600 text-white"
  : c === "warm" ? "bg-orange-500 text-white" : "bg-zinc-400 text-white";

export function ScoreBadge({ classification, score }: { classification: string; score: number }) {
  return <Badge className={`${tone(classification)} text-base px-3 py-1`}>
    {classification.toUpperCase()} · {score}/100
  </Badge>;
}
```

- [ ] **Step 2:** Summary + extracted.

`apps/web/components/SummaryCard.tsx`:
```tsx
export function SummaryCard({ summary, reason, nextAction }: { summary: string; reason: string; nextAction?: string | null }) {
  return (
    <div className="space-y-3">
      <p className="text-sm">{summary}</p>
      <p className="text-xs text-muted-foreground">Why this classification: {reason}</p>
      {nextAction && <p className="text-sm"><span className="font-medium">Next step:</span> {nextAction}</p>}
    </div>
  );
}
```

`apps/web/components/ExtractedFields.tsx`:
```tsx
type Ex = {
  decision_maker?: boolean; industry?: string | null;
  chemicals?: string[]; monthly_volume_kg?: number | null;
  current_supplier?: string | null; supplier_pain?: string[];
  timeline?: string; decision_maker_email?: string | null;
  decision_maker_whatsapp?: string | null;
};
export function ExtractedFields({ extracted }: { extracted: Ex }) {
  const Row = ({ k, v }: { k: string; v: any }) => (
    <div className="grid grid-cols-3 gap-2 text-sm"><dt className="text-muted-foreground">{k}</dt>
      <dd className="col-span-2">{v == null || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>
  );
  return (
    <dl className="space-y-1">
      <Row k="Decision maker" v={extracted.decision_maker ? "Yes" : "No"} />
      <Row k="Industry" v={extracted.industry} />
      <Row k="Chemicals" v={extracted.chemicals} />
      <Row k="Volume (kg/mo)" v={extracted.monthly_volume_kg} />
      <Row k="Current supplier" v={extracted.current_supplier} />
      <Row k="Supplier pain" v={extracted.supplier_pain} />
      <Row k="Timeline" v={extracted.timeline} />
      <Row k="Email" v={extracted.decision_maker_email} />
      <Row k="WhatsApp" v={extracted.decision_maker_whatsapp} />
    </dl>
  );
}
```

- [ ] **Step 3:** Wire into detail page.

Replace the "AI Summary" section in `apps/web/app/leads/[id]/page.tsx`:
```tsx
const { data: latestScore } = await supabase.from("lead_scores")
  .select("*").eq("lead_id", lead.id).order("scored_at", { ascending: false })
  .limit(1).maybeSingle();
// ...
{latestScore ? (
  <section className="space-y-4 rounded-md border p-4">
    <div className="flex items-center gap-3">
      <h2 className="text-sm font-medium">AI Summary</h2>
      <ScoreBadge classification={latestScore.classification} score={latestScore.score_0_100} />
    </div>
    <SummaryCard summary={latestScore.summary} reason={latestScore.reason} nextAction={latestScore.next_action} />
    <ExtractedFields extracted={latestScore.extracted ?? {}} />
  </section>
) : (
  <section className="rounded-md border p-4">
    <h2 className="mb-2 text-sm font-medium">AI Summary</h2>
    <p className="text-sm text-muted-foreground">No score yet. Trigger a call.</p>
  </section>
)}
```

- [ ] **Step 4:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): score badge + summary + extracted fields on lead detail"
```

---

## Task 8: Realtime score updates on dashboard

**Files:**
- Modify: `apps/web/app/leads/page.tsx` (subscribe to `lead_scores`)
- Modify: `apps/web/components/LeadsTable.tsx`

- [ ] **Step 1:** Pass classification down.

Change leads query to include `(latest score)`:
```ts
const { data: leads } = await supabase
  .from("leads")
  .select(`id,name,phone_e164,company,industry,status,created_at,
           lead_scores(score_0_100,classification,scored_at)`)
  .order("created_at",{ascending:false}).limit(500);
```

- [ ] **Step 2:** Render score in table.

Update `LeadsTable.tsx` to show a small badge if `lead_scores[0]` exists.

- [ ] **Step 3:** Add a tiny client wrapper that triggers `router.refresh()` on any `lead_scores` insert via Supabase realtime channel.

Create `apps/web/components/LeadsRealtimeRefresher.tsx`:
```tsx
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";
export function LeadsRealtimeRefresher() {
  const router = useRouter();
  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const ch = supabase.channel("scores-refresh")
      .on("postgres_changes", { event:"INSERT", schema:"public", table:"lead_scores" },
          () => router.refresh())
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [router]);
  return null;
}
```
Mount it on `app/leads/page.tsx`.

- [ ] **Step 4:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): realtime lead-score updates on list page"
```

---

## Task 9: 6-scenario E2E demo run

This is a manual demo gate per spec §12.3.

- [ ] **Scenario 1 — EN happy path.** Add yourself as a lead, click **Call with AI**. Engage fully in English for 2–3 minutes. Verify: status → Hot, score ≥80, WhatsApp notification arrives, AI summary card shows 2–4 sentences, extracted chemicals + timeline correct.

- [ ] **Scenario 2 — HI happy path.** Add yourself again (different number or delete previous). Trigger call; switch to Hindi after Priya's first line. Verify Priya continues in Hindi for the rest of the call. Score Hot.

- [ ] **Scenario 3 — TA happy path.** Same but Tamil. Score Hot.

- [ ] **Scenario 4 — Cold drop.** Trigger call, say "Not interested, do not call this number" within 15s. Verify: lead becomes Cold + DNC entry inserted (`select * from dnc_list where phone_e164='<yours>'`), no WhatsApp ping.

- [ ] **Scenario 5 — Voicemail.** Don't pick up. Verify: status `voicemail`, retry scheduled (`leads.status='queued'`), `call_events` shows voicemail.

- [ ] **Scenario 6 — Click-to-call human takeover (any lead).** Open ANY lead on desktop (not just Hot — the button is on every lead detail page). Click **Call now**. Your phone rings (the rep number); pick up — Exotel bridges to the lead number. Verify a `calls` row with `kind='human_followup'` exists. Then repeat on a mobile browser — the button becomes a `tel:` link instead of a bridge.

After each scenario, screen-record (OBS or Loom) and save under `docs/demo-recordings/`.

- [ ] **Step 7:** Commit recordings index.

Create `docs/demo-recordings/README.md` listing 6 video links/paths. Commit:
```powershell
git add docs/demo-recordings
git commit -m "demo: 6-scenario E2E recording index"
```

---

## Task 10: Cost dashboard tile

**Files:**
- Modify: `apps/web/app/campaigns/page.tsx`

- [ ] **Step 1:** Compute simple aggregates.

```tsx
const { data: rows } = await supabase.rpc("call_cost_summary", {});
// or inline:
const { data: calls7 } = await supabase
  .from("calls").select("duration_sec,kind,status,created_at")
  .gte("created_at", new Date(Date.now()-7*86400_000).toISOString());

const aiCalls = (calls7 ?? []).filter(c => c.kind === "ai_outbound");
const totalMin = aiCalls.reduce((a,c) => a + (c.duration_sec ?? 0)/60, 0);
const blendedRupees = Math.round(totalMin * 7); // ₹7/min blended
```

Render a small card under the campaign button showing:
- Calls in last 7 days
- Average duration
- Estimated cost (₹X)
- Hot rate (% of completed calls classified Hot)

- [ ] **Step 2:** Commit.

```powershell
git add apps/web
git commit -m "feat(web): cost + hot-rate dashboard tile"
```

---

## Task 11: SPC pitch script + readme polish

**Files:**
- Create: `docs/pitch/spc-demo-script.md`
- Modify: `README.md`

- [ ] **Step 1:** Pitch script (90 seconds talk-track + 3-minute demo).

`docs/pitch/spc-demo-script.md`:
```markdown
# SPC pitch — 4-minute demo

## Talk track (0:00–0:45)
- SPC's growth bottleneck is outbound qualification: dialing prospects,
  finding the right procurement contact, qualifying fit, routing hot
  ones to a rep.
- We've built Priya: a multilingual voice agent that places real calls,
  sounds human in English/Hindi/Tamil, qualifies the lead in under 3
  minutes, and logs everything into a CRM your reps already love using.

## Live demo flow (0:45–4:00)
1. Open dashboard → 10 sample leads.
2. Click a lead → click "Call with AI" → my own phone rings.
3. Pick up; let it run for ~2 minutes; switch to Hindi mid-call.
4. End call. Within ~30 seconds: AI summary appears, classification
   Hot, score 85, extracted fields populated, WhatsApp notification on
   my phone, email in my inbox.
5. Click "Call now" → bridge to a second number → human takeover.

## Pricing pitch (4:00–4:30)
- Demo cost: ₹0 fixed, ~₹9–13 per qualification call (blended).
- For SPC at ~1,000 outbound/month: ₹9k–13k/month, no setup fee.
- Per-tenant configuration, white-labelable, our IP.

## Close
- "We can run this against your real list next week if you can give us
  100 numbers + the procurement DLT template approval."
```

- [ ] **Step 2:** Update README with quickstart for new devs.

(Add sections: Local dev, Deploy, Architecture overview, Cost model.)

- [ ] **Step 3:** Commit.

```powershell
git add docs README.md
git commit -m "docs: SPC pitch script + README polish"
```

---

## Task 12: Production deploy + final smoke

- [ ] **Step 1:** Redeploy all four workers + web app.

```powershell
pnpm --filter @ai-voice/webhooks-worker deploy
pnpm --filter @ai-voice/campaigns-worker deploy
pnpm --filter @ai-voice/score-worker deploy
pnpm --filter @ai-voice/handoff-worker deploy
pnpm --filter @ai-voice/clicktocall-worker deploy
pnpm --filter @ai-voice/web run deploy
```

- [ ] **Step 2:** Run scenario 1 + 4 + 6 against production (not local).

- [ ] **Step 3:** Snapshot cost dashboard, save screenshot to `docs/pitch/cost-snapshot.png`.

- [ ] **Step 4:** Tag the release.

```powershell
git tag -a v0.1.0-spc-demo -m "SPC demo cut"
```

---

## Self-review

**Spec coverage:**
- §7 steps 6–7 (scoring + handoff) → Tasks 3, 4 ✓
- §9.5 scoring rubric → Tasks 1, 2 ✓
- §6.2 score-worker + handoff-worker + clicktocall-worker → Tasks 3, 4, 5 ✓
- §6.1 lead detail UI (summary, score, extracted, Call now) → Tasks 6, 7 ✓
- §12.3 6-scenario E2E → Task 9 ✓
- §13 M5 polish + cost dashboard + pitch → Tasks 10, 11 ✓

**Placeholder scan:** Task 3 step 2 inlines the scoring prompt — explicit "paste from Task 1" note avoids the trap. Golden fixtures: only 3 of 20 written inline; Task 2 step 2 instructs writing the remaining 17 with the same shape, but the executor needs to actually do it. If you want stricter coverage, expand Task 2 step 2 with all 20.

**Type consistency:** `LeadScore`, `extracted`, `samvaad_call_id`, `kind='human_followup'`, `INTERNAL_API_TOKEN` consistent across plans.

---

## Done state (after Task 12)

- Full demo flow works end-to-end on production URLs.
- 6 scenarios recorded.
- Pitch script written.
- Cost dashboard visible.
- Tagged `v0.1.0-spc-demo`.

The product is now sellable to a second tenant by re-running Task 1 of Plan 1 (create a new row in `tenants`, provision their Samvaad agent, run their CSV through the same dashboard).
