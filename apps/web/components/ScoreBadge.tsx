import { Badge } from "@/components/ui/badge";

const tone = (c: string) =>
  c === "hot"
    ? "bg-hot text-white border-hot"
    : c === "warm"
      ? "bg-warm text-white border-warm"
      : "bg-cold text-white border-cold";

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
