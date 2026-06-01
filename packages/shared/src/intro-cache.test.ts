import { describe, it, expect, vi } from "vitest";
import {
  buildIntroText,
  isUsableFirstName,
  introR2Key,
  synthesizeAndCacheIntros,
  type IntroTts,
} from "./intro-cache";

describe("isUsableFirstName", () => {
  it("accepts 2+ char names", () => {
    expect(isUsableFirstName("Ravi")).toBe(true);
    expect(isUsableFirstName("Su")).toBe(true);
  });
  it("rejects placeholders and short tokens", () => {
    expect(isUsableFirstName("Unknown")).toBe(false);
    expect(isUsableFirstName("NA")).toBe(false);
    expect(isUsableFirstName("N/A")).toBe(false);
    expect(isUsableFirstName("Test")).toBe(false);
    expect(isUsableFirstName("")).toBe(false);
    expect(isUsableFirstName(null)).toBe(false);
    expect(isUsableFirstName("R")).toBe(false);
  });
});

describe("buildIntroText", () => {
  it("inserts first name in English template", () => {
    expect(buildIntroText("en-IN", "Ravi")).toContain("Hello Ravi");
  });
  it("inserts first name in Hindi template", () => {
    expect(buildIntroText("hi-IN", "Sunil")).toMatch(/Sunil ji/);
  });
  it("inserts first name in Tamil template", () => {
    expect(buildIntroText("ta-IN", "Karthik")).toContain("Karthik avargale");
  });
  it("uses placeholder-free fallback when name is unusable", () => {
    const en = buildIntroText("en-IN", "Unknown");
    expect(en).not.toMatch(/Unknown/);
    expect(en).toMatch(/Namaste/);
  });
  it("never leaves a stray space when name is empty", () => {
    expect(buildIntroText("en-IN", "")).not.toMatch(/Hello ,/);
    expect(buildIntroText("hi-IN", null)).not.toMatch(/Namaste\s+ji/);
  });
});

describe("introR2Key", () => {
  it("namespaces by tenant and lead", () => {
    expect(introR2Key({ tenantId: "t1", leadId: "l1", lang: "en-IN" })).toBe(
      "intro/t1/l1/en-IN.mp3",
    );
  });
});

describe("synthesizeAndCacheIntros", () => {
  it("synthesizes 3 langs by default and writes each to R2 + DB", async () => {
    const tts = vi.fn(async () => new ArrayBuffer(16));
    const r2Put = vi.fn(async () => {});
    const upsertRow = vi.fn(async () => {});
    const out = await synthesizeAndCacheIntros({
      tenantId: "t1",
      leadId: "l1",
      firstName: "Ravi",
      tts,
      r2Put,
      upsertRow,
    });
    expect(out).toHaveLength(3);
    expect(tts).toHaveBeenCalledTimes(3);
    expect(r2Put).toHaveBeenCalledTimes(3);
    expect(upsertRow).toHaveBeenCalledTimes(3);
    expect(out.map((o) => o.lang)).toEqual(["en-IN", "hi-IN", "ta-IN"]);
  });

  it("uses fallback (no-name) text when first name is a placeholder", async () => {
    let capturedText = "";
    const tts: IntroTts = async ({ text }) => {
      capturedText = text;
      return new ArrayBuffer(8);
    };
    await synthesizeAndCacheIntros({
      tenantId: "t1",
      leadId: "l1",
      firstName: "Unknown",
      langs: ["en-IN"],
      tts,
      r2Put: async () => {},
      upsertRow: async () => {},
    });
    expect(capturedText).not.toMatch(/Unknown/);
  });

  it("text hash differs across names (cache invalidates on rename)", async () => {
    let hashes: string[] = [];
    const cap = (row: any) => {
      hashes.push(row.textHash);
    };
    await synthesizeAndCacheIntros({
      tenantId: "t1",
      leadId: "l1",
      firstName: "Ravi",
      langs: ["en-IN"],
      tts: async () => new ArrayBuffer(4),
      r2Put: async () => {},
      upsertRow: async (r) => cap(r),
    });
    await synthesizeAndCacheIntros({
      tenantId: "t1",
      leadId: "l1",
      firstName: "Sunil",
      langs: ["en-IN"],
      tts: async () => new ArrayBuffer(4),
      r2Put: async () => {},
      upsertRow: async (r) => cap(r),
    });
    expect(hashes[0]).not.toBe(hashes[1]);
  });
});
