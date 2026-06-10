import { cn } from "@/lib/utils";
import { ArrowRight } from "lucide-react";

const TONE: Record<
  string,
  { ring: string; text: string; chip: string; sub: string }
> = {
  hot: {
    ring: "stroke-hot",
    text: "text-hot",
    chip: "bg-hot/10 text-hot border-hot/20",
    sub: "Call back today",
  },
  warm: {
    ring: "stroke-warm",
    text: "text-warm",
    chip: "bg-warm/10 text-warm border-warm/20",
    sub: "Follow up in 3 days",
  },
  cold: {
    ring: "stroke-cold",
    text: "text-cold",
    chip: "bg-cold/10 text-cold border-cold/20",
    sub: "Monthly nurture",
  },
  dead: {
    ring: "stroke-muted-foreground",
    text: "text-muted-foreground",
    chip: "bg-muted text-muted-foreground border-border",
    sub: "Do-not-call",
  },
};

const ACTION_COPY: Record<string, string> = {
  // Broker actions
  book_site_visit: "Confirm the site visit",
  human_callback_today: "Call back today",
  send_listings: "Share matching listings",
  send_brochure: "Send brochure / details",
  followup_3d: "Schedule follow-up in 3 days",
  followup_30d: "Schedule follow-up in 30 days",
  dnc: "Mark do-not-call",
  // Legacy keys (old rows) → broker meaning
  send_quote: "Share matching listings",
  send_proforma: "Send site-visit confirmation",
  send_sample: "Send brochure / details",
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
            className="stroke-muted"
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
          <div className={cn("font-display text-2xl font-bold tabular-nums", tone.text)}>{score}</div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">/ 100</div>
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
        <p className="text-sm leading-relaxed text-foreground/80">{reason}</p>
        {nextAction ? (
          <div className="inline-flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-1.5 text-xs font-medium text-foreground">
            <ArrowRight className="h-3.5 w-3.5 text-brand" />
            <span>{ACTION_COPY[nextAction] ?? nextAction}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
