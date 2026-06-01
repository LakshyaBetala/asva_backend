/**
 * Per-turn live scoring endpoint.
 *
 * Called by the Python voice agent every time the qualification slot
 * extractor produces a new state. We:
 *   1. Upsert qualification_slots for this call.
 *   2. Recompute Hot/Warm/Cold from the new slots.
 *   3. Update leads.status (Supabase realtime pushes this to the CRM live).
 *
 * Deliberately minimal — no LLM call here. The expensive extraction
 * runs in the agent; this endpoint only persists + classifies.
 */
import type { Context } from "hono";

const SPC_CATALOG_TERMS = [
  "solvent", "acetone", "toluene", "ethanol", "methanol", "ipa", "mek",
  "polymer", "polyethylene", "polypropylene", "pvc", "resin",
  "acid", "sulfuric", "hcl", "hydrochloric", "nitric", "phosphoric",
  "caustic", "naoh", "lye", "sodium hydroxide",
  "glycol", "plasticizer", "aromatic",
];

export type LiveScoreInput = {
  call_id: string;
  tenant_id: string;
  lead_id: string;
  turn_idx: number;
  slots: {
    product_interest: string | null;
    volume_monthly_kg: number | null;
    buying_frequency: "one_off" | "monthly" | "ad_hoc" | "unknown";
    current_supplier: string | null;
    pain_point: string | null;
    decision_role: "owner" | "procurement" | "engineer" | "assistant" | "unknown";
    timeline_days: number | null;
    buying_confidence: number;
    slot_confidence: Record<string, number>;
  };
};

export type Classification = "hot" | "warm" | "cold";

export function classifyFromSlots(slots: LiveScoreInput["slots"]): Classification {
  const inCatalog =
    !!slots.product_interest &&
    SPC_CATALOG_TERMS.some((t) => slots.product_interest!.toLowerCase().includes(t));

  const isDecisionMaker =
    slots.decision_role === "owner" || slots.decision_role === "procurement";

  if (
    slots.buying_confidence >= 0.7 &&
    slots.timeline_days !== null &&
    slots.timeline_days <= 30 &&
    isDecisionMaker &&
    inCatalog
  ) {
    return "hot";
  }

  if (
    slots.buying_confidence >= 0.5 &&
    inCatalog &&
    ((slots.timeline_days !== null && slots.timeline_days <= 60) ||
      slots.current_supplier !== null)
  ) {
    return "warm";
  }

  return "cold";
}

// Minimum env we need. Made structural so the score worker's wider Env
// type assigns into it without friction.
export type ScoreLiveEnv = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  INTERNAL_API_TOKEN: string;
};

type SbClient = {
  from(table: string): {
    upsert(row: any, opts?: any): Promise<{ error: any }>;
    update(patch: any): { eq(col: string, val: any): Promise<{ error: any }> };
  };
};

export async function persistLiveScore(
  sb: SbClient,
  input: LiveScoreInput,
): Promise<{ classification: Classification }> {
  const classification = classifyFromSlots(input.slots);

  await sb.from("qualification_slots").upsert(
    {
      call_id: input.call_id,
      tenant_id: input.tenant_id,
      lead_id: input.lead_id,
      product_interest: input.slots.product_interest,
      volume_monthly_kg: input.slots.volume_monthly_kg,
      buying_frequency: input.slots.buying_frequency,
      current_supplier: input.slots.current_supplier,
      pain_point: input.slots.pain_point,
      decision_role: input.slots.decision_role,
      timeline_days: input.slots.timeline_days,
      buying_confidence: input.slots.buying_confidence,
      slot_confidence: input.slots.slot_confidence,
      last_turn_idx: input.turn_idx,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "call_id" },
  );

  // Update the lead row so the CRM realtime stream picks up the change.
  await sb.from("leads").update({ status: classification }).eq("id", input.lead_id);

  return { classification };
}

export async function handleScoreLive<E extends ScoreLiveEnv = ScoreLiveEnv>(
  c: Context<{ Bindings: E }>,
  buildSbClient: (env: E) => SbClient,
): Promise<Response> {
  const token = c.req.header("authorization")?.replace("Bearer ", "");
  if (token !== c.env.INTERNAL_API_TOKEN) {
    return c.json({ error: "unauthorized" }, 401);
  }

  let body: LiveScoreInput;
  try {
    body = await c.req.json<LiveScoreInput>();
  } catch {
    return c.json({ error: "invalid_json" }, 400);
  }

  if (!body.call_id || !body.tenant_id || !body.lead_id || !body.slots) {
    return c.json({ error: "missing_fields" }, 400);
  }
  if (
    typeof body.slots.buying_confidence !== "number" ||
    body.slots.buying_confidence < 0 ||
    body.slots.buying_confidence > 1
  ) {
    return c.json({ error: "invalid_buying_confidence" }, 400);
  }

  const sb = buildSbClient(c.env);
  const { classification } = await persistLiveScore(sb, body);
  return c.json({ ok: true, classification });
}
