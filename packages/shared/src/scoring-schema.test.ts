import { describe, it, expect } from "vitest";
import { LeadScore, containsNonEnglishScript } from "./scoring-schema";

const baseScore = {
  decision_maker: true,
  industry: "Pharmaceuticals",
  chemicals: ["glycerine", "acetic acid"],
  monthly_volume_kg: 8000,
  current_supplier: "ChemCo",
  supplier_pain: ["delivery"] as const,
  timeline: "now" as const,
  decision_maker_email: "x@y.com",
  decision_maker_whatsapp: null,
  classification: "hot" as const,
  score_0_100: 85,
  reason: "decision-maker, immediate timeline, bulk volume, supplier pain",
  summary: "Ravi at Acme Pharma confirmed bulk glycerine + acetic acid procurement.",
  next_action: "Send quote within 4 hours.",
  call_quality_flags: ["none"] as const,
};

describe("LeadScore schema", () => {
  it("accepts a well-formed score", () => {
    expect(() => LeadScore.parse(baseScore)).not.toThrow();
  });
  it("rejects score > 100", () => {
    expect(() => LeadScore.parse({ ...baseScore, score_0_100: 101 })).toThrow();
  });
  it("rejects unknown classification", () => {
    expect(() => LeadScore.parse({ ...baseScore, classification: "burning" })).toThrow();
  });
});

describe("containsNonEnglishScript", () => {
  it("returns false for English summary", () => {
    expect(containsNonEnglishScript(LeadScore.parse(baseScore))).toBe(false);
  });
  it("returns true if summary contains Devanagari", () => {
    const bad = { ...baseScore, summary: "रवि बल्क खरीद की पुष्टि करते हैं।" };
    expect(containsNonEnglishScript(LeadScore.parse(bad))).toBe(true);
  });
  it("returns true if chemicals contain Tamil", () => {
    const bad = { ...baseScore, chemicals: ["கிளிசரின்"] };
    expect(containsNonEnglishScript(LeadScore.parse(bad))).toBe(true);
  });
});
