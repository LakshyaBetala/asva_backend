import { z } from "zod";

export const LeadInput = z.object({
  name: z.string().min(1).max(120),
  phone: z.string().min(7).max(20),
  company: z.string().max(200).optional().nullable(),
  industry: z.string().max(120).optional().nullable(),
  source: z.string().max(120).optional().nullable(),
  notes: z.string().max(2000).optional().nullable(),
});
export type LeadInput = z.infer<typeof LeadInput>;

export const CsvRow = LeadInput;
export type CsvRow = z.infer<typeof CsvRow>;
