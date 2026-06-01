// Pre-cached intro audio orchestration. Pure logic; TTS + R2 are injected.

export type IntroLang = "en-IN" | "hi-IN" | "ta-IN";

export type IntroTts = (args: {
  text: string;
  lang: IntroLang;
  voiceId?: string;
}) => Promise<ArrayBuffer>;

export type IntroR2Put = (args: {
  key: string;
  body: ArrayBuffer;
  contentType: string;
}) => Promise<void>;

const PLACEHOLDER_RE = /^(unknown|n\/?a|test|na)$/i;

export function isUsableFirstName(name: string | null | undefined): boolean {
  if (!name) return false;
  const trimmed = name.trim();
  return trimmed.length >= 2 && !PLACEHOLDER_RE.test(trimmed);
}

// Mirrors infra/samvaad/spc-priya.agent.json first_turn_templates exactly.
// Keep in sync. We render {{lead.first_name}} with a leading-space-eaten
// fallback so "Hello , this is..." never appears.
export function buildIntroText(
  lang: IntroLang,
  firstName: string | null | undefined,
): string {
  const name = isUsableFirstName(firstName) ? firstName!.trim() : "";
  if (lang === "en-IN") {
    return name
      ? `Hello ${name}, this is Priya from Supreme Petrochemicals, Chennai. Is this a good time for a quick 30-second conversation?`
      : `Namaste, this is Priya from Supreme Petrochemicals, Chennai. Is this a good time?`;
  }
  if (lang === "hi-IN") {
    return name
      ? `Namaste ${name} ji, main Priya hoon Supreme Petrochemicals Chennai se. Kya aap 30 second baat kar sakte hain?`
      : `Namaste, main Priya hoon Supreme Petrochemicals Chennai se. Kya aap 30 second baat kar sakte hain?`;
  }
  return name
    ? `Vanakkam ${name} avargale, naan Priya, Supreme Petrochemicals Chennai-il irundhu. Ungalukku oru nimisham nerum unda?`
    : `Vanakkam, naan Priya, Supreme Petrochemicals Chennai-il irundhu. Ungalukku oru nimisham nerum unda?`;
}

// Stable hash used to invalidate cache when first_name or template changes.
// Not cryptographic — just a quick check that "same text → same audio".
function djb2(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(16);
}

export function introR2Key(args: {
  tenantId: string;
  leadId: string;
  lang: IntroLang;
}): string {
  return `intro/${args.tenantId}/${args.leadId}/${args.lang}.mp3`;
}

export type IntroSynthResult = {
  lang: IntroLang;
  r2Key: string;
  textHash: string;
};

export async function synthesizeAndCacheIntros(args: {
  tenantId: string;
  leadId: string;
  firstName: string | null | undefined;
  langs?: IntroLang[];
  voiceId?: string;
  tts: IntroTts;
  r2Put: IntroR2Put;
  upsertRow: (row: {
    tenantId: string;
    leadId: string;
    lang: IntroLang;
    r2Key: string;
    voiceId?: string;
    textHash: string;
  }) => Promise<void>;
}): Promise<IntroSynthResult[]> {
  const langs = args.langs ?? (["en-IN", "hi-IN", "ta-IN"] as IntroLang[]);
  const out: IntroSynthResult[] = [];
  for (const lang of langs) {
    const text = buildIntroText(lang, args.firstName);
    const textHash = djb2(`${args.voiceId ?? ""}|${text}`);
    const r2Key = introR2Key({
      tenantId: args.tenantId,
      leadId: args.leadId,
      lang,
    });
    const audio = await args.tts({ text, lang, voiceId: args.voiceId });
    await args.r2Put({ key: r2Key, body: audio, contentType: "audio/mpeg" });
    await args.upsertRow({
      tenantId: args.tenantId,
      leadId: args.leadId,
      lang,
      r2Key,
      voiceId: args.voiceId,
      textHash,
    });
    out.push({ lang, r2Key, textHash });
  }
  return out;
}
