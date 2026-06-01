import Link from "next/link";
import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { NavBar } from "@/components/NavBar";
import { PipelineBoard, type PipelineLead } from "@/components/PipelineBoard";

type ScoreRow = {
  classification: string;
  score_0_100: number;
  reason: string;
  next_action: string;
  scored_at: string;
};

export default async function PipelinePage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
  ]);

  const { data: leads } = await supabase
    .from("leads")
    .select(
      "id,name,phone_e164,company,industry,created_at,lead_scores(classification,score_0_100,reason,next_action,scored_at)",
    )
    .order("created_at", { ascending: false })
    .limit(500);

  const rows: PipelineLead[] = (leads ?? []).map((l: any) => {
    const scores = (l.lead_scores ?? []) as ScoreRow[];
    const latest = scores.length
      ? scores.slice().sort((a, b) => b.scored_at.localeCompare(a.scored_at))[0]
      : null;
    const cls = (latest?.classification ?? "unscored") as PipelineLead["classification"];
    return {
      id: l.id,
      name: l.name,
      phone_e164: l.phone_e164,
      company: l.company,
      industry: l.industry,
      classification: cls,
      score: latest?.score_0_100 ?? null,
      reason: latest?.reason ?? null,
      next_action: latest?.next_action ?? null,
      updated_at: latest?.scored_at ?? l.created_at,
    };
  });

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-7xl space-y-6 p-6">
        <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
            <p className="text-sm text-muted-foreground">
              Hot → Warm → Cold → Dead. Drag a card to reclassify.
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/leads"
              className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent"
            >
              Table view
            </Link>
          </div>
        </header>

        <PipelineBoard leads={rows} />
      </main>
    </>
  );
}
