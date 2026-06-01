import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { ingestLeads, type LeadCandidate } from "@/lib/leads/ingest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_ROWS = 1000;

/**
 * Generic third-party lead ingest webhook.
 *
 *   curl -X POST $URL/api/leads/ingest \
 *     -H "Authorization: Bearer <tenants.ingest_api_key>" \
 *     -H "Content-Type: application/json" \
 *     -d '[{"name":"...","phone":"...","company":"..."}]'
 *
 * Accepts an array of candidates, or {"leads":[...], "source":"..."}.
 * Source defaults to "webhook". Phone numbers are normalised to E.164 (IN
 * default region), duplicates against (tenant_id, phone_e164) are skipped.
 */
export async function POST(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const token = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : auth.trim();
  if (!token) {
    return NextResponse.json({ error: "missing bearer token" }, { status: 401 });
  }

  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false } },
  );
  const { data: tenant, error: tErr } = await admin
    .from("tenants")
    .select("id")
    .eq("ingest_api_key", token)
    .maybeSingle();
  if (tErr) return NextResponse.json({ error: tErr.message }, { status: 500 });
  if (!tenant) return NextResponse.json({ error: "invalid token" }, { status: 401 });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  let candidates: LeadCandidate[];
  let source = "webhook";
  if (Array.isArray(body)) {
    candidates = body as LeadCandidate[];
  } else if (body && typeof body === "object" && Array.isArray((body as any).leads)) {
    candidates = (body as any).leads as LeadCandidate[];
    if (typeof (body as any).source === "string") source = (body as any).source;
  } else {
    return NextResponse.json(
      { error: "body must be a leads array or { leads: [...] }" },
      { status: 400 },
    );
  }

  if (candidates.length > MAX_ROWS) {
    return NextResponse.json(
      { error: `too many rows (max ${MAX_ROWS})` },
      { status: 413 },
    );
  }

  try {
    const summary = await ingestLeads(tenant.id, candidates, source);
    return NextResponse.json({
      inserted: summary.inserted,
      duplicates: summary.duplicates,
      invalid: summary.invalid,
      source: summary.source,
    });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}
