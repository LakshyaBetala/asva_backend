import { cn } from "@/lib/utils";

type Tone = "neutral" | "hot" | "good" | "info";

const toneStyles: Record<Tone, { ring: string; value: string; label: string; bg: string }> = {
  neutral: {
    ring: "ring-slate-200",
    value: "text-slate-900",
    label: "text-slate-500",
    bg: "bg-white",
  },
  hot: {
    ring: "ring-red-200",
    value: "text-red-700",
    label: "text-red-500",
    bg: "bg-gradient-to-br from-red-50 to-white",
  },
  good: {
    ring: "ring-emerald-200",
    value: "text-emerald-700",
    label: "text-emerald-600",
    bg: "bg-gradient-to-br from-emerald-50 to-white",
  },
  info: {
    ring: "ring-blue-200",
    value: "text-blue-700",
    label: "text-blue-600",
    bg: "bg-gradient-to-br from-blue-50 to-white",
  },
};

export function StatCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: Tone;
}) {
  const s = toneStyles[tone];
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-xl p-4 shadow-sm ring-1",
        s.ring,
        s.bg,
      )}
    >
      <div className={cn("text-xs font-medium uppercase tracking-wide", s.label)}>
        {label}
      </div>
      <div className={cn("text-3xl font-semibold tabular-nums", s.value)}>
        {value}
      </div>
      {hint ? (
        <div className="text-xs text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}
