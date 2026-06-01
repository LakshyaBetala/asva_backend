import { z } from "zod";

export const LeadScore = z.object({
  decision_maker: z.boolean(),
  industry: z.string().nullable(),
  chemicals: z.array(z.string()),
  monthly_volume_kg: z.number().nullable(),
  current_supplier: z.string().nullable(),
  supplier_pain: z.array(z.enum(["price", "delivery", "quality", "support", "none"])),
  timeline: z.enum(["now", "1-3mo", "exploring", "unknown"]),
  decision_maker_email: z.string().email().nullable(),
  decision_maker_whatsapp: z.string().nullable(),
  classification: z.enum(["hot", "warm", "cold"]),
  score_0_100: z.number().int().min(0).max(100),
  reason: z.string().min(1),
  summary: z.string().min(1),
  next_action: z.string().min(1),
  call_quality_flags: z.array(
    z.enum(["voicemail", "wrong_number", "language_struggle", "audio_poor", "none"])
  ),
});
export type LeadScore = z.infer<typeof LeadScore>;

// Reject any non-Latin / non-English script in CRM-facing fields.
// Devanagari = Hindi; Tamil block. Forces LLM to translate.
const NON_ENGLISH_RE = /[ऀ-ॿ]|[஀-௿]/;

export function containsNonEnglishScript(score: LeadScore): boolean {
  const haystack = JSON.stringify({
    summary: score.summary,
    reason: score.reason,
    next_action: score.next_action,
    industry: score.industry,
    current_supplier: score.current_supplier,
    chemicals: score.chemicals,
  });
  return NON_ENGLISH_RE.test(haystack);
}
