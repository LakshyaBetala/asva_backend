"use client";
import Link from "next/link";
import { useMemo, useState, useTransition } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { updateLeadClassificationAction } from "@/app/leads/actions";

type Tier = "hot" | "warm" | "cold" | "dead";

export type PipelineLead = {
  id: string;
  name: string;
  phone_e164: string;
  company: string | null;
  industry: string | null;
  classification: Tier | "unscored";
  score: number | null;
  reason: string | null;
  next_action: string | null;
  updated_at: string;
};

const COLS: {
  key: Tier;
  title: string;
  sub: string;
  bg: string;
  border: string;
  dot: string;
  badge: string;
}[] = [
  {
    key: "hot",
    title: "Hot",
    sub: "Call back today",
    bg: "bg-hot/5",
    border: "border-hot/20",
    dot: "bg-hot",
    badge: "bg-hot/10 text-hot border-hot/20",
  },
  {
    key: "warm",
    title: "Warm",
    sub: "Follow up in 3 days",
    bg: "bg-warm/5",
    border: "border-warm/20",
    dot: "bg-warm",
    badge: "bg-warm/10 text-warm border-warm/20",
  },
  {
    key: "cold",
    title: "Cold",
    sub: "Monthly nurture",
    bg: "bg-cold/5",
    border: "border-cold/20",
    dot: "bg-cold",
    badge: "bg-cold/10 text-cold border-cold/20",
  },
  {
    key: "dead",
    title: "Dead",
    sub: "Do-not-call",
    bg: "bg-muted/40",
    border: "border-border",
    dot: "bg-muted-foreground",
    badge: "bg-muted text-muted-foreground border-border",
  },
];

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  const diffMin = Math.floor((Date.now() - t) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const h = Math.floor(diffMin / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const NEXT_ACTION_COPY: Record<string, string> = {
  // Broker actions
  book_site_visit: "Confirm site visit",
  human_callback_today: "Callback today",
  send_listings: "Share listings",
  send_brochure: "Send brochure",
  followup_3d: "Follow up in 3d",
  followup_30d: "Follow up in 30d",
  dnc: "Mark DNC",
  // Legacy keys (old rows)
  send_quote: "Share listings",
  send_proforma: "Send confirmation",
  send_sample: "Send brochure",
};

export function PipelineBoard({ leads }: { leads: PipelineLead[] }) {
  const [optimistic, setOptimistic] = useState<Record<string, Tier>>({});
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [, start] = useTransition();
  const [dragOver, setDragOver] = useState<Tier | null>(null);
  const [search, setSearch] = useState("");

  const grouped = useMemo(() => {
    const byTier: Record<Tier, PipelineLead[]> = { hot: [], warm: [], cold: [], dead: [] };
    const q = search.trim().toLowerCase();
    for (const l of leads) {
      if (q) {
        const hay = `${l.name} ${l.phone_e164} ${l.company ?? ""} ${l.industry ?? ""}`.toLowerCase();
        if (!hay.includes(q)) continue;
      }
      const tier = (optimistic[l.id] ?? l.classification) as Tier;
      if (tier === "hot" || tier === "warm" || tier === "cold" || tier === "dead") {
        byTier[tier].push(l);
      } else {
        byTier.cold.push(l); // unscored shown in cold column
      }
    }
    return byTier;
  }, [leads, optimistic, search]);

  function move(leadId: string, target: Tier) {
    setOptimistic((m) => ({ ...m, [leadId]: target }));
    setPendingId(leadId);
    start(async () => {
      const r = await updateLeadClassificationAction(leadId, target);
      setPendingId(null);
      if (r.error) {
        toast.error(r.error);
        setOptimistic((m) => {
          const c = { ...m };
          delete c[leadId];
          return c;
        });
      } else {
        toast.success(`Moved to ${target}`);
      }
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search across columns…"
          className="w-full max-w-sm rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        />
        <div className="text-xs text-muted-foreground">
          Drag cards between columns to reclassify · {leads.length} total
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {COLS.map((col) => {
          const rows = grouped[col.key];
          const isOver = dragOver === col.key;
          return (
            <div
              key={col.key}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(col.key);
              }}
              onDragLeave={() => setDragOver(null)}
              onDrop={(e) => {
                e.preventDefault();
                const leadId = e.dataTransfer.getData("text/lead-id");
                setDragOver(null);
                if (leadId) move(leadId, col.key);
              }}
              className={cn(
                "flex min-h-[60vh] flex-col rounded-xl border transition",
                col.bg,
                col.border,
                isOver && "ring-2 ring-primary/40",
              )}
            >
              <div className="flex items-center justify-between border-b border-black/5 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className={cn("h-2.5 w-2.5 rounded-full", col.dot)} />
                  <div>
                    <div className="text-sm font-semibold text-foreground">{col.title}</div>
                    <div className="text-[11px] text-muted-foreground">{col.sub}</div>
                  </div>
                </div>
                <span className="rounded-full bg-card px-2 py-0.5 text-xs font-semibold tabular-nums text-foreground shadow-sm">
                  {rows.length}
                </span>
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto p-3">
                {rows.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border bg-background/40 p-4 text-center text-xs text-muted-foreground">
                    Drop a lead here to mark {col.title.toLowerCase()}.
                  </div>
                ) : (
                  rows.map((lead) => (
                    <div
                      key={lead.id}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/lead-id", lead.id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      className={cn(
                        "group cursor-grab rounded-lg border bg-card p-3 shadow-sm transition hover:shadow-md active:cursor-grabbing",
                        col.border,
                        pendingId === lead.id && "opacity-60",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <Link
                          href={`/leads/${lead.id}`}
                          className="font-medium text-foreground transition-colors hover:text-brand"
                        >
                          {lead.name}
                        </Link>
                        {lead.score !== null ? (
                          <span
                            className={cn(
                              "rounded-md border px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                              col.badge,
                            )}
                          >
                            {lead.score}
                          </span>
                        ) : null}
                      </div>
                      {lead.company ? (
                        <div className="mt-0.5 text-xs text-muted-foreground">{lead.company}</div>
                      ) : null}
                      <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                        {lead.phone_e164}
                      </div>
                      {lead.reason ? (
                        <div className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                          {lead.reason}
                        </div>
                      ) : null}
                      <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
                        <span className="text-[10px] text-muted-foreground">
                          {relativeTime(lead.updated_at)}
                        </span>
                        {lead.next_action ? (
                          <span className="text-[10px] font-medium text-foreground/70">
                            {NEXT_ACTION_COPY[lead.next_action] ?? lead.next_action}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
