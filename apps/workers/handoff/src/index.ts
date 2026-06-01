import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { handleHandoff } from "./handoff";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  INTERNAL_API_TOKEN: string;
  APP_BASE_URL: string;
  RESEND_API_KEY: string;
  RESEND_FROM: string;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

app.post("/handoff", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);

  const { lead_id, call_id } = await c.req.json<{ lead_id: string; call_id: string }>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  try {
    const out = await handleHandoff(sb, {
      leadId: lead_id,
      callId: call_id,
      appBaseUrl: c.env.APP_BASE_URL,
      resendKey: c.env.RESEND_API_KEY,
      resendFrom: c.env.RESEND_FROM,
    });
    return c.json(out);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

export default app;
