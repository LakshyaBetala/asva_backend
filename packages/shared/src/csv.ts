import Papa from "papaparse";
import { LeadInput } from "./schemas";
import { toE164 } from "./phone";

export type ValidatedLead = {
  name: string;
  phone_e164: string;
  company: string | null;
  industry: string | null;
  source: string | null;
  notes: string | null;
};

export type CsvParseResult = {
  valid: ValidatedLead[];
  invalid: { row: number; reason: string }[];
  duplicatesInFile: { row: number; phone_e164: string }[];
};

const MAX_ROWS = 10_000;

export function parseLeadsCsv(text: string): CsvParseResult {
  const parsed = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: "greedy",
    transformHeader: (h) => h.trim().toLowerCase(),
  });

  if (parsed.data.length > MAX_ROWS) {
    throw new Error(`CSV exceeds 10000 rows (got ${parsed.data.length})`);
  }

  const valid: ValidatedLead[] = [];
  const invalid: { row: number; reason: string }[] = [];
  const duplicatesInFile: { row: number; phone_e164: string }[] = [];
  const seenPhones = new Set<string>();

  parsed.data.forEach((row, i) => {
    const rowNum = i + 2;
    const parsedRow = LeadInput.safeParse({
      name: row.name?.trim() ?? "",
      phone: row.phone?.trim() ?? "",
      company: row.company?.trim() || null,
      industry: row.industry?.trim() || null,
      source: row.source?.trim() || null,
      notes: row.notes?.trim() || null,
    });
    if (!parsedRow.success) {
      invalid.push({ row: rowNum, reason: parsedRow.error.issues[0]!.message });
      return;
    }
    let phone_e164: string;
    try {
      phone_e164 = toE164(parsedRow.data.phone);
    } catch (e) {
      invalid.push({ row: rowNum, reason: (e as Error).message });
      return;
    }
    if (seenPhones.has(phone_e164)) {
      duplicatesInFile.push({ row: rowNum, phone_e164 });
      return;
    }
    seenPhones.add(phone_e164);
    valid.push({
      name: parsedRow.data.name,
      phone_e164,
      company: parsedRow.data.company ?? null,
      industry: parsedRow.data.industry ?? null,
      source: parsedRow.data.source ?? null,
      notes: parsedRow.data.notes ?? null,
    });
  });

  return { valid, invalid, duplicatesInFile };
}
