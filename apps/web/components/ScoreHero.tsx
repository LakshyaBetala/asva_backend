import { cn } from "@/lib/utils";

const TONE: Record<
  string,
  { ring: string; text: string; chip: string; sub: string }
> = {
  hot: {
    ring: "stroke-red-500",
    text: "text-red-600",
    chip: "bg-red-50 text-red-700 border-red-200",
    sub: "Call back today",
  },
  warm: {
    ring: "stroke-orange-500",
    text: "text-orange-600",
    chip: "bg-orange-50 text-orange-700 border-orange-200",
    sub: "Follow up in 3 days",
  },
  cold: {
    ring: "stroke-blue-500",
    text: "text-blue-600",
    chip: "bg-blue-50 text-blue-700 border-blue-200",
    sub: "Monthly nurture",
  },
  dead: {
    ring: "stroke-zinc-400",
    text: "text-zinc-600",
    chip: "bg-zinc-50 text-zinc-700 border-zinc-200",
    sub: "Do-not-call",
  },
};

const ACTION_COPY: Record<string, string> = {
  human_callback_today: "Call back today",
  send_quote: "Send a quote",
  send_proforma: "Send proforma invoice",
  send_sample: "Send a sample",
  followup_3d: "Schedule follow-up in 3 days",
  followup_30d: "Schedule follow-up in 30 days",
  dnc: "Mark do-not-call",
};

export function ScoreHero({
  classification,
  score,
  reason,
  nextAction,
}: {
  classification: string;
  score: number;
  reason: string;
  nextAction?: string | null;
}) {
  const tone = (TONE[classification] ?? TONE.cold)!;
  const r = 40;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.max(0, Math.min(100, score)) / 100) * circ;

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-center">
      <div className="relative h-28 w-28 shrink-0">
        <svg viewBox="0 0 100 100" className="h-28 w-28 -rotate-90">
          <circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            className="stroke-slate-100"
            strokeWidth="10"
          />
          <circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            className={cn(tone.ring, "transition-all")}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={cn("text-2xl font-bold tabular-nums", tone.text)}>{score}</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">/ 100</div>
        </div>
      </div>

      <div className="flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-semibold uppercase tracking-wide",
              tone.chip,
            )}
          >
            <span className={cn("h-2 w-2 rounded-full", tone.ring.replace("stroke-", "bg-"))} />
            {classification}
          </span>
          <span className="text-xs text-muted-foreground">{tone.sub}</span>
        </div>
        <p className="text-sm leading-relaxed text-slate-700">{reason}</p>
        {nextAction ? (
          <div className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700">
            <span>▶</span>
            <span>{ACTION_COPY[nextAction] ?? nextAction}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
