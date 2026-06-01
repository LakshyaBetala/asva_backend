export type Lang = "en-IN" | "hi-IN" | "ta-IN";

export type SamvaadEvent =
  | { kind: "call.started";     event_id: string; call_id: string; lead_id?: string; tenant_id?: string; at: string }
  | { kind: "call.answered";    event_id: string; call_id: string; at: string }
  | { kind: "transcript.chunk"; event_id: string; call_id: string; speaker: "agent" | "lead";
                                text: string; lang: Lang; ts_ms: number; idx: number }
  | { kind: "call.ended";       event_id: string; call_id: string;
                                status: "completed" | "failed" | "voicemail" | "no_answer";
                                duration_sec: number; language_used: Lang; at: string }
  | { kind: "recording.ready";  event_id: string; call_id: string; download_url: string; format: "mp3" | "wav" }
  | { kind: "turn.completed";   event_id: string; call_id: string; turn_idx: number;
                                stt_final_ms: number | null; llm_first_token_ms: number | null;
                                tts_first_chunk_ms: number | null; total_turn_ms: number;
                                used_intro_cache: boolean };
