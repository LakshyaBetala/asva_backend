import Link from "next/link";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LeadStatusBadge } from "./LeadStatusBadge";
import { ScoreBadge } from "./ScoreBadge";

type Score = { score_0_100: number; classification: string; scored_at: string };
type Lead = {
  id: string;
  name: string;
  phone_e164: string;
  company: string | null;
  industry: string | null;
  status: string;
  lead_scores?: Score[] | null;
};

export function LeadsTable({ leads }: { leads: Lead[] }) {
  if (leads.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No leads yet. Upload a CSV or add a lead to get started.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Phone</TableHead>
          <TableHead>Company</TableHead>
          <TableHead>Industry</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Score</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {leads.map((l) => {
          const latestScore =
            l.lead_scores && l.lead_scores.length > 0
              ? [...l.lead_scores].sort((a, b) =>
                  b.scored_at.localeCompare(a.scored_at),
                )[0]
              : null;
          return (
            <TableRow key={l.id}>
              <TableCell>
                <Link className="font-medium hover:underline" href={`/leads/${l.id}`}>
                  {l.name}
                </Link>
              </TableCell>
              <TableCell className="font-mono text-xs">{l.phone_e164}</TableCell>
              <TableCell>{l.company ?? "—"}</TableCell>
              <TableCell>{l.industry ?? "—"}</TableCell>
              <TableCell>
                <LeadStatusBadge status={l.status} />
              </TableCell>
              <TableCell>
                {latestScore ? (
                  <ScoreBadge
                    classification={latestScore.classification}
                    score={latestScore.score_0_100}
                  />
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
