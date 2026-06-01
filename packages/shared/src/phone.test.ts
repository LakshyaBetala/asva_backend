import { describe, it, expect } from "vitest";
import { toE164 } from "./phone";

describe("toE164 (India default)", () => {
  it("normalizes 10-digit mobile", () => {
    expect(toE164("9876543210")).toBe("+919876543210");
  });
  it("accepts +91 prefix", () => {
    expect(toE164("+91 98765 43210")).toBe("+919876543210");
  });
  it("accepts 0-prefixed", () => {
    expect(toE164("09876543210")).toBe("+919876543210");
  });
  it("strips spaces and dashes", () => {
    expect(toE164("98765-43210")).toBe("+919876543210");
  });
  it("rejects too-short / non-numeric", () => {
    expect(() => toE164("abc")).toThrow(/invalid/i);
    expect(() => toE164("123")).toThrow(/invalid/i);
  });
  it("accepts foreign number when region-overridden", () => {
    expect(toE164("+1 415 555 0100", { defaultRegion: "IN" })).toBe("+14155550100");
  });
});
