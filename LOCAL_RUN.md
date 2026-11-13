# Running ASVA locally (no Exotel)

Everything runs on this laptop: Supabase in Docker, the CRM on `localhost:3000`, and the voice agent through the laptop mic and speakers. A call made locally lands in the CRM like a phone call: transcript, live qualification, AI verdict, lead status.

## One click

Double-click **ASVA Demo** on the Desktop, or run `run-all` from the repo folder. It:

1. stops any previous CRM or voice-agent run,
2. starts Docker and the local database (API `127.0.0.1:54321`, Postgres `127.0.0.1:54322`),
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
$env:DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"; node seed-remote-ultimate.js
```

## Providers (apps/pipecat-agent/.env)

| Stage | Provider | Setting |
|---|---|---|
| Speech-to-text | ElevenLabs Scribe, then Groq Whisper, then Sarvam on failure | `STT_PROVIDER=elevenlabs` |
| LLM | Gemini 2.5 Flash (key pool), Groq gpt-oss fallback | `LLM_PRIMARY=gemini` |
| Voice | Smallest `meher` (English/Hindi), Cartesia `nithya` (Tamil) | `TTS_PROVIDER=smallest`, `SMALLEST_TAMIL_PROVIDER=cartesia` |
| Phrase cache (R2) | off locally: slower than synthesis from a laptop | `LOCAL_R2_CACHE=1` to enable |

Latency depends heavily on the internet connection: each reply makes three sequential API calls. On a good connection expect about 2–4 s per reply; on a congested network it can exceed 8 s.
