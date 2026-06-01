import { describe, it, expect, vi } from "vitest";
import { scoreTranscript } from "./score";

const okScore = {
  decision_maker: true,
  industry: "Pharmaceuticals",
  chemicals: ["glycerine", "acetic acid"],
  monthly_volume_kg: 8000,
  current_supplier: "ChemCo",
  supplier_pain: ["delivery"],
  timeline: "now",
  decision_maker_email: "ravi@acmepharma.in",
  decision_maker_whatsapp: null,
  classification: "hot",
  score_0_100: 85,
  reason: "decision-maker, immediate, bulk, supplier pain",
  summary: "Ravi at Acme Pharma confirmed bulk glycerine + acetic acid procurement with delivery pain.",
  next_action: "Send quote for glycerine and acetic acid within 4 hours.",
  call_quality_flags: ["none"],
};

describe("scoreTranscript", () => {
  it("returns parsed score on first try", async () => {
    const llm = vi.fn().mockResolvedValue(JSON.stringify(okScore));
    const out = await scoreTranscript(
      [{ speaker: "agent", text: "hi", lang: "en-IN" }],
      { callLlm: llm },
    );
    expect(out.classification).toBe("hot");
    expect(out.score_0_100).toBe(85);
    expect(llm).toHaveBeenCalledTimes(1);
  });

  it("retries when LLM returns invalid JSON, throws needs_review after 2", async () => {
    const llm = vi.fn().mockResolvedValue("not json");
    await expect(
      scoreTranscript([{ speaker: "agent", text: "hi", lang: "en-IN" }], { callLlm: llm }),
    ).rejects.toThrow(/needs_review/);
    expect(llm).toHaveBeenCalledTimes(2);
  });

  it("rejects + retries when summary contains Devanagari", async () => {
    const badThenGood = vi
      .fn()
      .mockResolvedValueOnce(
        JSON.stringify({ ...okScore, summary: "रवि बल्क खरीद की पुष्टि करते हैं।" }),
      )
      .mockResolvedValueOnce(JSON.stringify(okScore));
    const out = await scoreTranscript(
      [{ speaker: "agent", text: "hi", lang: "en-IN" }],
      { callLlm: badThenGood },
    );
    expect(out.summary).not.toMatch(/[ऀ-ॿ]/);
    expect(badThenGood).toHaveBeenCalledTimes(2);
  });

  it("rejects + retries when chemicals contain Tamil", async () => {
    const badThenGood = vi
      .fn()
      .mockResolvedValueOnce(JSON.stringify({ ...okScore, chemicals: ["கிளிசரின்"] }))
      .mockResolvedValueOnce(JSON.stringify(okScore));
    const out = await scoreTranscript(
      [{ speaker: "agent", text: "hi", lang: "en-IN" }],
      { callLlm: badThenGood },
    );
    expect(out.chemicals.join("")).not.toMatch(/[஀-௿]/);
    expect(badThenGood).toHaveBeenCalledTimes(2);
  });
});
