import { describe, it, expect, vi } from "vitest";
import { connectTwoNumbers } from "./exotel";

describe("connectTwoNumbers", () => {
  it("POSTs to Exotel Connect endpoint with form-encoded body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ Call: { Sid: "CA123" } }), { status: 200 }),
    );
    const out = await connectTwoNumbers({
      sid: "SID",
      apiKey: "K",
      apiToken: "T",
      from: "+919000000001",
      to: "+919876543210",
      callerId: "+914440000000",
      fetchImpl: fetchSpy,
    });
    expect(out.callSid).toBe("CA123");
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(String(url)).toMatch(/exotel\.com.*Accounts\/SID\/Calls\/connect/);
    expect((init as RequestInit).method).toBe("POST");
    const body = (init as RequestInit).body as string;
    expect(body).toContain("From=%2B919000000001");
    expect(body).toContain("To=%2B919876543210");
    expect(body).toContain("CallType=trans");
  });

  it("throws on non-ok response", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response("nope", { status: 403 }));
    await expect(
      connectTwoNumbers({
        sid: "SID",
        apiKey: "K",
        apiToken: "T",
        from: "+91900",
        to: "+91987",
        callerId: "+91444",
        fetchImpl: fetchSpy,
      }),
    ).rejects.toThrow(/exotel connect 403/);
  });
});
