/**
 * Performance / ROI calculator card for the settings page.
 *
 * Shows: calls this month, units used, hot+warm count, cost incurred,
 * potential pipeline value (hot_count × avg_order_size_inr), ROI multiple.
 * This is the "5 new businesses worth it" anchor for the customer.
 */
function fmtInr(n: number): string {
  if (n >= 10_000_000) return `₹${(n / 10_000_000).toFixed(2)} Cr`;
  if (n >= 100_000) return `₹${(n / 100_000).toFixed(2)} L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}k`;
  return `₹${n.toFixed(0)}`;
}

export function PerformanceCard({
  unitsUsed,
  unitsAllowance,
  hotCount,
  warmCount,
  costInr,
  avgOrderSizeInr,
  monthlySubscriptionInr,
}: {
  unitsUsed: number;
  unitsAllowance: number;
  hotCount: number;
  warmCount: number;
  costInr: number;
  avgOrderSizeInr: number;
  monthlySubscriptionInr: number;
}) {
  // Pipeline value: assume 100% of Hot leads close (optimistic anchor —
  // real conversion is lower but the framing is "even if a fraction
  // close, the ROI is huge").
  const pipelineValue = hotCount * avgOrderSizeInr;
  // ROI: only need ONE Hot lead to close at avg_order_size to justify
  // monthly fee. Compute "Hot-leads-needed-to-payback".
  const paybackHotLeads = avgOrderSizeInr > 0 ? Math.ceil(monthlySubscriptionInr / avgOrderSizeInr) : 0;
  const roiMultiple = monthlySubscriptionInr > 0 ? pipelineValue / monthlySubscriptionInr : 0;

  return (
    <div className="space-y-4 rounded-md border p-4">
      <h2 className="text-sm font-medium">Performance this month</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Units used" value={`${unitsUsed.toLocaleString()} / ${unitsAllowance.toLocaleString()}`} />
        <Stat label="Hot leads" value={hotCount} accent="text-red-600" />
        <Stat label="Warm leads" value={warmCount} accent="text-orange-500" />
        <Stat label="Cost so far" value={fmtInr(costInr)} />
      </div>

      <div className="rounded-md border bg-muted/30 p-3 text-sm space-y-2">
        <p>
          <strong>Pipeline opened:</strong> {fmtInr(pipelineValue)} potential
          (at your avg order of {fmtInr(avgOrderSizeInr)} × {hotCount} hot leads).
        </p>
        <p>
          <strong>Break-even:</strong> Just {paybackHotLeads} closed Hot lead{paybackHotLeads === 1 ? "" : "s"} this
          month covers the entire ₹{monthlySubscriptionInr.toLocaleString()} subscription.
        </p>
        {roiMultiple > 0 && (
          <p>
            <strong>ROI on pipeline opened:</strong> {roiMultiple.toFixed(0)}× the
            monthly subscription, assuming Hot leads close at average order
            size.
          </p>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${accent ?? ""}`}>{value}</div>
    </div>
  );
}
