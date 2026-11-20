# Running ASVA locally (no Exotel)

Everything runs on this laptop: Supabase in Docker, the CRM on `localhost:3000`, and the voice agent through the laptop mic and speakers. A call made locally lands in the CRM like a phone call: transcript, live qualification, AI verdict, lead status.

## One click

Double-click **ASVA Demo** on the Desktop, or run `run-all` from the repo folder. It:

1. stops any previous CRM or voice-agent run,
2. starts Docker and the local database (API `127.0.0.1:44321`, Postgres `127.0.0.1:44322`),
3. starts the CRM in its own window (http://localhost:3000, login `admin@spc.test` / `demo-password-change-me`),
4. picks the newest lead with no call yet and opens its page in the browser,
5. starts the voice call in the same window.

During the call: press **ENTER** to talk, **ENTER** again to stop; Priya answers through the speakers. Ask to switch language at any time ("Hindi mein baat karo", "Tamil-la pesalama?"). Type **q** + ENTER to end. The window prints `CRM: call ... saved, scored hot (95)`; refresh the lead page to see the transcript, verdict and status.

Variants:

```
run-all <lead-id> hi-IN     call a specific lead (id = end of its CRM URL), starting in Hindi
run-all -SkipCall           only (re)start the database and CRM
apps\pipecat-agent\local-call <lead-id>   another call while the CRM is already running
```

First time only (or to wipe and reload demo data):

```powershell
cd packages/db; npx -y supabase@2.54.11 db reset --workdir .; cd ../..
$env:DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:44322/postgres"; node seed-remote-ultimate.js
```

## Providers (apps/pipecat-agent/.env)

| Stage | Provider, in fallback order | Setting |
|---|---|---|
| Speech-to-text | Sarvam **streaming** (transcribes while you speak; needs Sarvam credits), else ElevenLabs Scribe, then Groq Whisper | `LOCAL_STREAMING_STT=1`, `STT_PROVIDER=elevenlabs` |
| LLM | Groq `qwen/qwen3.8-27b` (thinking off, ~0.4 s to first sentence), then Groq `gpt-oss-120b`, then Gemini | `LLM_PRIMARY=groq`, `GROQ_MODEL`, `ALT_LLM_*` |
| Voice | Smallest `meher` (English/Hindi), Cartesia `nithya` (Tamil) | `TTS_PROVIDER=smallest`, `SMALLEST_TAMIL_PROVIDER=cartesia` |
| Phrase cache (R2) | off locally: slower than synthesis from a laptop | `LOCAL_R2_CACHE=1` to enable |

## Latency

The call window prints `[1735ms]` before each reply: time from pressing ENTER to Priya's first audio.

- Measured with the current keys: **1.7–2.1 s** while Groq has quota.
- Groq's free tier allows 8,000 tokens/minute per model and each turn uses ~3,000, so busy calls fall back to Gemini (~1.3 s slower). A Groq Developer-tier key removes this.
- With Sarvam credits, streaming speech-to-text removes ~0.7–1 s, bringing replies to about **1.0–1.3 s**.
