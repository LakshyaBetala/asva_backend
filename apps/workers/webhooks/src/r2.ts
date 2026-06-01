export async function fetchAndStoreRecording(
  env: { RECORDINGS: R2Bucket; SARVAM_API_KEY: string; SARVAM_BASE_URL: string },
  call: { id: string; tenant_id: string; samvaad_call_id: string },
): Promise<string> {
  const url = `${env.SARVAM_BASE_URL}/samvaad/calls/${call.samvaad_call_id}/recording`;
  const res = await fetch(url, {
    headers: { authorization: `Bearer ${env.SARVAM_API_KEY}` },
  });
  if (!res.ok || !res.body) throw new Error(`recording fetch ${res.status}`);
  const key = `tenants/${call.tenant_id}/calls/${call.id}.mp3`;
  await env.RECORDINGS.put(key, res.body, {
    httpMetadata: { contentType: "audio/mpeg" },
  });
  return key;
}
