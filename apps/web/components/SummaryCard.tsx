export function SummaryCard({
  summary,
  reason,
  nextAction,
}: {
  summary: string;
  reason: string;
  nextAction?: string | null;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed">{summary}</p>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium">Why this classification:</span> {reason}
      </p>
      {nextAction && (
        <p className="text-sm">
          <span className="font-medium">Next step:</span> {nextAction}
        </p>
      )}
    </div>
  );
}
