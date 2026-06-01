type Ex = {
  decision_maker?: boolean;
  industry?: string | null;
  chemicals?: string[];
  monthly_volume_kg?: number | null;
  current_supplier?: string | null;
  supplier_pain?: string[];
  timeline?: string;
  decision_maker_email?: string | null;
  decision_maker_whatsapp?: string | null;
};

function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  return String(v);
}

export function ExtractedFields({ extracted }: { extracted: Ex }) {
  const rows: [string, unknown][] = [
    ["Decision maker", extracted.decision_maker ? "Yes" : "No"],
    ["Industry", extracted.industry],
    ["Chemicals", extracted.chemicals],
    ["Volume (kg/mo)", extracted.monthly_volume_kg],
    ["Current supplier", extracted.current_supplier],
    ["Supplier pain", extracted.supplier_pain],
    ["Timeline", extracted.timeline],
    ["Email", extracted.decision_maker_email],
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
