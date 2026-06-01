/**
 * Per-tenant billing rollup helper for the navbar units widget + settings.
 *
 * Reads from public.tenant_monthly_units view (migration 20260522180100).
 * View aggregates calls.billed_units + estimated_cost_inr by tenant + month.
 */
import { createSupabaseServerClient } from "./supabase/server";

export type BillingSummary = {
  unitsUsed: number;
  costInr: number;
  completedCalls: number;
  totalCalls: number;
  unitsAllowance: number;
  wigglePct: number;
  overagePolicy: "continue_billed" | "hard_pause";
  overageRateInr: number;
  avgOrderSizeInr: number;
  dailySpendCapInr: number;
  monthlySubscriptionInr: number;
};

// Default subscription used when tenants.monthly_subscription_inr is not
// modelled yet. SPC pricing per spec: ₹15k for client #1.
const DEFAULT_MONTHLY_SUBSCRIPTION_INR = 15000;

export async function fetchBillingSummary(tenantId: string): Promise<BillingSummary> {
  const sb = createSupabaseServerClient();

  const monthStart = new Date();
  monthStart.setUTCDate(1);
  monthStart.setUTCHours(0, 0, 0, 0);

  const [tenantRow, rollupRow] = await Promise.all([
    sb
      .from("tenants")
      .select(
        "monthly_unit_allowance, overage_policy, overage_rate_inr, wiggle_room_pct, avg_order_size_inr, daily_spend_cap_inr",
      )
      .eq("id", tenantId)
      .single(),
    sb
      .from("tenant_monthly_units")
      .select("units_used, cost_inr, completed_calls, total_calls")
      .eq("tenant_id", tenantId)
      .gte("month_start", monthStart.toISOString())
      .order("month_start", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  const t: any = tenantRow.data ?? {};
  const r: any = rollupRow.data ?? {};

  return {
    unitsUsed: Number(r.units_used ?? 0),
    costInr: Number(r.cost_inr ?? 0),
    completedCalls: Number(r.completed_calls ?? 0),
    totalCalls: Number(r.total_calls ?? 0),
    unitsAllowance: Number(t.monthly_unit_allowance ?? 2000),
    wigglePct: Number(t.wiggle_room_pct ?? 10),
    overagePolicy: (t.overage_policy as "continue_billed" | "hard_pause") ?? "continue_billed",
    overageRateInr: Number(t.overage_rate_inr ?? 10),
    avgOrderSizeInr: Number(t.avg_order_size_inr ?? 200000),
    dailySpendCapInr: Number(t.daily_spend_cap_inr ?? 600),
    monthlySubscriptionInr: DEFAULT_MONTHLY_SUBSCRIPTION_INR,
  };
}

export async function fetchLeadCounts(tenantId: string): Promise<{ hot: number; warm: number }> {
  const sb = createSupabaseServerClient();
  const [{ count: hot }, { count: warm }] = await Promise.all([
    sb
      .from("leads")
      .select("id", { count: "exact", head: true })
      .eq("tenant_id", tenantId)
      .eq("status", "hot"),
    sb
      .from("leads")
      .select("id", { count: "exact", head: true })
      .eq("tenant_id", tenantId)
      .eq("status", "warm"),
  ]);
  return { hot: hot ?? 0, warm: warm ?? 0 };
}
