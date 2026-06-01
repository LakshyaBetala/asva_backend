import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { fetchPlacesLeads } from "@/lib/leads/sources/places";
import { ingestLeads } from "@/lib/leads/ingest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Daily lead sync.
 *
 *   * Auth: Vercel-cron requests carry `Authorization: Bearer $CRON_SECRET`
 *     (also accepts a `?secret=` query param for manual triggers).
 *   * Loops every tenant with places_sync_enabled=true and runs Google Places
 *     textsearch over their configured industries × locations.
 *   * Quietly skips tenants with no config; returns a summary array per tenant.
 *
 * Schedule lives in vercel.json (00:30 UTC = 06:00 IST).
 */
export async function GET(req: Request) {
  const expected = process.env.CRON_SECRET;
  if (!expected) {
    return NextResponse.json({ error: "CRON_SECRET not configured" }, { status: 500 });
  }
  const url = new URL(req.url);
  const auth = req.headers.get("authorization") ?? "";
  const provided = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : url.searchParams.get("secret") ?? "";
  if (provided !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false } },
  );

  const { data: tenants, error } = await admin
    .from("tenants")
    .select("id, slug, lead_industries, lead_locations, places_sync_enabled")
    .eq("places_sync_enabled", true);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const results: Array<Record<string, unknown>> = [];
  for (const t of tenants ?? []) {
    const industries = (t.lead_industries ?? []) as string[];
    const locations = (t.lead_locations ?? []) as string[];
    if (industries.length === 0 || locations.length === 0) {
      results.push({ tenant: t.slug, skipped: "no config" });
      continue;
    }
    try {
      const fetched = await fetchPlacesLeads({ industries, locations, maxQueries: 30 });
      const summary = await ingestLeads(t.id, fetched.candidates, "google_places");
      results.push({
        tenant: t.slug,
        queries: fetched.queries,
        fetched: fetched.candidates.length,
        inserted: summary.inserted,
        duplicates: summary.duplicates,
        invalid: summary.invalid.length,
        errors: fetched.errors.length,
      });
    } catch (e) {
      results.push({ tenant: t.slug, error: (e as Error).message });
    }
  }

  return NextResponse.json({ ranAt: new Date().toISOString(), results });
}
