"use server";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { toE164 } from "@ai-voice/shared";
import { createSupabaseServerClient } from "@/lib/supabase/server";

const FormSchema = z.object({
  name: z.string().min(1),
  phone: z.string().min(7),
  company: z.string().optional().nullable(),
  industry: z.string().optional().nullable(),
});

export async function addLeadAction(formData: FormData) {
  const parsed = FormSchema.safeParse({
    name: formData.get("name"),
    phone: formData.get("phone"),
    company: formData.get("company") || null,
    industry: formData.get("industry") || null,
  });
  if (!parsed.success) return { error: parsed.error.issues[0]!.message };

  let phone_e164: string;
  try {
    phone_e164 = toE164(parsed.data.phone);
  } catch (e) {
    return { error: (e as Error).message };
  }

  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: "unauthorized" };
  const { data: profile } = await supabase
    .from("users")
    .select("tenant_id")
    .eq("id", user.id)
    .single();
  if (!profile?.tenant_id) return { error: "no tenant" };

  const { error } = await supabase.from("leads").insert({
    tenant_id: profile.tenant_id,
    name: parsed.data.name,
    phone_e164,
    company: parsed.data.company,
    industry: parsed.data.industry,
    status: "new",
  });
  if (error) return { error: error.message };
  revalidatePath("/leads");
  return { ok: true };
}

export async function updateLeadNameAction(leadId: string, name: string) {
  const clean = name.trim();
  if (!clean) return { error: "name cannot be empty" };
  const supabase = createSupabaseServerClient();
  const { error } = await supabase
    .from("leads")
    .update({ name: clean })
    .eq("id", leadId);
  if (error) return { error: error.message };
  revalidatePath("/leads");
  revalidatePath(`/leads/${leadId}`);
  return { ok: true };
}

export async function updateLeadClassificationAction(
  leadId: string,
  classification: "hot" | "warm" | "cold" | "dead",
) {
  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: "unauthorized" };
  const { data: profile } = await supabase
    .from("users")
    .select("tenant_id")
    .eq("id", user.id)
    .single();
  if (!profile?.tenant_id) return { error: "no tenant" };

  const score = classification === "hot" ? 90
    : classification === "warm" ? 65
    : classification === "cold" ? 35 : 10;
  const nextAction = classification === "hot" ? "human_callback_today"
    : classification === "warm" ? "followup_3d"
    : classification === "cold" ? "followup_30d" : "dnc";

  const { error } = await supabase.from("lead_scores").insert({
    lead_id: leadId,
    classification,
    score_0_100: score,
    reason: "manual override from pipeline board",
    summary: "Operator moved this lead manually.",
    next_action: nextAction,
    extracted: {},
  });
  if (error) return { error: error.message };
  revalidatePath("/leads");
  revalidatePath("/leads/pipeline");
  revalidatePath(`/leads/${leadId}`);
  return { ok: true };
}

export async function markDncAction(leadId: string, phone_e164: string) {
  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: "unauthorized" };
  const { data: profile } = await supabase
    .from("users")
    .select("tenant_id")
    .eq("id", user.id)
    .single();
  if (!profile?.tenant_id) return { error: "no tenant" };

  const { error: e1 } = await supabase
    .from("leads")
    .update({ status: "do_not_call" })
    .eq("id", leadId);
  if (e1) return { error: e1.message };
  await supabase.from("dnc_list").upsert({
    tenant_id: profile.tenant_id,
    phone_e164,
    reason: "manual",
  });
  revalidatePath("/leads");
  revalidatePath(`/leads/${leadId}`);
  return { ok: true };
}

type CallPrefs = {
  lang?: "ta-IN" | "hi-IN" | "en-IN";
  gender?: "female" | "male";
};

export async function startAiCallAction(leadId: string, prefs: CallPrefs = {}) {
  const url = process.env.CAMPAIGNS_WORKER_URL;
  const token = process.env.INTERNAL_API_TOKEN;
  if (!url || !token) return { error: "campaigns worker not configured" };

  if (prefs.lang || prefs.gender) {
    const supabase = createSupabaseServerClient();
    await supabase
      .from("leads")
      .update({
        ...(prefs.lang && { preferred_lang: prefs.lang }),
        ...(prefs.gender && { preferred_voice_gender: prefs.gender }),
      })
      .eq("id", leadId);
  }

  const res = await fetch(`${url}/dispatch`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      lead_id: leadId,
      lang: prefs.lang,
      voice_gender: prefs.gender,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { error: (body as any).error ?? "dispatch failed" };
  }
  revalidatePath(`/leads/${leadId}`);
  return { ok: true };
}

export async function bridgeCallAction(leadId: string) {
  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: "unauthorized" };

  const url = process.env.CLICKTOCALL_WORKER_URL;
  const token = process.env.INTERNAL_API_TOKEN;
  if (!url || !token) return { error: "clicktocall worker not configured" };

  const res = await fetch(`${url}/bridge`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ lead_id: leadId, rep_user_id: user.id }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { error: (body as any).error ?? "bridge failed" };
  }
  return { ok: true };
}
