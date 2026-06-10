"use client";

import { useState } from "react";

// Single source of truth for the credit economy (matches the agent's billing:
// supabase_client.update_call_status — 150-sec blocks, hard cap 4 credits/call).
const SECONDS_PER_CREDIT = 150;
const MINUTES_PER_CREDIT = SECONDS_PER_CREDIT / 60; // 2.5
const MAX_CREDITS_PER_CALL = 4;
const HARD_CAP_SECONDS = MAX_CREDITS_PER_CALL * SECONDS_PER_CREDIT; // 600s / 10 min

function clampNum(v: string, min: number, max: number, fallback: number): number {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function fmtMinutes(totalMin: number): string {
  const h = Math.floor(totalMin / 60);
  const m = Math.round(totalMin % 60);
  if (h <= 0) return `${m} min`;
  return `${h} hr ${m} min`;
}

export function CreditCalculator({ creditsRemaining }: { creditsRemaining?: number }) {
  const [credits, setCredits] = useState<number>(
    creditsRemaining && creditsRemaining > 0 ? Math.round(creditsRemaining) : 100,
  );
  const [avgCallMin, setAvgCallMin] = useState<number>(2.5);

  const totalMinutes = credits * MINUTES_PER_CREDIT;
  const creditsPerCall = Math.min(
    MAX_CREDITS_PER_CALL,
    Math.max(1, Math.ceil(avgCallMin / MINUTES_PER_CREDIT)),
  );
  const estCalls = avgCallMin > 0 ? Math.floor(totalMinutes / avgCallMin) : 0;

  return (
    <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
      {/* Calculator */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <h2 className="font-display text-lg font-semibold">Credit calculator</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          See how far your credits go. <span className="font-medium text-foreground">1 credit = 2.5 minutes</span> of talk time.
        </p>

        <div className="mt-6 space-y-6">
          <Field
            label="Credits available"
            value={credits}
            suffix="credits"
            min={0}
            max={5000}
            step={10}
            onChange={(v) => setCredits(clampNum(v, 0, 100000, 0))}
          />
          <Field
            label="Average call length"
            value={avgCallMin}
            suffix="min / call"
            min={0.5}
            max={10}
            step={0.5}
            onChange={(v) => setAvgCallMin(clampNum(v, 0.5, 10, 2.5))}
          />
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3">
          <Readout label="Total talk time" value={fmtMinutes(totalMinutes)} accent />
          <Readout label="≈ Calls you can make" value={estCalls.toLocaleString()} />
          <Readout label="Credits per call" value={`${creditsPerCall}`} />
          <Readout
            label="Cost per call"
            value={`${creditsPerCall} cr`}
            hint={`${(creditsPerCall * MINUTES_PER_CREDIT).toFixed(1)} min billed`}
          />
        </div>
      </div>

      {/* Time / seconds reference */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <h2 className="font-display text-lg font-semibold">How time &amp; credits work</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Calls bill in 150-second blocks. You&apos;re only charged for blocks you use.
        </p>

        <dl className="mt-5 divide-y divide-border text-sm">
          <Row term="1 credit" desc="150 seconds = 2.5 minutes of talk time" />
          <Row term="Billing block" desc="Each started 150s block = 1 credit" />
          <Row term="Max per call" desc="4 credits (10-minute hard cap, then auto-ends)" />
          <Row term="A 4-min call" desc="120 + 120s → rounds to 2 credits" />
          <Row term="A 90-sec call" desc="Under one block → 1 credit" />
        </dl>

        <div className="mt-5 rounded-lg bg-accent/60 p-4 text-sm text-accent-foreground">
          <span className="font-medium">Rule of thumb:</span> a tight qualify-and-book
          call runs ~2 min → <span className="font-semibold tabular">1 credit</span>. Budget
          ~<span className="font-semibold tabular">1.2 credits</span> per connected lead on average.
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  suffix,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  suffix: string;
  min: number;
  max: number;
  step: number;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <label className="text-sm font-medium">{label}</label>
        <div className="flex items-baseline gap-1.5">
          <input
            type="number"
            value={value}
            min={min}
            max={max}
            step={step}
            onChange={(e) => onChange(e.target.value)}
            className="w-24 rounded-md border border-input bg-background px-2 py-1 text-right text-sm tabular focus:border-brand focus:outline-none focus:ring-2 focus:ring-ring/30"
          />
          <span className="text-xs text-muted-foreground">{suffix}</span>
        </div>
      </div>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(e.target.value)}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-brand"
      />
    </div>
  );
}

function Readout({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={
        "rounded-lg border p-3 " +
        (accent ? "border-brand/30 bg-brand/5" : "border-border bg-muted/40")
      }
    >
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={"mt-1 font-display text-xl font-semibold tabular " + (accent ? "text-brand" : "")}>
        {value}
      </div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

function Row({ term, desc }: { term: string; desc: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <dt className="font-medium">{term}</dt>
      <dd className="text-right text-muted-foreground">{desc}</dd>
    </div>
  );
}
