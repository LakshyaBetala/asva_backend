import { describe, it, expect, vi } from "vitest";
import { SamvaadProvider } from "./provider";

const SECRET = "test-secret";

async function hmac(body: string, secret: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
}

describe("SamvaadProvider", () => {
  it("startCall: POSTs to /agents/:id/calls", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ call_id: "c_123" }), { status: 200 })
    );
    const p = new SamvaadProvider({ apiKey: "K", baseUrl: "https://x", fetchImpl: fetchSpy });
    const out = await p.startCall({
      agentId: "agt_1",
      to_e164: "+919876543210",
      callerId: "+914440000000",
      metadata: { lead_id: "L", tenant_id: "T" },
      langHint: "en-IN",
    });
    expect(out.providerCallId).toBe("c_123");
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe("https://x/agents/agt_1/calls");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.to).toBe("+919876543210");
    expect(body.metadata.lead_id).toBe("L");
    expect(body.lang_hint).toBe("en-IN");
  });

  it("parseWebhook: verifies HMAC and returns parsed event", async () => {
    const body = JSON.stringify({
      kind: "call.started", event_id: "e1", call_id: "c1", at: "2026-05-21T00:00:00Z",
    });
    const sig = await hmac(body, SECRET);
    const req = new Request("http://x/samvaad", {
      method: "POST",
      headers: { "content-type": "application/json", "x-samvaad-signature": sig },
      body,
    });
    const p = new SamvaadProvider({ apiKey: "K", baseUrl: "https://x" });
    const evt = await p.parseWebhook(req, { secret: SECRET });
    expect(evt.kind).toBe("call.started");
  });

  it("parseWebhook: rejects bad signature", async () => {
    const body = JSON.stringify({
      kind: "call.started", event_id: "e1", call_id: "c1", at: "2026-05-21T00:00:00Z",
    });
    const req = new Request("http://x/samvaad", {
      method: "POST",
      headers: { "content-type": "application/json", "x-samvaad-signature": "badsig" },
      body,
    });
    const p = new SamvaadProvider({ apiKey: "K", baseUrl: "https://x" });
    await expect(p.parseWebhook(req, { secret: SECRET })).rejects.toThrow(/signature/i);
  });
});
