export async function connectTwoNumbers(args: {
  sid: string;
  apiKey: string;
  apiToken: string;
  from: string;
  to: string;
  callerId: string;
  fetchImpl?: typeof fetch;
}): Promise<{ callSid: string }> {
  const auth = btoa(`${args.apiKey}:${args.apiToken}`);
  const url = `https://api.exotel.com/v1/Accounts/${args.sid}/Calls/connect.json`;
  const body = new URLSearchParams({
    From: args.from,
    To: args.to,
    CallerId: args.callerId,
    CallType: "trans",
    TimeLimit: "600",
    TimeOut: "30",
  });
  const f = args.fetchImpl ?? fetch;
  const res = await f(url, {
    method: "POST",
    headers: {
      authorization: `Basic ${auth}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
  if (!res.ok) throw new Error(`exotel connect ${res.status}: ${await res.text()}`);
  const j: any = await res.json();
  return { callSid: j.Call?.Sid ?? j.Call?.CallSid };
}
