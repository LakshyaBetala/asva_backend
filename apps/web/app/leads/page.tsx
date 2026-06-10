import Link from "next/link";
import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { LeadsExplorer } from "@/components/LeadsExplorer";
import { LeadStatsStrip } from "@/components/LeadStatsStrip";
import { CsvUploadDialog } from "@/components/CsvUpload";
import { ManualLeadDialog } from "@/components/ManualLeadDialog";
import { SyncFromGoogleButton } from "@/components/SyncFromGoogleButton";
import { LeadsRealtimeRefresher } from "@/components/LeadsRealtimeRefresher";
import { NavBar } from "@/components/NavBar";

export default async function LeadsPage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
  ]);
  const { data: leads, error } = await supabase
    .from("leads")
    .select(
      "id,name,phone_e164,company,industry,status,created_at,lead_scores(score_0_100,classification,scored_at,next_action,extracted)",
    )
    .order("created_at", { ascending: false })
    .limit(500);

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-6xl space-y-6 p-6">
        <LeadsRealtimeRefresher />

        <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Leads</h1>
            <p className="mt-1 text-muted-foreground">
              Filter by score, search by locality or budget, call from any row.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/leads/pipeline"
              className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent"
            >
              Pipeline view
            </Link>
            <SyncFromGoogleButton />
            <ManualLeadDialog />
            <CsvUploadDialog />
          </div>
        </header>

        <LeadStatsStrip tenantId={tenantId} />

        {error ? (
          <p className="text-sm text-destructive">Error: {error.message}</p>
        ) : (
          <LeadsExplorer leads={(leads ?? []) as any} />
        )}
      </main>
    </>
  );
}
