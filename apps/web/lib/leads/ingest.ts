import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { toE164 } from "@ai-voice/shared";

export type LeadCandidate = {
  name: string;
  phone: string;
  company?: string | null;
  industry?: string | null;
  source?: string | null;
  notes?: string | null;
};

export type IngestSummary = {
  inserted: number;
  duplicates: number;
  invalid: { input: LeadCandidate; reason: string }[];
  source: string;
};

function serviceClient(): SupabaseClient {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false } },
  );
}

export async function ingestLeads(
  tenantId: string,
  candidates: LeadCandidate[],
  defaultSource: string,
): Promise<IngestSummary> {
  const sb = serviceClient();
  const invalid: IngestSummary["invalid"] = [];
  const rows: Array<{
    tenant_id: string;
    name: string;
    phone_e164: string;
    company: string | null;
    industry: string | null;
    source: string;
    notes: string | null;
    status: "new";
  }> = [];

  const seen = new Set<string>();
  for (const c of candidates) {
    if (!c?.name?.trim()) {
      invalid.push({ input: c, reason: "missing name" });
      continue;
    }
    let phone: string;
    try {
      phone = toE164(c.phone ?? "");
    } catch (e) {
      invalid.push({ input: c, reason: (e as Error).message });
      continue;
    }
    if (seen.has(phone)) continue;
    seen.add(phone);
    rows.push({
      tenant_id: tenantId,
      name: c.name.trim().slice(0, 200),
      phone_e164: phone,
      company: c.company?.trim() || null,
      industry: c.industry?.trim() || null,
      source: c.source?.trim() || defaultSource,
      notes: c.notes?.trim() || null,
      status: "new",
    });
  }

  if (rows.length === 0) {
    return { inserted: 0, duplicates: 0, invalid, source: defaultSource };
  }

  const phones = rows.map((r) => r.phone_e164);
  const { data: existing } = await sb
    .from("leads")
    .select("phone_e164")
    .eq("tenant_id", tenantId)
    .in("phone_e164", phones);
  const existingSet = new Set((existing ?? []).map((r) => r.phone_e164));

  const fresh = rows.filter((r) => !existingSet.has(r.phone_e164));
  const duplicates = rows.length - fresh.length;

  let inserted = 0;
  if (fresh.length > 0) {
    const { error, count } = await sb
      .from("leads")
      .insert(fresh, { count: "exact" });
    if (error) throw new Error(`insert failed: ${error.message}`);
    inserted = count ?? fresh.length;
  }

  return { inserted, duplicates, invalid, source: defaultSource };
}
