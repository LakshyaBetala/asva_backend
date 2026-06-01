import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { SamvaadProvider } from "@ai-voice/shared";
import { dispatchSingleCall } from "./dispatch";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SARVAM_API_KEY: string;
  SARVAM_BASE_URL: string;
  INTERNAL_API_TOKEN: string;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

app.post("/dispatch", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);

  const body = await c.req.json<{ lead_id: string; campaign_id?: string }>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const provider = new SamvaadProvider({
    apiKey: c.env.SARVAM_API_KEY,
    baseUrl: c.env.SARVAM_BASE_URL,
  });
  try {
    const r = await dispatchSingleCall(sb, provider, {
      leadId: body.lead_id,
      campaignId: body.campaign_id,
    });
    return c.json(r);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 400);
  }
});

export default app;
