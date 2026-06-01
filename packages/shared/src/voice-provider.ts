import type { SamvaadEvent, Lang } from "./samvaad/types";

export type StartCallOpts = {
  agentId: string;
  to_e164: string;
  callerId: string;
  metadata: { lead_id: string; tenant_id: string; campaign_id?: string };
  langHint?: Lang;
};

export interface VoiceProvider {
  startCall(opts: StartCallOpts): Promise<{ providerCallId: string }>;
  parseWebhook(req: Request, opts: { secret: string }): Promise<SamvaadEvent>;
  fetchRecording(providerCallId: string): Promise<ReadableStream>;
}
