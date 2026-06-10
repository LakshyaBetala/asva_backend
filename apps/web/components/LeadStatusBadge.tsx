import { Badge } from "@/components/ui/badge";

const color: Record<string, string> = {
  new: "bg-muted text-muted-foreground border-border",
  queued: "bg-cold/10 text-cold border-cold/20",
  calling: "bg-warm/10 text-warm border-warm/20",
  called: "bg-muted text-foreground border-border",
  hot: "bg-hot/10 text-hot border-hot/20",
  warm: "bg-warm/10 text-warm border-warm/20",
  cold: "bg-cold/10 text-cold border-cold/20",
  do_not_call: "bg-foreground text-background border-foreground",
  needs_review: "bg-accent text-accent-foreground border-brand/20",
};

const label: Record<string, string> = {
  new: "New",
  queued: "Queued",
  calling: "Calling",
  called: "Called",
  hot: "Hot",
  warm: "Warm",
  cold: "Cold",
  do_not_call: "Do-not-call",
  needs_review: "Needs review",
};

export function LeadStatusBadge({ status }: { status: string }) {
  return (
    <Badge className={color[status] ?? "bg-muted text-muted-foreground border-border"}>
      {label[status] ?? status}
    </Badge>
  );
}
