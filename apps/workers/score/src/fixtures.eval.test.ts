import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { LeadScore, containsNonEnglishScript } from "@ai-voice/shared";
import { scoreTranscript, type TranscriptLine } from "./score";

// Locate fixtures relative to this file: src/ -> ../../../../tests/fixtures/...
const FIXTURE_DIR = join(
  __dirname,
  "..",
  "..",
  "..",
  "..",
  "tests",
  "fixtures",
  "golden-transcripts",
);

type Fixture = {
  lang_primary: string;
  transcript: TranscriptLine[];
  expected: {
    classification: "hot" | "warm" | "cold";
    score_range: [number, number];
    decision_maker?: boolean;
    timeline?: "now" | "1-3mo" | "exploring" | "unknown";
    must_include?: {
      chemicals?: string[];
      supplier_pain?: string[];
      call_quality_flags?: string[];
    };
  };
};

function loadFixtures(): { name: string; fx: Fixture }[] {
  return readdirSync(FIXTURE_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((name) => ({
      name,
      fx: JSON.parse(readFileSync(join(FIXTURE_DIR, name), "utf-8")) as Fixture,
    }));
}

// Build a Zod-conformant LeadScore that matches a fixture's expectations.
// This is the "happy path" LLM output the scorer should accept unchanged.
function makeExpectedScore(fx: Fixture) {
  const mid = Math.floor(
    (fx.expected.score_range[0] + fx.expected.score_range[1]) / 2,
  );
  return {
    decision_maker: fx.expected.decision_maker ?? false,
    industry: "Chemicals",
    chemicals: fx.expected.must_include?.chemicals ?? [],
    monthly_volume_kg: null,
    current_supplier: null,
    supplier_pain: (fx.expected.must_include?.supplier_pain as any) ?? ["none"],
    timeline: fx.expected.timeline ?? "unknown",
    decision_maker_email: null,
    decision_maker_whatsapp: null,
    classification: fx.expected.classification,
    score_0_100: mid,
    reason: "deterministic eval stub",
    summary: "Eval stub summary in English only.",
    next_action: "Send quote within 4 hours.",
    call_quality_flags:
      (fx.expected.must_include?.call_quality_flags as any) ?? ["none"],
  };
}

describe("fixtures: schema + invariants (offline)", () => {
  const fixtures = loadFixtures();

  it("loads 20 golden fixtures", () => {
    expect(fixtures.length).toBe(20);
  });

  for (const { name, fx } of fixtures) {
    describe(name, () => {
      it("fixture filename label matches expected.classification", () => {
        const label = name.split("_")[0];
        expect(fx.expected.classification).toBe(label);
      });

      it("expected payload conforms to LeadScore Zod schema", () => {
        const parsed = LeadScore.safeParse(makeExpectedScore(fx));
        expect(parsed.success).toBe(true);
      });

      it("scoreTranscript accepts a conformant LLM response unchanged", async () => {
        const stub = async () => JSON.stringify(makeExpectedScore(fx));
        const out = await scoreTranscript(fx.transcript, { callLlm: stub });
        expect(out.classification).toBe(fx.expected.classification);
        expect(out.score_0_100).toBeGreaterThanOrEqual(fx.expected.score_range[0]);
        expect(out.score_0_100).toBeLessThanOrEqual(fx.expected.score_range[1]);
        expect(containsNonEnglishScript(out)).toBe(false);
      });

      it("rejects + retries when LLM leaks Devanagari/Tamil into summary", async () => {
        const bad = { ...makeExpectedScore(fx), summary: "रवि की पुष्टि।" };
        const good = makeExpectedScore(fx);
        let calls = 0;
        const stub = async () => {
          calls++;
          return JSON.stringify(calls === 1 ? bad : good);
        };
        const out = await scoreTranscript(fx.transcript, { callLlm: stub });
        expect(calls).toBe(2);
        expect(containsNonEnglishScript(out)).toBe(false);
      });
    });
  }
});

// Live-LLM eval — opt-in. Set RUN_LIVE_EVAL=1 + SARVAM_BASE_URL/SARVAM_API_KEY
// (or substitute a Gemini caller) to actually hit the model. Catches prompt
// regressions and silent model behavior changes.
describe.skipIf(process.env.RUN_LIVE_EVAL !== "1")(
  "fixtures: live-LLM eval (opt-in)",
  () => {
    const fixtures = loadFixtures();
    for (const { name, fx } of fixtures) {
      it(`live: ${name} classifies as ${fx.expected.classification}`, async () => {
        const { callSarvamLlm } = await import("./score");
        const env = {
          SARVAM_BASE_URL: process.env.SARVAM_BASE_URL!,
          SARVAM_API_KEY: process.env.SARVAM_API_KEY!,
        };
        const out = await scoreTranscript(fx.transcript, {
          callLlm: (p) => callSarvamLlm(env, p),
        });
        expect(out.classification).toBe(fx.expected.classification);
        expect(containsNonEnglishScript(out)).toBe(false);
      }, 30_000);
    }
  },
);
