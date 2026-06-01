import { describe, it, expect, vi } from "vitest";
import { Hono } from "hono";

import { classifyFromSlots, handleScoreLive, persistLiveScore, type LiveScoreInput } from "./score-live";

function baseSlots(overrides: Partial<LiveScoreInput["slots"]> = {}): LiveScoreInput["slots"] {
  return {
    product_interest: null,
    volume_monthly_kg: null,
    buying_frequency: "unknown",
    current_supplier: null,
    pain_point: null,
    decision_role: "unknown",
    timeline_days: null,
    buying_confidence: 0,
    slot_confidence: {},
    ...overrides,
  };
}

describe("classifyFromSlots", () => {
  it("returns hot when all hot signals present", () => {
    const c = classifyFromSlots(
      baseSlots({
        product_interest: "acetone solvent",
        decision_role: "procurement",
        timeline_days: 14,
        buying_confidence: 0.85,
      }),
    );
    expect(c).toBe("hot");
  });

  it("returns warm when buying_confidence ≥0.5 + named supplier", () => {
    const c = classifyFromSlots(
      baseSlots({
        product_interest: "polymer",
        decision_role: "procurement",
        current_supplier: "ABC Chem",
        buying_confidence: 0.55,
      }),
    );
    expect(c).toBe("warm");
  });

  it("returns cold when off-catalog even with high confidence", () => {
    const c = classifyFromSlots(
      baseSlots({
        product_interest: "fertilizer",
        decision_role: "owner",
        timeline_days: 7,
        buying_confidence: 0.95,
      }),
    );
    expect(c).toBe("cold");
  });

  it("returns cold for low buying_confidence", () => {
    const c = classifyFromSlots(
      baseSlots({
        product_interest: "acetone",
        decision_role: "owner",
        timeline_days: 14,
        buying_confidence: 0.3,
      }),
    );
    expect(c).toBe("cold");
  });
});

function makeStubSb() {
  const upsertCalls: any[] = [];
  const updateCalls: any[] = [];
  const sb = {
    from(table: string) {
      return {
        async upsert(row: any) {
          upsertCalls.push({ table, row });
          return { error: null };
        },
        update(patch: any) {
          return {
            async eq(col: string, val: any) {
              updateCalls.push({ table, patch, col, val });
              return { error: null };
            },
          };
        },
      };
    },
  };
  return { sb, upsertCalls, updateCalls };
}

describe("persistLiveScore", () => {
  it("upserts qualification_slots and updates lead status", async () => {
    const { sb, upsertCalls, updateCalls } = makeStubSb();
    const input: LiveScoreInput = {
      call_id: "c1",
      tenant_id: "t1",
      lead_id: "L1",
      turn_idx: 5,
      slots: baseSlots({
        product_interest: "acetone",
        decision_role: "procurement",
        timeline_days: 14,
        buying_confidence: 0.85,
      }),
    };

    const out = await persistLiveScore(sb, input);
    expect(out.classification).toBe("hot");
    expect(upsertCalls).toHaveLength(1);
    expect(upsertCalls[0].table).toBe("qualification_slots");
    expect(upsertCalls[0].row.call_id).toBe("c1");
    expect(upsertCalls[0].row.last_turn_idx).toBe(5);
    expect(updateCalls).toHaveLength(1);
    expect(updateCalls[0].table).toBe("leads");
    expect(updateCalls[0].patch.status).toBe("hot");
    expect(updateCalls[0].col).toBe("id");
    expect(updateCalls[0].val).toBe("L1");
  });
});

describe("handleScoreLive HTTP handler", () => {
  function makeApp(env: any) {
    const app = new Hono<{ Bindings: any }>();
    app.post("/score-live", (c) => handleScoreLive(c, () => makeStubSb().sb));
    return { app, env };
  }

  it("rejects without bearer token", async () => {
    const { app, env } = makeApp({ INTERNAL_API_TOKEN: "secret" });
    const res = await app.request(
      "/score-live",
      { method: "POST", body: "{}" },
      env,
    );
    expect(res.status).toBe(401);
  });

  it("rejects invalid JSON", async () => {
    const { app, env } = makeApp({ INTERNAL_API_TOKEN: "secret" });
    const res = await app.request(
      "/score-live",
      {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: "not json",
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("rejects missing fields", async () => {
    const { app, env } = makeApp({ INTERNAL_API_TOKEN: "secret" });
    const res = await app.request(
      "/score-live",
      {
        method: "POST",
        headers: { authorization: "Bearer secret", "content-type": "application/json" },
        body: JSON.stringify({ call_id: "c1" }),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("rejects out-of-range buying_confidence", async () => {
    const { app, env } = makeApp({ INTERNAL_API_TOKEN: "secret" });
    const res = await app.request(
      "/score-live",
      {
        method: "POST",
        headers: { authorization: "Bearer secret", "content-type": "application/json" },
        body: JSON.stringify({
          call_id: "c1",
          tenant_id: "t1",
          lead_id: "L1",
          turn_idx: 1,
          slots: baseSlots({ buying_confidence: 1.5 }),
        }),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("succeeds with valid payload and returns classification", async () => {
    const { app, env } = makeApp({ INTERNAL_API_TOKEN: "secret" });
    const res = await app.request(
      "/score-live",
      {
        method: "POST",
        headers: { authorization: "Bearer secret", "content-type": "application/json" },
        body: JSON.stringify({
          call_id: "c1",
          tenant_id: "t1",
          lead_id: "L1",
          turn_idx: 3,
          slots: baseSlots({
            product_interest: "acetone",
            decision_role: "procurement",
            timeline_days: 14,
            buying_confidence: 0.85,
          }),
        }),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; classification: string };
    expect(body.ok).toBe(true);
    expect(body.classification).toBe("hot");
  });
});
