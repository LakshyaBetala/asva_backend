import { LeadScore, containsNonEnglishScript, type LeadScore as Score } from "@ai-voice/shared";
import { SCORING_PROMPT } from "./prompt";

export type TranscriptLine = { speaker: "agent" | "lead"; text: string; lang: string };

function buildPrompt(transcript: TranscriptLine[]): string {
  const body = transcript
    .map((l) => `${l.speaker.toUpperCase()} (${l.lang}): ${l.text}`)
    .join("\n");
  return `${SCORING_PROMPT}\n\n--- TRANSCRIPT ---\n${body}\n--- END ---`;
}

export async function scoreTranscript(
  transcript: TranscriptLine[],
  opts: { callLlm: (prompt: string) => Promise<string> },
): Promise<Score> {
  const prompt = buildPrompt(transcript);
  let lastError = "unknown";
  for (let attempt = 0; attempt < 2; attempt++) {
    let raw: string;
    try {
      raw = await opts.callLlm(prompt);
    } catch (e) {
      lastError = (e as Error).message;
      continue;
    }
    try {
      const json = JSON.parse(raw);
      const parsed = LeadScore.parse(json);
      if (containsNonEnglishScript(parsed)) {
        lastError = "non-English script in summary fields";
        continue;
      }
      return parsed;
    } catch (e) {
      lastError = (e as Error).message;
    }
  }
  throw new Error(`scoring failed: needs_review (${lastError})`);
}

export async function callSarvamLlm(
  env: { SARVAM_BASE_URL: string; SARVAM_API_KEY: string },
  prompt: string,
): Promise<string> {
  const res = await fetch(`${env.SARVAM_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.SARVAM_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: "sarvam-105b",
      temperature: 0,
      response_format: { type: "json_object" },
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!res.ok) throw new Error(`sarvam llm ${res.status}: ${await res.text()}`);
  const j = (await res.json()) as any;
  return j.choices[0].message.content as string;
}
