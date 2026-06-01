"use client";
import Link from "next/link";
import { useMemo, useState, useTransition } from "react";
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

type Score = { score_0_100: number; classification: string; scored_at: string };
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

type SortKey = "score" | "name" | "company" | "created";
type SortDir = "asc" | "desc";

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

function EditableName({
  leadId,
  name,
  industry,
}: {
  leadId: string;
  name: string;
  industry: string | null;
}) {
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
      <div className="flex items-center gap-2">
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
          className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        />
      </div>
    );
  }
  return (
    <div className="group/name flex items-center gap-2">
      <Link
        className="font-medium text-slate-900 hover:underline"
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
        className="opacity-0 transition group-hover/name:opacity-100"
        title="Edit name"
        aria-label="Edit name"
      >
        <span className="text-xs text-slate-400 hover:text-slate-700">✏️</span>
      </button>
      {industry ? (
        <div className="ml-auto text-xs text-muted-foreground">{industry}</div>
      ) : null}
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
  return (
    <button
      type="button"
      onClick={() => onSort(k)}
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide",
        active ? "text-slate-900" : "text-slate-500 hover:text-slate-800",
      )}
    >
      {label}
      <span className={cn("text-[10px]", active ? "opacity-100" : "opacity-40")}>
        {active ? (sortDir === "asc" ? "▲" : "▼") : "▾"}
      </span>
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
        return (
          l.name.toLowerCase().includes(q) ||
          l.phone_e164.toLowerCase().includes(q) ||
          (l.company ?? "").toLowerCase().includes(q) ||
          (l.industry ?? "").toLowerCase().includes(q)
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
      if (sortKey === "company")
        return (a.company ?? "").localeCompare(b.company ?? "") * dir;
      return a.created_at.localeCompare(b.created_at) * dir;
    });
    return rows;
  }, [leads, filter, search, sortKey, sortDir]);

  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir(k === "name" || k === "company" ? "asc" : "desc");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <PipelineChips active={filter} counts={counts} onChange={setFilter} />
        <div className="relative w-full md:w-72">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, phone, company…"
            className="w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          />
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
            🔍
          </span>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-12 text-center">
          <p className="text-sm font-medium text-slate-700">No leads match.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {leads.length === 0
              ? "Upload a CSV or add a lead to get started."
              : "Try a different filter or clear the search."}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>
                  <SortHeader label="Name" k="name" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>
                  <SortHeader label="Company" k="company" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead>Status</TableHead>
                <TableHead>
                  <SortHeader label="Score" k="score" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead>
                  <SortHeader label="Added" k="created" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                </TableHead>
                <TableHead className="w-32 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((l) => {
                const score = latestScore(l);
                return (
                  <TableRow key={l.id} className="group hover:bg-slate-50">
                    <TableCell>
                      <EditableName
                        leadId={l.id}
                        name={l.name}
                        industry={l.industry}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{l.phone_e164}</TableCell>
                    <TableCell>{l.company ?? "—"}</TableCell>
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
                    <TableCell className="text-xs text-muted-foreground">
                      {formatWhen(l.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="invisible inline-flex group-hover:visible">
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
          Showing <b className="tabular-nums">{visible.length}</b> of{" "}
          <b className="tabular-nums">{leads.length}</b> leads
        </span>
        {filter !== "all" || search ? (
          <button
            type="button"
            onClick={() => {
              setFilter("all");
              setSearch("");
            }}
            className="font-medium text-primary hover:underline"
          >
            Clear filters
          </button>
        ) : null}
      </div>
    </div>
  );
}
