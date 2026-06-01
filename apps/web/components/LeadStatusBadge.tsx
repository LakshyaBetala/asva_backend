import { Badge } from "@/components/ui/badge";

const color: Record<string, string> = {
  new: "bg-slate-100 text-slate-800 border-slate-200",
  queued: "bg-blue-100 text-blue-800 border-blue-200",
  calling: "bg-amber-100 text-amber-800 border-amber-200",
  called: "bg-gray-100 text-gray-800 border-gray-200",
  hot: "bg-red-100 text-red-800 border-red-200",
  warm: "bg-orange-100 text-orange-800 border-orange-200",
  cold: "bg-zinc-100 text-zinc-800 border-zinc-200",
  do_not_call: "bg-black text-white border-black",
  needs_review: "bg-purple-100 text-purple-800 border-purple-200",
};

export function LeadStatusBadge({ status }: { status: string }) {
  return <Badge className={color[status] ?? "bg-slate-100"}>{status}</Badge>;
}
