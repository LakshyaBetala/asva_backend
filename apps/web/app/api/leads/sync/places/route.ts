import { NextResponse } from "next/server";
import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchPlacesLeads } from "@/lib/leads/sources/places";
import { ingestLeads } from "@/lib/leads/ingest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const { tenantId } = await requireTenant();

  const sb = createSupabaseServerClient();
  const { data: tenant, error } = await sb
    .from("tenants")
    .select("lead_industries, lead_locations")
    .eq("id", tenantId)
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const industries = (tenant?.lead_industries ?? []) as string[];
  const locations = (tenant?.lead_locations ?? []) as string[];

  if (industries.length === 0 || locations.length === 0) {
    return NextResponse.json(
      {
        error:
          "No industries or locations configured for this tenant. Update tenants.lead_industries / tenants.lead_locations.",
      },
      { status: 400 },
    );
  }

  const result = await fetchPlacesLeads({ industries, locations, maxQueries: 30 });

  if (!process.env.GOOGLE_PLACES_API_KEY) {
    return NextResponse.json(
      {
        error: "GOOGLE_PLACES_API_KEY not set",
        hint: "Add GOOGLE_PLACES_API_KEY to apps/web/.env.local and restart the dev server.",
      },
      { status: 503 },
    );
  }

  const summary = await ingestLeads(tenantId, result.candidates, "google_places");

  return NextResponse.json({
    fetched: result.candidates.length,
    queries: result.queries,
    inserted: summary.inserted,
    duplicates: summary.duplicates,
    invalid: summary.invalid.length,
    errors: result.errors,
  });
}
