import { notFound } from "next/navigation";
import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { LeadStatusBadge } from "@/components/LeadStatusBadge";
import { ScoreHero } from "@/components/ScoreHero";
import { ExtractedFields } from "@/components/ExtractedFields";
import { TranscriptView } from "@/components/TranscriptView";
import { DncDialog } from "@/components/DncDialog";
import { StartAiCallButton } from "@/components/StartAiCallButton";
import { CallNowButton } from "@/components/CallNowButton";
import { NavBar } from "@/components/NavBar";
import { QualificationPanel } from "@/components/QualificationPanel";

export default async function LeadDetail({
  params,
}: {
  params: { id: string };
}) {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
  ]);
  const { data: lead } = await supabase
    .from("leads")
    .select("*")
    .eq("id", params.id)
    .single();
  if (!lead) notFound();

  const [{ data: latestScore }, { data: latestSlots }] = await Promise.all([
    supabase
      .from("lead_scores")
      .select("*")
      .eq("lead_id", lead.id)
      .order("scored_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("qualification_slots")
      .select("*")
      .eq("lead_id", lead.id)
      .order("updated_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-4xl space-y-6 p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">{lead.name}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              <span className="font-mono tabular">{lead.phone_e164}</span>
              {lead.company ? <> · {lead.company}</> : null}
              {lead.industry ? <> · {lead.industry}</> : null}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CallNowButton leadId={lead.id} phone={lead.phone_e164} />
            <StartAiCallButton
              leadId={lead.id}
              defaultLang={lead.preferred_lang ?? "ta-IN"}
              defaultGender={lead.preferred_voice_gender ?? "female"}
            />
            <LeadStatusBadge status={lead.status} />
            <DncDialog leadId={lead.id} phone={lead.phone_e164} />
          </div>
        </header>

        <section className="space-y-4 rounded-xl border border-border bg-card p-6 shadow-sm">
          <div className="flex items-baseline justify-between">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              AI verdict
            </h2>
            {latestScore?.scored_at ? (
              <span className="text-xs text-muted-foreground">
                Scored {new Date(latestScore.scored_at).toLocaleString()}
              </span>
            ) : null}
          </div>
          {latestScore ? (
            <>
              <ScoreHero
                classification={latestScore.classification}
                score={latestScore.score_0_100}
                reason={latestScore.reason}
                nextAction={latestScore.next_action}
              />
              {latestScore.summary ? (
                <div className="rounded-lg border border-border bg-muted/40 p-4">
                  <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Call summary
                  </div>
                  <p className="text-sm leading-relaxed text-foreground/80">
                    {latestScore.summary}
                  </p>
                </div>
              ) : null}
              <div className="border-t pt-4">
                <ExtractedFields extracted={latestScore.extracted ?? {}} />
              </div>
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-border bg-muted/40 p-6 text-center">
              <p className="text-sm font-medium text-foreground">No call yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Click <strong>Call with AI</strong> to dial Priya. The verdict
                appears here ~30 seconds after the call ends.
              </p>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <h2 className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Live qualification
          </h2>
          <QualificationPanel slots={(latestSlots as any) ?? null} />
        </section>

        <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Transcript
          </h2>
          <TranscriptView leadId={lead.id} />
        </section>
      </main>
    </>
  );
}
