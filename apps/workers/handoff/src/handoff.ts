import type { SupabaseClient } from "@supabase/supabase-js";
import { buildHotLeadMessage, buildWaLink, sendResendEmail } from "./wa-email";

export async function handleHandoff(
  sb: SupabaseClient,
  args: {
    leadId: string;
    callId: string;
    appBaseUrl: string;
    resendKey: string;
    resendFrom: string;
    emailSender?: (a: { to: string; from: string; subject: string; text: string }) => Promise<void>;
  },
): Promise<{ wa: string; email: string | null }> {
  const { data: lead } = await sb
    .from("leads")
    .select("id,tenant_id,name,phone_e164,company,assigned_to")
    .eq("id", args.leadId)
    .single();
  if (!lead) throw new Error("lead not found");

  const { data: tenant } = await sb
    .from("tenants")
    .select("whatsapp_handoff_number")
    .eq("id", lead.tenant_id)
    .single();

  let repWa = tenant?.whatsapp_handoff_number ?? "";
  let repEmail: string | null = null;
  if (lead.assigned_to) {
    const { data: rep } = await sb
      .from("users")
      .select("email,whatsapp")
      .eq("id", lead.assigned_to)
      .single();
    if (rep?.whatsapp) repWa = rep.whatsapp;
    if (rep?.email) repEmail = rep.email;
  }
  if (!repWa) throw new Error("no handoff WhatsApp configured");

  const { data: score } = await sb
    .from("lead_scores")
    .select("score_0_100,summary,next_action,extracted")
    .eq("call_id", args.callId)
    .order("scored_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!score) throw new Error("no score");

  const ex: any = score.extracted ?? {};
  const message = buildHotLeadMessage({
    leadName: lead.name,
    company: lead.company,
    phone: lead.phone_e164,
    score: score.score_0_100,
    summary: score.summary,
    chemicals: ex.chemicals ?? [],
    timeline: ex.timeline ?? "unknown",
    nextAction: score.next_action ?? "Follow up",
    leadUrl: `${args.appBaseUrl}/leads/${lead.id}`,
  });
  const wa = buildWaLink(repWa, message);

  await sb.from("handoffs").insert({
    lead_id: lead.id,
    call_id: args.callId,
    channel: "whatsapp",
    sent_to: repWa,
  });

  let emailOut: string | null = null;
  if (repEmail) {
    const sender = args.emailSender ?? ((a) => sendResendEmail(args.resendKey, a));
    await sender({
      to: repEmail,
      from: args.resendFrom,
      subject: `Hot lead: ${lead.name} (${lead.company ?? ""})`,
      text: message,
    });
    await sb.from("handoffs").insert({
      lead_id: lead.id,
      call_id: args.callId,
      channel: "email",
      sent_to: repEmail,
    });
    emailOut = repEmail;
  }
  return { wa, email: emailOut };
}
