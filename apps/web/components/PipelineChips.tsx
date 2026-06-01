"use client";
import { cn } from "@/lib/utils";

export type Classification = "all" | "hot" | "warm" | "cold" | "unscored";

export type ChipCounts = Record<Classification, number>;

const tone: Record<Classification, { active: string; idle: string; dot: string }> = {
  all: {
    active: "bg-slate-900 text-white border-slate-900",
    idle: "border-slate-300 text-slate-700 hover:bg-slate-50",
    dot: "bg-slate-500",
  },
  hot: {
    active: "bg-red-600 text-white border-red-700",
    idle: "border-red-200 text-red-700 hover:bg-red-50",
    dot: "bg-red-500",
  },
  warm: {
    active: "bg-orange-500 text-white border-orange-600",
    idle: "border-orange-200 text-orange-700 hover:bg-orange-50",
    dot: "bg-orange-500",
  },
  cold: {
    active: "bg-blue-600 text-white border-blue-700",
    idle: "border-blue-200 text-blue-700 hover:bg-blue-50",
    dot: "bg-blue-500",
  },
  unscored: {
    active: "bg-zinc-700 text-white border-zinc-800",
    idle: "border-zinc-200 text-zinc-600 hover:bg-zinc-50",
    dot: "bg-zinc-400",
  },
};

const labels: Record<Classification, string> = {
  all: "All",
  hot: "Hot",
  warm: "Warm",
  cold: "Cold",
  unscored: "Unscored",
};

export function PipelineChips({
  active,
  counts,
  onChange,
}: {
  active: Classification;
  counts: ChipCounts;
  onChange: (next: Classification) => void;
}) {
  const order: Classification[] = ["all", "hot", "warm", "cold", "unscored"];
  return (
    <div className="flex flex-wrap gap-2">
      {order.map((c) => {
        const isActive = c === active;
        const styles = tone[c];
        return (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium transition-colors",
              isActive ? styles.active : styles.idle,
            )}
            aria-pressed={isActive}
          >
            <span className={cn("h-2 w-2 rounded-full", styles.dot)} />
            <span>{labels[c]}</span>
            <span
              className={cn(
                "ml-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                isActive ? "bg-white/20" : "bg-slate-100 text-slate-700",
              )}
            >
              {counts[c]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
