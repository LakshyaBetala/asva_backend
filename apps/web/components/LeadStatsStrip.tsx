import { createSupabaseServerClient } from "@/lib/supabase/server";
import { StatCard } from "./StatCard";

/**
 * Four KPI cards rendered above the leads table.
 *
 *   New today      — leads.created_at >= start of today (UTC)
 *   Calls today    — calls.created_at >= start of today
 *   Hot leads      — distinct leads with a hot lead_scores row
 *   Connect rate   — completed / total over last 7d (calls.status = 'completed')
 *
 * All four are independent count queries against existing tables — no
 * new schema. Failures degrade silently (card shows "—") because a
 * single broken metric should not blank the whole header.
 */
export async function LeadStatsStrip({ tenantId }: { tenantId: string }) {
  const sb = createSupabaseServerClient();

  const todayUtc = new Date();
  todayUtc.setUTCHours(0, 0, 0, 0);
  const todayIso = todayUtc.toISOString();

  const weekAgoUtc = new Date();
  weekAgoUtc.setUTCDate(weekAgoUtc.getUTCDate() - 7);
  const weekAgoIso = weekAgoUtc.toISOString();

  const [newToday, callsToday, hotLeads, callsWeek, completedWeek] =
    await Promise.all([
      sb
        .from("leads")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .gte("created_at", todayIso),
      sb
        .from("calls")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .gte("created_at", todayIso),
      sb
        .from("lead_scores")
        .select("lead_id", { count: "exact", head: true })
        .eq("classification", "hot"),
      sb
        .from("calls")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .gte("created_at", weekAgoIso),
      sb
        .from("calls")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .eq("status", "completed")
        .gte("created_at", weekAgoIso),
    ]);

  const total = callsWeek.count ?? 0;
  const done = completedWeek.count ?? 0;
  const rate = total > 0 ? Math.round((done / total) * 100) : null;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatCard
        label="New today"
        value={newToday.count ?? 0}
        hint="Leads added in last 24h"
        tone="info"
      />
      <StatCard
        label="Calls today"
        value={callsToday.count ?? 0}
        hint="Dialled since 00:00 UTC"
        tone="neutral"
      />
      <StatCard
        label="Hot leads"
        value={hotLeads.count ?? 0}
        hint="Scored 'hot' — call first"
        tone="hot"
      />
      <StatCard
        label="Connect rate"
        value={rate === null ? "—" : `${rate}%`}
        hint={`${done} / ${total} last 7 days`}
        tone="good"
      />
    </div>
  );
}
