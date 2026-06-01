import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { connectTwoNumbers } from "./exotel";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  INTERNAL_API_TOKEN: string;
  EXOTEL_SID: string;
  EXOTEL_API_KEY: string;
  EXOTEL_API_TOKEN: string;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

app.post("/bridge", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);

  const { lead_id, rep_user_id } = await c.req.json<{
    lead_id: string;
    rep_user_id: string;
  }>();

  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  const { data: lead } = await sb
    .from("leads")
    .select("id,tenant_id,phone_e164")
    .eq("id", lead_id)
    .single();
  if (!lead) return c.json({ error: "lead not found" }, 404);

  const { data: rep } = await sb
    .from("users")
    .select("whatsapp")
    .eq("id", rep_user_id)
    .single();
  if (!rep?.whatsapp) return c.json({ error: "rep has no phone" }, 400);

  const { data: tenant } = await sb
    .from("tenants")
    .select("exotel_caller_id")
    .eq("id", lead.tenant_id)
    .single();
  if (!tenant?.exotel_caller_id) return c.json({ error: "tenant has no caller id" }, 400);

  try {
    const { callSid } = await connectTwoNumbers({
      sid: c.env.EXOTEL_SID,
      apiKey: c.env.EXOTEL_API_KEY,
      apiToken: c.env.EXOTEL_API_TOKEN,
      from: rep.whatsapp,
      to: lead.phone_e164,
      callerId: tenant.exotel_caller_id,
    });
    await sb.from("calls").insert({
      tenant_id: lead.tenant_id,
      lead_id: lead.id,
      samvaad_call_id: `exotel:${callSid}`,
      status: "ringing",
      kind: "human_followup",
    });
    return c.json({ ok: true, callSid });
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

export default app;
