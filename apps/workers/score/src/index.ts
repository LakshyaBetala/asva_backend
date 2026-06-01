import { Hono } from "hono";
import { createClient } from "@supabase/supabase-js";
import { scoreTranscript, callSarvamLlm } from "./score";
import { handleScoreLive } from "./score-live";

type Env = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SARVAM_BASE_URL: string;
  SARVAM_API_KEY: string;
  INTERNAL_API_TOKEN: string;
  HANDOFF_WORKER_URL: string;
};

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

// Per-turn live scoring. The voice agent calls this every turn with the
// latest extracted qualification slots; we persist + update lead status.
app.post("/score-live", (c) =>
  handleScoreLive(c, (env) =>
    createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    }) as any,
  ),
);

app.post("/score", async (c) => {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) return c.json({ error: "unauthorized" }, 401);

  const { call_id } = await c.req.json<{ call_id: string }>();
  const sb = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  const { data: call } = await sb
    .from("calls")
    .select("id,lead_id,tenant_id")
    .eq("id", call_id)
    .single();
  if (!call) return c.json({ error: "call not found" }, 404);

  const { data: lines } = await sb
    .from("transcripts")
    .select("speaker,text,lang")
    .eq("call_id", call.id)
    .order("idx");
  if (!lines || lines.length === 0) {
    await sb.from("leads").update({ status: "needs_review" }).eq("id", call.lead_id);
    return c.json({ error: "empty transcript" }, 400);
  }

  let score;
  try {
    score = await scoreTranscript(lines as any, {
      callLlm: (p) => callSarvamLlm(c.env, p),
    });
  } catch (e) {
    await sb.from("leads").update({ status: "needs_review" }).eq("id", call.lead_id);
    return c.json({ error: (e as Error).message }, 500);
  }

  await sb.from("lead_scores").insert({
    lead_id: call.lead_id,
    call_id: call.id,
    classification: score.classification,
    score_0_100: score.score_0_100,
    reason: score.reason,
    summary: score.summary,
    next_action: score.next_action,
    extracted: {
      decision_maker: score.decision_maker,
      industry: score.industry,
      chemicals: score.chemicals,
      monthly_volume_kg: score.monthly_volume_kg,
      current_supplier: score.current_supplier,
      supplier_pain: score.supplier_pain,
      timeline: score.timeline,
      decision_maker_email: score.decision_maker_email,
      decision_maker_whatsapp: score.decision_maker_whatsapp,
    },
    call_quality_flags: score.call_quality_flags,
  });
  await sb.from("leads").update({ status: score.classification }).eq("id", call.lead_id);

  if (score.classification === "hot") {
    await fetch(`${c.env.HANDOFF_WORKER_URL}/handoff`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${c.env.INTERNAL_API_TOKEN}`,
      },
      body: JSON.stringify({ lead_id: call.lead_id, call_id: call.id }),
    });
  }

  return c.json({ ok: true, classification: score.classification });
});

export default app;
