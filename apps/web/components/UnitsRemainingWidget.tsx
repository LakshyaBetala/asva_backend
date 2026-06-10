/**
 * Monthly billing unit counter shown in the navbar.
 *
 * "1,247 / 2,000 units used" — turns amber at 80%, red at 100%, blue
 * when within the 10% wiggle room, dark red past wiggle.
 *
 * Reads from the tenant_monthly_units view (rolled-up sum of
 * calls.billed_units for the current calendar month).
 */
function statusLabel(used: number, allowance: number, wigglePct: number): {
  colour: string;
  label: string;
} {
  if (allowance <= 0) return { colour: "text-muted-foreground", label: "No allowance" };
  const pct = (used / allowance) * 100;
  const wiggleCeiling = allowance * (1 + wigglePct / 100);

  if (used >= wiggleCeiling) return { colour: "text-hot", label: "Overage" };
  if (used >= allowance) return { colour: "text-cold", label: "Bonus" };
  if (pct >= 90) return { colour: "text-warm", label: "90%+" };
  if (pct >= 80) return { colour: "text-warm", label: "80%+" };
  return { colour: "text-brand", label: "OK" };
}

export function UnitsRemainingWidget({
  unitsUsed,
  allowance,
  wigglePct = 10,
}: {
  unitsUsed: number;
  allowance: number;
  wigglePct?: number;
}) {
  const { colour, label } = statusLabel(unitsUsed, allowance, wigglePct);
  const pct = allowance > 0 ? Math.min(100, (unitsUsed / allowance) * 100) : 0;
  return (
    <div className="flex items-center gap-3" title={`${label} — ${wigglePct}% wiggle room`}>
      <div className={`text-xs font-mono ${colour}`}>
        {unitsUsed.toLocaleString()} / {allowance.toLocaleString()}
      </div>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={pct >= 100 ? "h-full bg-hot" : pct >= 80 ? "h-full bg-warm" : "h-full bg-brand"}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
