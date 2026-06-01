import { cn } from "@/lib/utils";

const fill: Record<string, string> = {
  hot: "bg-red-500",
  warm: "bg-orange-500",
  cold: "bg-blue-500",
};

const text: Record<string, string> = {
  hot: "text-red-700",
  warm: "text-orange-700",
  cold: "text-blue-700",
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
            text[classification] ?? "text-zinc-700",
          )}
        >
          {classification}
        </span>
        <span className="tabular-nums text-muted-foreground">{score}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn("h-full rounded-full", fill[classification] ?? "bg-zinc-400")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
