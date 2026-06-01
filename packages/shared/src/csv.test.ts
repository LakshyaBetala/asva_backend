import { describe, it, expect } from "vitest";
import { parseLeadsCsv } from "./csv";

const SAMPLE = `name,phone,company,industry,source,notes
Ravi Kumar,9876543210,Acme Pharma,Pharmaceuticals,LinkedIn,interested in glycerine
Anita S,98765 43211,,Paints,Trade show,
,9000000000,No Name Co,,,
Bad Row,abc,,,,`;

describe("parseLeadsCsv", () => {
  it("parses valid rows and normalizes phones to E.164", () => {
    const result = parseLeadsCsv(SAMPLE);
    expect(result.valid).toHaveLength(2);
    expect(result.valid[0]!.phone_e164).toBe("+919876543210");
    expect(result.valid[1]!.phone_e164).toBe("+919876543211");
  });

  it("reports invalid rows with row numbers and messages", () => {
    const result = parseLeadsCsv(SAMPLE);
    expect(result.invalid).toHaveLength(2);
    expect(result.invalid[0]!.row).toBe(4);
    expect(result.invalid[1]!.row).toBe(5);
  });

  it("dedupes by phone within the file (keeps first)", () => {
    const dup = `name,phone\nA,9876543210\nB,9876543210`;
    const result = parseLeadsCsv(dup);
    expect(result.valid).toHaveLength(1);
    expect(result.duplicatesInFile).toHaveLength(1);
  });

  it("caps at 10,000 rows", () => {
    const rows = ["name,phone"];
    for (let i = 0; i < 10001; i++) {
      const last6 = String(100000 + i).slice(-6);
      rows.push(`User ${i},9876${last6}`);
    }
    expect(() => parseLeadsCsv(rows.join("\n"))).toThrow(/exceeds 10000/i);
  });
});
