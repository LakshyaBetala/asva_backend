"use client";
import { cn } from "@/lib/utils";

export type Classification = "all" | "hot" | "warm" | "cold" | "unscored";

export type ChipCounts = Record<Classification, number>;

const tone: Record<Classification, { active: string; idle: string; dot: string }> = {
  all: {
    active: "bg-foreground text-background border-foreground",
    idle: "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
    dot: "bg-muted-foreground",
  },
  hot: {
    active: "bg-hot text-white border-hot",
    idle: "border-hot/30 text-hot hover:bg-hot/5",
    dot: "bg-hot",
  },
  warm: {
    active: "bg-warm text-white border-warm",
    idle: "border-warm/30 text-warm hover:bg-warm/5",
    dot: "bg-warm",
  },
  cold: {
    active: "bg-cold text-white border-cold",
    idle: "border-cold/30 text-cold hover:bg-cold/5",
    dot: "bg-cold",
  },
  unscored: {
    active: "bg-muted-foreground text-white border-muted-foreground",
    idle: "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
    dot: "bg-muted-foreground",
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
              "inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium transition-colors active:scale-[0.97]",
              isActive ? styles.active : styles.idle,
            )}
            aria-pressed={isActive}
          >
            <span className={cn("h-2 w-2 rounded-full", styles.dot)} />
            <span>{labels[c]}</span>
            <span
              className={cn(
                "ml-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                isActive ? "bg-white/20" : "bg-muted text-muted-foreground",
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
