import { cn } from "@/lib/utils";

type Tone = "neutral" | "hot" | "good" | "info";

const toneStyles: Record<Tone, { ring: string; value: string; label: string; bg: string }> = {
  neutral: {
    ring: "ring-border",
    value: "text-foreground",
    label: "text-muted-foreground",
    bg: "bg-card",
  },
  hot: {
    ring: "ring-hot/20",
    value: "text-hot",
    label: "text-hot/70",
    bg: "bg-gradient-to-br from-hot/5 to-card",
  },
  good: {
    ring: "ring-brand/20",
    value: "text-brand",
    label: "text-brand/70",
    bg: "bg-gradient-to-br from-brand/5 to-card",
  },
  info: {
    ring: "ring-cold/20",
    value: "text-cold",
    label: "text-cold/70",
    bg: "bg-gradient-to-br from-cold/5 to-card",
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
      <div className={cn("font-display text-3xl font-semibold tabular-nums", s.value)}>
        {value}
      </div>
      {hint ? (
        <div className="text-xs text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}
