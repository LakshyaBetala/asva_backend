import { Hono } from "hono";
import { SamvaadProvider } from "@ai-voice/shared";
import { adminClient } from "./supabase-admin";
import { handleSamvaadEvent } from "./samvaad-handler";
import { fetchAndStoreRecording } from "./r2";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SAMVAAD_WEBHOOK_SECRET: string;
  SARVAM_API_KEY: string;
  SARVAM_BASE_URL: string;
  SCORE_WORKER_URL: string;
  INTERNAL_API_TOKEN: string;
  RECORDINGS: R2Bucket;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

app.post("/samvaad", async (c) => {
  const provider = new SamvaadProvider({
    apiKey: c.env.SARVAM_API_KEY,
    baseUrl: c.env.SARVAM_BASE_URL,
  });

  let evt;
  try {
    evt = await provider.parseWebhook(c.req.raw, {
      secret: c.env.SAMVAAD_WEBHOOK_SECRET,
    });
  } catch (e) {
    return c.json({ error: (e as Error).message }, 401);
  }

  const sb = adminClient(c.env);

  await handleSamvaadEvent(sb, evt, {
    onCallEnded: async (callId) => {
      await fetch(`${c.env.SCORE_WORKER_URL}/score`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${c.env.INTERNAL_API_TOKEN}`,
        },
        body: JSON.stringify({ call_id: callId }),
      });
    },
  });

  if (evt.kind === "recording.ready") {
    const { data: call } = await sb
      .from("calls")
      .select("id,tenant_id,samvaad_call_id")
      .eq("samvaad_call_id", evt.call_id)
      .single();
    if (call) {
      try {
        const key = await fetchAndStoreRecording(c.env, call as any);
        await sb.from("calls").update({ recording_r2_key: key }).eq("id", call.id);
      } catch (e) {
        console.error("recording upload failed", e);
      }
    }
  }

  return c.json({ ok: true });
});

export default app;
