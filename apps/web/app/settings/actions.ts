"use server";
import { z } from "zod";
import { revalidatePath } from "next/cache";
import { createSupabaseServerClient } from "@/lib/supabase/server";

const Schema = z.object({
  persona_name: z.string().min(1).max(60),
  persona_lang_default: z.enum(["en-IN", "hi-IN", "ta-IN"]),
  exotel_caller_id: z.string().optional().nullable(),
  whatsapp_handoff_number: z.string().optional().nullable(),
  agent_enabled: z.boolean(),
  telephony_mode: z.enum(["managed", "byon"]),
  byon_provider: z.enum(["exotel", "plivo", "tata"]).optional().nullable(),
  byon_from_number: z.string().optional().nullable(),
  // CP3 billing fields
  monthly_unit_allowance: z.coerce.number().int().min(0).max(1_000_000).optional(),
  wiggle_room_pct: z.coerce.number().int().min(0).max(50).optional(),
  overage_rate_inr: z.coerce.number().min(0).max(1000).optional(),
  daily_spend_cap_inr: z.coerce.number().min(0).max(1_000_000).optional(),
  avg_order_size_inr: z.coerce.number().min(0).max(100_000_000).optional(),
  overage_policy: z.enum(["continue_billed", "hard_pause"]).optional(),
});

export async function updateTenantSettingsAction(fd: FormData) {
  const parsed = Schema.safeParse({
    persona_name: fd.get("persona_name"),
    persona_lang_default: fd.get("persona_lang_default"),
    exotel_caller_id: fd.get("exotel_caller_id") || null,
    whatsapp_handoff_number: fd.get("whatsapp_handoff_number") || null,
    agent_enabled: fd.get("agent_enabled") === "on",
    telephony_mode: fd.get("telephony_mode") || "managed",
    byon_provider: fd.get("byon_provider") || null,
    byon_from_number: fd.get("byon_from_number") || null,
    monthly_unit_allowance: fd.get("monthly_unit_allowance") || undefined,
    wiggle_room_pct: fd.get("wiggle_room_pct") || undefined,
    overage_rate_inr: fd.get("overage_rate_inr") || undefined,
    daily_spend_cap_inr: fd.get("daily_spend_cap_inr") || undefined,
    avg_order_size_inr: fd.get("avg_order_size_inr") || undefined,
    overage_policy: fd.get("overage_policy") || undefined,
  });
  if (!parsed.success) return { error: parsed.error.issues[0]!.message };
  if (
    parsed.data.telephony_mode === "byon" &&
    (!parsed.data.byon_provider || !parsed.data.byon_from_number)
  ) {
    return { error: "BYON requires provider and from-number" };
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

  const { error } = await supabase
    .from("tenants")
    .update(parsed.data)
    .eq("id", profile.tenant_id);
  if (error) return { error: error.message };
  revalidatePath("/settings");
  return { ok: true };
}
