"use client";
import Link from "next/link";
import { useMemo, useState, useTransition } from "react";
import { Search, Pencil, ChevronsUpDown, ArrowUp, ArrowDown, CalendarCheck2 } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LeadStatusBadge } from "./LeadStatusBadge";
import { ScoreBar } from "./ScoreBar";
import { CallNowButton } from "./CallNowButton";
import { PipelineChips, type ChipCounts, type Classification } from "./PipelineChips";
import { cn } from "@/lib/utils";
import { updateLeadNameAction } from "@/app/leads/actions";
import { toast } from "sonner";

// Broker-relevant fields the post-call scorer extracts from the transcript.
type Extracted = {
  intent?: string | null;
  budget_range?: string | null;
  locality?: string | null;
  bhk?: string | null;
  site_visit_slot?: string | null;
  product_interest?: string | null;
};

type Score = {
  score_0_100: number;
  classification: string;
  scored_at: string;
  next_action?: string | null;
  extracted?: Extracted | null;
};

export type LeadRow = {
  id: string;
  name: string;
  phone_e164: string;
  company: string | null;
  industry: string | null;
  status: string;
  created_at: string;
  lead_scores?: Score[] | null;
};

type SortKey = "score" | "name" | "created";
type SortDir = "asc" | "desc";

// Same vocabulary as the pipeline board — one language across the CRM.
const NEXT_ACTION_COPY: Record<string, string> = {
  book_site_visit: "Confirm site visit",
  human_callback_today: "Callback today",
  send_listings: "Share listings",
  send_brochure: "Send brochure",
  followup_3d: "Follow up in 3d",
  followup_30d: "Follow up in 30d",
  dnc: "Mark DNC",
  send_quote: "Share listings",
  send_proforma: "Send confirmation",
  send_sample: "Send brochure",
};

function latestScore(l: LeadRow): Score | null {
  if (!l.lead_scores || l.lead_scores.length === 0) return null;
  return [...l.lead_scores].sort((a, b) => b.scored_at.localeCompare(a.scored_at))[0]!;
}

function leadClassification(l: LeadRow): Classification {
  const s = latestScore(l);
  if (!s) return "unscored";
  if (s.classification === "hot" || s.classification === "warm" || s.classification === "cold") {
    return s.classification;
  }
  return "unscored";
}

