export function buildWaLink(repWhatsapp: string, message: string): string {
  const e164 = repWhatsapp.replace(/[^\d]/g, "");
  return `https://wa.me/${e164}?text=${encodeURIComponent(message)}`;
}

export function buildHotLeadMessage(args: {
  leadName: string;
  company: string | null;
  phone: string;
  score: number;
  summary: string;
  chemicals: string[];
  timeline: string;
  nextAction: string;
  leadUrl: string;
}): string {
  return [
    `HOT LEAD - score ${args.score}/100`,
    `${args.leadName} - ${args.company ?? "-"} - ${args.phone}`,
    `Chemicals: ${args.chemicals.join(", ") || "-"} | Timeline: ${args.timeline}`,
    ``,
    args.summary,
    ``,
    `Next action: ${args.nextAction}`,
    `Open lead: ${args.leadUrl}`,
  ].join("\n");
}

export async function sendResendEmail(
  apiKey: string,
  args: { to: string; from: string; subject: string; text: string },
): Promise<void> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!res.ok) throw new Error(`resend ${res.status}: ${await res.text()}`);
}
