import { Badge } from "@/components/ui/badge";

const tone = (c: string) =>
  c === "hot"
    ? "bg-red-600 text-white border-red-700"
    : c === "warm"
      ? "bg-orange-500 text-white border-orange-600"
      : "bg-zinc-500 text-white border-zinc-600";

export function ScoreBadge({
  classification,
  score,
}: {
  classification: string;
  score: number;
}) {
  return (
    <Badge className={`${tone(classification)} px-3 py-1 text-sm`}>
      {classification.toUpperCase()} · {score}/100
    </Badge>
  );
}
