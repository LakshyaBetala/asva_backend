/**
 * Live qualification slot panel. Renders on /leads/[id].
 *
 * Broker-grade slots — what a real-estate agent needs to book a site visit:
 * intent (buy/rent), budget, locality, BHK, move-in timeline, requirement.
 * Reads from public.qualification_slots (one row per call). Slots Priya is
 * <0.5 sure about are dimmed so the broker knows they're uncertain.
 *
 * NOTE: budget/locality/bhk/intent become first-class once the slots-jsonb
 * migration lands (task #101). Until then they read from the broker-native
 * keys if present and fall back to the interim catch-all (`looking_for`).
 */
type Slots = {
  // Broker-native (post-migration / when the extractor fills them)
  intent?: string | null;            // buy / rent / not_sure_yet
  budget_range?: string | null;      // "80L-1.2Cr" or "15k-30k rent"
  locality?: string | null;          // canonical area, e.g. "Adyar"
  bhk?: string | null;               // 1 / 2 / 3 / 4+
  possession_timeline?: string | null;

  // Interim / existing columns
  product_interest: string | null;   // catch-all: "2 BHK Adyar, buy"
  pain_point: string | null;         // key requirement / must-have
  timeline_days: number | null;      // move-in timeline in days
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
    <div className={`rounded-md border border-border p-3 ${opacity}`}>
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
  const colour = value >= 0.7 ? "bg-hot" : value >= 0.5 ? "bg-warm" : "bg-cold";
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          Buying intent
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
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        No qualification data yet. Budget, locality, BHK and the site-visit slot
        populate live as Priya talks with the lead.
      </div>
    );
  }

  const sc = slots.slot_confidence ?? {};
  const moveIn =
    slots.possession_timeline ??
    (slots.timeline_days != null ? `${slots.timeline_days} days` : null);

  return (
    <div className="space-y-4">
      <BuyingConfidenceBar value={slots.buying_confidence ?? 0} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Slot label="Buy / Rent" value={slots.intent} confidence={sc.intent} />
        <Slot label="Budget" value={slots.budget_range} confidence={sc.budget_range} />
        <Slot label="Locality" value={slots.locality} confidence={sc.locality} />
        <Slot label="BHK" value={slots.bhk} confidence={sc.bhk} />
        <Slot label="Move-in" value={moveIn} confidence={sc.timeline_days} />
        <Slot
          label="Looking for"
          value={slots.product_interest}
          confidence={sc.product_interest}
        />
        <Slot label="Key requirement" value={slots.pain_point} confidence={sc.pain_point} />
      </div>
    </div>
  );
}