function formatWhen(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** "2 BHK · Adyar · ₹80–90L" — the line a broker scans the table by. */
function requirementParts(l: LeadRow): string[] {
  const ex = latestScore(l)?.extracted ?? null;
  const parts: string[] = [];
  if (ex?.bhk) parts.push(/bhk/i.test(ex.bhk) ? ex.bhk : `${ex.bhk} BHK`);
  if (ex?.locality) parts.push(ex.locality);
  if (ex?.budget_range) parts.push(ex.budget_range);
  if (parts.length === 0 && ex?.product_interest) parts.push(ex.product_interest);
  return parts;
}

function intentLabel(l: LeadRow): string | null {
  const intent = latestScore(l)?.extracted?.intent;
  if (!intent) return null;
  if (intent === "buy") return "Buy";
  if (intent === "rent") return "Rent";
  if (intent === "not_sure_yet") return null;
  return intent.charAt(0).toUpperCase() + intent.slice(1);
}

function EditableName({ leadId, name }: { leadId: string; name: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [pending, start] = useTransition();

  function save() {
    if (value.trim() === name) {
      setEditing(false);
      return;
    }
    start(async () => {
      const r = await updateLeadNameAction(leadId, value);
      if (r.error) {
        toast.error(r.error);
        setValue(name);
      } else {
        toast.success("Name updated");
      }
      setEditing(false);
    });
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") {
            setValue(name);
            setEditing(false);
          }
        }}
        disabled={pending}
        className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    );
  }
  return (
    <div className="group/name flex items-center gap-2">
      <Link
        className="font-medium text-foreground transition-colors hover:text-brand"
        href={`/leads/${leadId}`}
      >
        {name}
      </Link>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          setEditing(true);
        }}
        className="text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover/name:opacity-100"
        title="Edit name"
        aria-label="Edit name"
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function SortHeader({
  label,
  k,
  sortKey,
  sortDir,
  onSort,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const active = sortKey === k;
  const Icon = active ? (sortDir === "asc" ? ArrowUp : ArrowDown) : ChevronsUpDown;
  return (
    <button
      type="button"
      onClick={() => onSort(k)}
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide transition-colors",
        active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <Icon className={cn("h-3 w-3", active ? "opacity-100" : "opacity-40")} />
    </button>
  );
}

export function LeadsExplorer({ leads }: { leads: LeadRow[] }) {
  const [filter, setFilter] = useState<Classification>("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const counts: ChipCounts = useMemo(() => {
    const c: ChipCounts = { all: leads.length, hot: 0, warm: 0, cold: 0, unscored: 0 };
    for (const l of leads) c[leadClassification(l)]++;
    return c;
  }, [leads]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = leads;
    if (filter !== "all") {
      rows = rows.filter((l) => leadClassification(l) === filter);
    }
    if (q) {
      rows = rows.filter((l) => {
        const ex = latestScore(l)?.extracted;
        return (
          l.name.toLowerCase().includes(q) ||
          l.phone_e164.toLowerCase().includes(q) ||
          (l.company ?? "").toLowerCase().includes(q) ||
          (ex?.locality ?? "").toLowerCase().includes(q) ||
          (ex?.bhk ?? "").toLowerCase().includes(q) ||
          (ex?.budget_range ?? "").toLowerCase().includes(q) ||
          (ex?.product_interest ?? "").toLowerCase().includes(q)
        );
      });
    }
    const dir = sortDir === "asc" ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      if (sortKey === "score") {
        const sa = latestScore(a)?.score_0_100 ?? -1;
        const sb = latestScore(b)?.score_0_100 ?? -1;
        return (sa - sb) * dir;
      }
      if (sortKey === "name") return a.name.localeCompare(b.name) * dir;
      return a.created_at.localeCompare(b.created_at) * dir;
    });
    return rows;
  }, [leads, filter, search, sortKey, sortDir]);

  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir(k === "name" ? "asc" : "desc");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <PipelineChips active={filter} counts={counts} onChange={setFilter} />
        <div className="relative w-full md:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, locality, budget, BHK…"
            className="w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-muted/40 p-12 text-center">
          <p className="text-sm font-medium text-foreground">No leads match.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {leads.length === 0
              ? "Upload a CSV or add a lead to get started."
              : "Try a different filter or clear the search."}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 hover:bg-muted/40">
                <TableHead>
                  <SortHeader label="Lead" k="name" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead>Requirement</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>
                  <SortHeader label="Score" k="score" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead>Next action</TableHead>
                <TableHead>
                  <SortHeader label="Added" k="created" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead className="w-28 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((l, i) => {
                const score = latestScore(l);
                const req = requirementParts(l);
                const intent = intentLabel(l);
                const visit = score?.extracted?.site_visit_slot ?? null;
                return (
                  <TableRow
                    key={l.id}
                    className="group animate-row-in transition-colors hover:bg-muted/40"
                    style={{ animationDelay: `${Math.min(i, 14) * 28}ms` }}
                  >
                    <TableCell>
                      <EditableName leadId={l.id} name={l.name} />
                      <div className="mt-0.5 font-mono text-[11px] tabular text-muted-foreground">
                        {l.phone_e164}
                        {l.company ? <span className="font-sans"> · {l.company}</span> : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      {req.length > 0 || intent || visit ? (
                        <div className="flex max-w-[26ch] flex-wrap items-center gap-1.5">
                          {intent ? (
                            <span className="rounded-md bg-accent px-1.5 py-0.5 text-[11px] font-semibold text-accent-foreground">
                              {intent}
                            </span>
                          ) : null}
                          {req.map((p) => (
                            <span
                              key={p}
                              className="rounded-md border border-border bg-muted/50 px-1.5 py-0.5 text-[11px] font-medium text-foreground/80"
                            >
                              {p}
                            </span>
                          ))}
                          {visit ? (
                            <span
                              className="inline-flex items-center gap-1 rounded-md bg-brand/10 px-1.5 py-0.5 text-[11px] font-semibold text-brand"
                              title={`Site visit: ${visit}`}
                            >
                              <CalendarCheck2 className="h-3 w-3" />
                              {visit}
                            </span>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {score ? "—" : "Not called yet"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <LeadStatusBadge status={l.status} />
                    </TableCell>
                    <TableCell>
                      {score ? (
                        <ScoreBar
                          classification={score.classification}
                          score={score.score_0_100}
                        />
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {score?.next_action ? (
                        <span className="text-xs font-medium text-foreground/80">
                          {NEXT_ACTION_COPY[score.next_action] ?? score.next_action}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatWhen(l.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="inline-flex opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover:opacity-100">
                        <CallNowButton leadId={l.id} phone={l.phone_e164} />
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Showing <b className="tabular text-foreground">{visible.length}</b> of{" "}
          <b className="tabular text-foreground">{leads.length}</b> leads
        </span>
        {filter !== "all" || search ? (
          <button
            type="button"
            onClick={() => {
              setFilter("all");
              setSearch("");
            }}
            className="font-medium text-brand transition-colors hover:underline"
          >
            Clear filters
          </button>
        ) : null}
      </div>
    </div>
  );
}
