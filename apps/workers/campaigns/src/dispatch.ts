import type { SupabaseClient } from "@supabase/supabase-js";
import type { VoiceProvider } from "@ai-voice/shared";

// Projected cost of a single 180s "unit" call. Mirrors
// apps/pipecat-agent/src/voice_agent/cost_guard.py:project_next_call_cost_inr().
// Pessimistic — used for the daily-cap admission check before dial.
const PROJECTED_UNIT_COST_INR = 12.0;

export async function dispatchSingleCall(
  sb: SupabaseClient,
  provider: VoiceProvider,
  args: { leadId: string; campaignId?: string },
): Promise<{ providerCallId: string }> {
  const { data: lead } = await sb.from("leads").select("*").eq("id", args.leadId).single();
  if (!lead) throw new Error("lead not found");
  if (lead.status === "do_not_call") throw new Error("lead is DNC");

  const { data: tenant } = await sb
    .from("tenants")
    .select(
      "samvaad_agent_id,exotel_caller_id,persona_lang_default,agent_enabled,telephony_mode,byon_provider,byon_from_number,daily_spend_cap_inr",
    )
    .eq("id", lead.tenant_id)
    .single();
  if (!tenant?.samvaad_agent_id) {
    throw new Error("tenant not provisioned for voice");
  }
  if (tenant.agent_enabled === false) {
    throw new Error("agent_disabled");
  }

  // Cost guardrail: refuse to dispatch if today's projected cost would
  // exceed the tenant's daily spend cap. tenant_spend_today() is the SQL
  // helper from migration 20260522180200_tenant_overage.sql.
  if (typeof tenant.daily_spend_cap_inr === "number" && tenant.daily_spend_cap_inr > 0) {
    const { data: spendRow } = await sb.rpc("tenant_spend_today", {
      p_tenant_id: lead.tenant_id,
    });
    const spentToday = typeof spendRow === "number" ? spendRow : Number(spendRow ?? 0);
    if (spentToday + PROJECTED_UNIT_COST_INR > tenant.daily_spend_cap_inr) {
      throw new Error("daily_cap_reached");
    }
  }
  const fromNumber =
    tenant.telephony_mode === "byon"
      ? tenant.byon_from_number
      : tenant.exotel_caller_id;
  if (!fromNumber) {
    throw new Error("tenant not provisioned for voice");
  }

  const { data: dnc } = await sb
    .from("dnc_list")
    .select("phone_e164")
    .eq("tenant_id", lead.tenant_id)
    .eq("phone_e164", lead.phone_e164)
    .single();
  if (dnc) throw new Error("phone on DNC list");

  await sb.from("leads").update({ status: "queued" }).eq("id", lead.id);

  // Extract first name for personalized greeting. Indian lead names are
  // often "First Last" or "First Middle Last"; we take only the first
  // token, trimmed, and reject if it's clearly a placeholder.
  const firstNameRaw = (lead.name ?? "").trim().split(/\s+/)[0] ?? "";
  const firstName =
    firstNameRaw.length >= 2 && !/^(unknown|n\/?a|test|na)$/i.test(firstNameRaw)
      ? firstNameRaw
      : "";

  const { providerCallId } = await provider.startCall({
    agentId: tenant.samvaad_agent_id,
    to_e164: lead.phone_e164,
    callerId: fromNumber,
    langHint: tenant.persona_lang_default as any,
    metadata: {
      lead_id: lead.id,
      tenant_id: lead.tenant_id,
      campaign_id: args.campaignId,
      lead_first_name: firstName,
      lead_company: lead.company ?? "",
    } as any,
  });

  await sb.from("calls").insert({
    tenant_id: lead.tenant_id,
    lead_id: lead.id,
    campaign_id: args.campaignId ?? null,
    samvaad_call_id: providerCallId,
    status: "queued",
    kind: "ai_outbound",
  });
  await sb.from("leads").update({ status: "calling" }).eq("id", lead.id);
  return { providerCallId };
}
