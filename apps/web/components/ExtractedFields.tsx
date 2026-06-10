type Ex = {
  // Broker-native
  intent?: string | null;
  budget_range?: string | null;
  locality?: string | null;
  bhk?: string | null;
  possession_timeline?: string | null;
  purpose?: string | null;
  loan_status?: string | null;
  site_visit_slot?: string | null;
  source_channel?: string | null;
  // Interim / shared
  product_interest?: string | null;
  pain_point?: string | null;
  timeline_days?: number | null;
  decision_maker_whatsapp?: string | null;
};

function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  return String(v);
}

export function ExtractedFields({ extracted }: { extracted: Ex }) {
  const moveIn =
    extracted.possession_timeline ??
    (extracted.timeline_days != null ? `${extracted.timeline_days} days` : null);

  const rows: [string, unknown][] = [
    ["Buy / Rent", extracted.intent],
    ["Budget", extracted.budget_range],
    ["Locality", extracted.locality],
    ["BHK", extracted.bhk],
    ["Move-in timeline", moveIn],
    ["Purpose", extracted.purpose],
    ["Loan status", extracted.loan_status],
    ["Looking for", extracted.product_interest],
    ["Key requirement", extracted.pain_point],
    ["Site visit", extracted.site_visit_slot],
    ["Source", extracted.source_channel],
    ["WhatsApp", extracted.decision_maker_whatsapp],
  ];
  return (
    <dl className="space-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-3 gap-2 text-sm">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="col-span-2">{fmt(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
