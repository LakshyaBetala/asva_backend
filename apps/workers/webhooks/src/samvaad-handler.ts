import type { SupabaseClient } from "@supabase/supabase-js";
import type { SamvaadEvent } from "@ai-voice/shared";

export type HandlerTriggers = {
  onCallEnded?: (callId: string) => Promise<void>;
};

export async function handleSamvaadEvent(
  sb: SupabaseClient,
  evt: SamvaadEvent,
  triggers: HandlerTriggers = {},
): Promise<void> {
  const { data: call } = await sb
    .from("calls")
    .select("id,tenant_id,lead_id")
    .eq("samvaad_call_id", evt.call_id)
    .single();

  if (!call) {
    // Most likely the calls row hasn't been written yet by campaigns-worker.
    // Skip for non-started events; a reconciliation job will replay.
    return;
  }

  // Idempotent event log keyed by (call_id, event_id)
  await sb.from("call_events").insert({
    call_id: call.id,
    event_id: evt.event_id,
    kind: evt.kind,
    payload: evt,
  });

  switch (evt.kind) {
    case "call.started":
      await sb.from("calls").update({ status: "ringing" }).eq("id", call.id);
      break;
    case "call.answered":
      await sb
        .from("calls")
        .update({ status: "in_progress", started_at: evt.at })
        .eq("id", call.id);
      break;
    case "transcript.chunk":
      await sb.from("transcripts").insert({
        call_id: call.id,
        speaker: evt.speaker,
        text: evt.text,
        lang: evt.lang,
        ts_ms: evt.ts_ms,
        idx: evt.idx,
      });
      break;
    case "call.ended":
      await sb
        .from("calls")
        .update({
          status: evt.status,
          ended_at: evt.at,
          duration_sec: evt.duration_sec,
          language_used: evt.language_used,
        })
        .eq("id", call.id);

      if (evt.status === "voicemail") {
        // single retry: requeue the lead
        await sb.from("leads").update({ status: "queued" }).eq("id", call.lead_id);
      } else if (evt.status === "no_answer" || evt.status === "failed") {
        await sb.from("leads").update({ status: "cold" }).eq("id", call.lead_id);
      } else if (evt.status === "completed" && triggers.onCallEnded) {
        await triggers.onCallEnded(call.id);
      }
      break;
    case "turn.completed":
      await sb.from("turn_latencies").insert({
        call_id: call.id,
        tenant_id: call.tenant_id,
        turn_idx: evt.turn_idx,
        stt_final_ms: evt.stt_final_ms,
        llm_first_token_ms: evt.llm_first_token_ms,
        tts_first_chunk_ms: evt.tts_first_chunk_ms,
        total_turn_ms: evt.total_turn_ms,
        used_intro_cache: evt.used_intro_cache,
      });
      break;
    case "recording.ready":
      // Actual R2 upload handled by index.ts; here we only mark pending.
      await sb
        .from("calls")
        .update({ recording_r2_key: `pending:${evt.download_url}` })
        .eq("id", call.id);
      break;
  }
}
