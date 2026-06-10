import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { NavBar } from "@/components/NavBar";
import { CreditCalculator } from "@/components/CreditCalculator";

export default async function CreditsPage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
  ]);

  const remaining = Math.max(0, billing.unitsAllowance - billing.unitsUsed);
  const remainingMin = remaining * 2.5;
  const remainingLabel =
    remainingMin >= 60
      ? `${Math.floor(remainingMin / 60)} hr ${Math.round(remainingMin % 60)} min`
      : `${Math.round(remainingMin)} min`;

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-6xl space-y-8 p-6">
        <header>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Credits</h1>
          <p className="mt-1.5 text-muted-foreground">
            You have{" "}
            <span className="font-semibold tabular text-foreground">
              {remaining.toLocaleString()}
            </span>{" "}
            credits left this month — about{" "}
            <span className="font-semibold text-foreground">{remainingLabel}</span> of talk time.
          </p>
        </header>
        <CreditCalculator creditsRemaining={remaining} />
      </main>
    </>
  );
}
