import { describe, it, expect, vi } from "vitest";
import { handleSamvaadEvent } from "./samvaad-handler";

function fakeSupabase(callRow: any = { id: "call-uuid", tenant_id: "t1", lead_id: "l1" }) {
  const calls: any[] = [];
  const fn = (table: string) => ({
    upsert: vi.fn(async (rows: any) => {
      calls.push({ table, op: "upsert", rows });
      return { data: rows, error: null };
    }),
    insert: vi.fn(async (rows: any) => {
      calls.push({ table, op: "insert", rows });
      return { data: rows, error: null };
    }),
    update: vi.fn((patch: any) => ({
      eq: vi.fn(async () => {
        calls.push({ table, op: "update", patch });
        return { error: null };
      }),
    })),
    select: vi.fn(() => ({
      eq: vi.fn(() => ({
        single: async () => ({ data: callRow }),
      })),
    })),
  });
  return { client: { from: fn } as any, calls };
}

describe("handleSamvaadEvent", () => {
  it("inserts call_events idempotently", async () => {
    const { client, calls } = fakeSupabase();
    const evt = {
      kind: "call.started",
      event_id: "e1",
      call_id: "prov_1",
      at: "2026-05-21T00:00:00Z",
    } as const;
    await handleSamvaadEvent(client, evt);
    expect(calls.some((c) => c.table === "call_events" && c.op === "insert")).toBe(true);
    expect(calls.some((c) => c.table === "calls" && c.op === "update")).toBe(true);
  });

  it("appends transcript chunks", async () => {
    const { client, calls } = fakeSupabase();
    const evt = {
      kind: "transcript.chunk",
      event_id: "e2",
      call_id: "prov_1",
      speaker: "agent",
      text: "hello",
      lang: "en-IN",
      ts_ms: 1000,
      idx: 1,
    } as const;
    await handleSamvaadEvent(client, evt);
    expect(calls.some((c) => c.table === "transcripts" && c.op === "insert")).toBe(true);
  });

  it("on completed call.ended updates calls and fires onCallEnded", async () => {
    const { client } = fakeSupabase();
    const trigger = vi.fn();
    await handleSamvaadEvent(
      client,
      {
        kind: "call.ended",
        event_id: "e3",
        call_id: "prov_1",
        status: "completed",
        duration_sec: 95,
        language_used: "en-IN",
        at: "2026-05-21T00:01:00Z",
      } as const,
      { onCallEnded: trigger },
    );
    expect(trigger).toHaveBeenCalledWith("call-uuid");
  });

  it("on voicemail requeues the lead and does NOT score", async () => {
    const { client, calls } = fakeSupabase();
    const trigger = vi.fn();
    await handleSamvaadEvent(
      client,
      {
        kind: "call.ended",
        event_id: "v1",
        call_id: "prov_1",
        status: "voicemail",
        duration_sec: 8,
        language_used: "en-IN",
        at: "2026-05-21T00:00:00Z",
      } as const,
      { onCallEnded: trigger },
    );
    expect(trigger).not.toHaveBeenCalled();
    expect(
      calls.some(
        (c) => c.table === "leads" && c.op === "update" && c.patch?.status === "queued",
      ),
    ).toBe(true);
  });

  it("records turn_latencies on turn.completed", async () => {
    const { client, calls } = fakeSupabase();
    await handleSamvaadEvent(client, {
      kind: "turn.completed",
      event_id: "t1",
      call_id: "prov_1",
      turn_idx: 3,
      stt_final_ms: 210,
      llm_first_token_ms: 240,
      tts_first_chunk_ms: 180,
      total_turn_ms: 820,
      used_intro_cache: false,
    } as const);
    expect(
      calls.some(
        (c) => c.table === "turn_latencies" && c.op === "insert" && c.rows?.total_turn_ms === 820,
      ),
    ).toBe(true);
  });

  it("on no_answer marks lead cold", async () => {
    const { client, calls } = fakeSupabase();
    await handleSamvaadEvent(client, {
      kind: "call.ended",
      event_id: "n1",
      call_id: "prov_1",
      status: "no_answer",
      duration_sec: 0,
      language_used: "en-IN",
      at: "2026-05-21T00:00:00Z",
    } as const);
    expect(
      calls.some(
        (c) => c.table === "leads" && c.op === "update" && c.patch?.status === "cold",
      ),
    ).toBe(true);
  });
});
