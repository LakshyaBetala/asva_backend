import { describe, it, expect, vi } from "vitest";
import { handleHandoff } from "./handoff";

function makeSb(opts: { assignedTo?: string | null } = {}) {
  const writes: any[] = [];
  const assignedTo = "assignedTo" in opts ? opts.assignedTo : "u1";
  const lead = {
    id: "L",
    tenant_id: "T",
    name: "Ravi",
    phone_e164: "+919876543210",
    company: "Acme",
    assigned_to: assignedTo,
  };
  const user = { id: "u1", email: "rep@spc.test", whatsapp: "+919000000000" };
  const tenant = { whatsapp_handoff_number: "+919000000000" };
  const score = {
    score_0_100: 85,
    summary: "Confirmed bulk glycerine + acetic acid procurement.",
    next_action: "Send quote within 4 hours.",
    extracted: { chemicals: ["glycerine", "acetic acid"], timeline: "now" },
  };
  return {
    writes,
    client: {
      from: (t: string) => {
        if (t === "leads")
          return { select: () => ({ eq: () => ({ single: async () => ({ data: lead }) }) }) };
        if (t === "users")
          return { select: () => ({ eq: () => ({ single: async () => ({ data: user }) }) }) };
        if (t === "tenants")
          return { select: () => ({ eq: () => ({ single: async () => ({ data: tenant }) }) }) };
        if (t === "lead_scores")
          return {
            select: () => ({
              eq: () => ({
                order: () => ({
                  limit: () => ({ maybeSingle: async () => ({ data: score }) }),
                }),
              }),
            }),
          };
        if (t === "handoffs")
          return {
            insert: async (row: any) => {
              writes.push({ t, row });
              return { error: null };
            },
          };
        return {};
      },
    } as any,
  };
}

describe("handleHandoff", () => {
  it("inserts WhatsApp + email handoff rows for a hot lead", async () => {
    const { client, writes } = makeSb();
    const send = vi.fn();
    const out = await handleHandoff(client, {
      leadId: "L",
      callId: "C",
      appBaseUrl: "https://app",
      resendKey: "rk",
      resendFrom: "no-reply@aivoice.dev",
      emailSender: send,
    });
    expect(out.wa).toMatch(/wa\.me\/919000000000/);
    expect(out.email).toBe("rep@spc.test");
    const channels = writes.map((w) => w.row.channel);
    expect(channels).toContain("whatsapp");
    expect(channels).toContain("email");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("only inserts WhatsApp when rep has no email", async () => {
    const { client, writes } = makeSb({ assignedTo: null });
    const send = vi.fn();
    const out = await handleHandoff(client, {
      leadId: "L",
      callId: "C",
      appBaseUrl: "https://app",
      resendKey: "rk",
      resendFrom: "no-reply@aivoice.dev",
      emailSender: send,
    });
    expect(out.email).toBe(null);
    const channels = writes.map((w) => w.row.channel);
    expect(channels).toContain("whatsapp");
    expect(channels).not.toContain("email");
    expect(send).not.toHaveBeenCalled();
  });
});
