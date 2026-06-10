import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary, fetchLeadCounts } from "@/lib/billing";
import { NavBar } from "@/components/NavBar";
import Link from "next/link";

export default async function ResultsPage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing, counts] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
    fetchLeadCounts(tenantId),
  ]);

  const talkMinutes = Math.round(billing.unitsUsed * 2.5);
  const remaining = Math.max(0, billing.unitsAllowance - billing.unitsUsed);
  const usedPct =
    billing.unitsAllowance > 0
      ? Math.min(100, Math.round((billing.unitsUsed / billing.unitsAllowance) * 100))
      : 0;
  const connectRate =
    billing.totalCalls > 0
      ? Math.round((billing.completedCalls / billing.totalCalls) * 100)
      : 0;

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-6xl space-y-8 p-6">
        <header className="flex flex-col gap-1">
          <h1 className="font-display text-3xl font-semibold tracking-tight">Results</h1>
          <p className="text-muted-foreground">
            This month&apos;s calling performance and credit usage.
          </p>
        </header>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Calls completed" value={billing.completedCalls.toLocaleString()} sub={`${billing.totalCalls.toLocaleString()} dialed · ${connectRate}% connected`} />
          <Stat label="Credits used" value={billing.unitsUsed.toLocaleString()} sub={`${remaining.toLocaleString()} of ${billing.unitsAllowance.toLocaleString()} left`} />
          <Stat label="Talk time" value={`${talkMinutes.toLocaleString()} min`} sub="across all completed calls" />
          <Stat label="Est. spend" value={`₹${Math.round(billing.costInr).toLocaleString("en-IN")}`} sub="this billing cycle" />
        </section>

        {/* Credit usage bar */}
        <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-display text-lg font-semibold">Monthly credit usage</h2>
            <span className="text-sm tabular text-muted-foreground">{usedPct}% used</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={
                "h-full rounded-full transition-all " +
                (usedPct >= 90 ? "bg-hot" : usedPct >= 70 ? "bg-warm" : "bg-brand")
              }
              style={{ width: `${usedPct}%` }}
            />
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {remaining.toLocaleString()} credits ≈ {Math.round(remaining * 2.5).toLocaleString()} more
            talk-minutes.{" "}
            <Link href="/credits" className="font-medium text-brand hover:underline">
              Open the calculator →
            </Link>
          </p>
        </section>

        {/* Lead outcomes */}
        <section className="grid gap-4 sm:grid-cols-3">
          <ScoreStat label="Hot leads" value={counts.hot} tone="hot" hint="Ready to book — call now" />
          <ScoreStat label="Warm leads" value={counts.warm} tone="warm" hint="Engaged — nurture" />
          <ScoreStat
            label="Conversion"
            value={billing.completedCalls > 0 ? `${Math.round(((counts.hot + counts.warm) / billing.completedCalls) * 100)}%` : "—"}
            tone="brand"
            hint="Hot+warm per completed call"
          />
        </section>
      </main>
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1.5 font-display text-2xl font-semibold tabular">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

function ScoreStat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number | string;
  tone: "hot" | "warm" | "brand";
  hint: string;
}) {
  const dot = tone === "hot" ? "bg-hot" : tone === "warm" ? "bg-warm" : "bg-brand";
  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="mt-2 font-display text-3xl font-semibold tabular">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}
