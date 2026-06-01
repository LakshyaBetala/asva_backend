/**
 * Live qualification slot panel. Renders on /leads/[id].
 *
 * Reads from public.qualification_slots (one row per call). Shows the
 * 8 extracted slots with confidence-based dimming — slots Priya is
 * <0.5 sure about are shown faded so the user knows they're uncertain.
 */
type Slots = {
  product_interest: string | null;
  volume_monthly_kg: number | null;
  buying_frequency: string;
  current_supplier: string | null;
  pain_point: string | null;
  decision_role: string;
  timeline_days: number | null;
  buying_confidence: number;
  slot_confidence: Record<string, number> | null;
  last_turn_idx: number;
};

function Slot({
  label,
  value,
  confidence,
}: {
  label: string;
  value: string | number | null | undefined;
  confidence?: number;
}) {
  const display = value === null || value === undefined || value === "" ? "—" : String(value);
  const isEmpty = display === "—" || display.toLowerCase() === "unknown";
  const conf = confidence ?? 0;
  const opacity = isEmpty ? "opacity-50" : conf < 0.5 && conf > 0 ? "opacity-60" : "";
  return (
    <div className={`rounded-md border p-3 ${opacity}`}>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-medium">{display}</div>
      {conf > 0 && !isEmpty && (
        <div className="mt-1 text-[10px] text-muted-foreground">
          confidence {Math.round(conf * 100)}%
        </div>
      )}
    </div>
  );
}

function BuyingConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colour = value >= 0.7 ? "bg-red-600" : value >= 0.5 ? "bg-orange-500" : "bg-zinc-400";
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          Buying confidence
        </span>
        <span className="text-sm font-semibold">{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full ${colour} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function QualificationPanel({ slots }: { slots: Slots | null }) {
  if (!slots) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        No qualification data yet. The 8 slots will populate live as Priya talks
        with the lead.
      </div>
    );
  }

  const sc = slots.slot_confidence ?? {};
  return (
    <div className="space-y-4">
      <BuyingConfidenceBar value={slots.buying_confidence ?? 0} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Slot
          label="Product interest"
          value={slots.product_interest}
          confidence={sc.product_interest}
        />
        <Slot
          label="Volume (kg/mo)"
          value={slots.volume_monthly_kg}
          confidence={sc.volume_monthly_kg}
        />
        <Slot
          label="Buying frequency"
          value={slots.buying_frequency}
          confidence={sc.buying_frequency}
        />
        <Slot
          label="Current supplier"
          value={slots.current_supplier}
          confidence={sc.current_supplier}
        />
        <Slot
          label="Pain point"
          value={slots.pain_point}
          confidence={sc.pain_point}
        />
        <Slot
          label="Decision role"
          value={slots.decision_role}
          confidence={sc.decision_role}
        />
        <Slot
          label="Timeline (days)"
          value={slots.timeline_days}
          confidence={sc.timeline_days}
        />
        <Slot label="Turns processed" value={slots.last_turn_idx} />
      </div>
    </div>
  );
}
