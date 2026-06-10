import { cn } from "@/lib/utils";

const fill: Record<string, string> = {
  hot: "bg-hot",
  warm: "bg-warm",
  cold: "bg-cold",
};

const text: Record<string, string> = {
  hot: "text-hot",
  warm: "text-warm",
  cold: "text-cold",
};

export function ScoreBar({
  classification,
  score,
}: {
  classification: string;
  score: number;
}) {
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div className="flex w-32 flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <span
          className={cn(
            "font-semibold uppercase tracking-wide",
            text[classification] ?? "text-muted-foreground",
          )}
        >
          {classification}
        </span>
        <span className="tabular-nums text-muted-foreground">{score}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "animate-bar-fill h-full rounded-full transition-all duration-500",
            fill[classification] ?? "bg-muted-foreground",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
