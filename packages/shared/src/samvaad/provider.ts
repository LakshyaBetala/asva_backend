import { SamvaadClient, type SamvaadClientOpts } from "./client";
import type { SamvaadEvent } from "./types";
import type { VoiceProvider, StartCallOpts } from "../voice-provider";

async function verifyHmac(body: string, signature: string, secret: string): Promise<boolean> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  const hex = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
  if (hex.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < hex.length; i++) {
    diff |= hex.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return diff === 0;
}

export class SamvaadProvider implements VoiceProvider {
  private client: SamvaadClient;
  constructor(opts: SamvaadClientOpts) {
    this.client = new SamvaadClient(opts);
  }

  async startCall(opts: StartCallOpts): Promise<{ providerCallId: string }> {
    const res = await this.client.post<{ call_id: string }>(
      `/agents/${opts.agentId}/calls`,
      {
        to: opts.to_e164,
        from: opts.callerId,
        lang_hint: opts.langHint,
        metadata: opts.metadata,
      }
    );
    return { providerCallId: res.call_id };
  }

  async parseWebhook(req: Request, { secret }: { secret: string }): Promise<SamvaadEvent> {
    const sig = req.headers.get("x-samvaad-signature") ?? "";
    const text = await req.text();
    if (!sig || !(await verifyHmac(text, sig, secret))) {
      throw new Error("invalid signature");
    }
    return JSON.parse(text) as SamvaadEvent;
  }

  async fetchRecording(callId: string): Promise<ReadableStream> {
    const url = `${this.client.opts.baseUrl}/calls/${callId}/recording`;
    const res = await fetch(url, {
      headers: { authorization: `Bearer ${this.client.opts.apiKey}` },
    });
    if (!res.ok || !res.body) throw new Error(`recording fetch failed: ${res.status}`);
    return res.body;
  }
}
