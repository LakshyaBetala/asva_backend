# Running ASVA locally (no Exotel)

Everything runs on this laptop: Supabase in Docker, the CRM on `localhost:3000`, and the voice agent through the laptop mic and speakers. A call made locally lands in the CRM like a phone call: transcript, live qualification, AI verdict, lead status.

## 1. Start the stack

```powershell
.\start-local.ps1
```

Starts Docker Desktop if needed, then local Supabase (API `127.0.0.1:54321`, Postgres `127.0.0.1:54322`) and the CRM. Log in at http://localhost:3000 with `admin@spc.test` / `demo-password-change-me`.

First time only (or to wipe and reload demo data):

```powershell
cd packages/db; npx -y supabase@2.54.11 db reset --workdir .; cd ../..
$env:DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"; node seed-remote-ultimate.js
```

## 2. Make a call

1. In the CRM, open a lead. Its id is the last part of the URL: `/leads/<lead-id>`.
2. Run:

```powershell
cd apps/pipecat-agent
python -m voice_agent.local_audio --lead-id <lead-id> --lang en-IN --record-seconds 0
```

Priya greets the lead by name. Press **ENTER** to start talking and **ENTER** again to stop; she replies through the speakers. Type **q** + ENTER to end the call.

To switch language, just ask: "Hindi mein baat karo", "Can we talk in English?", "Tamil-la pesalama?". She switches and keeps the rest of the call in that language.

3. When the call ends the terminal prints `CRM: call ... saved, scored hot (95)`. Refresh the lead page: transcript, verdict (buy/rent, budget, locality, BHK, site visit), live qualification and status are filled in.

Without `--lead-id` the harness still works, but nothing is saved.

## Providers (apps/pipecat-agent/.env)

| Stage | Provider | Setting |
|---|---|---|
| Speech-to-text | ElevenLabs Scribe, then Groq Whisper, then Sarvam on failure | `STT_PROVIDER=elevenlabs` |
| LLM | Gemini 2.5 Flash (key pool), Groq gpt-oss fallback | `LLM_PRIMARY=gemini` |
| Voice | Smallest `meher` (English/Hindi), Cartesia `nithya` (Tamil) | `TTS_PROVIDER=smallest`, `SMALLEST_TAMIL_PROVIDER=cartesia` |
| Phrase cache (R2) | off locally: slower than synthesis from a laptop | `LOCAL_R2_CACHE=1` to enable |

Latency depends heavily on the internet connection: each reply makes three sequential API calls. On a good connection expect about 2–4 s per reply; on a congested network it can exceed 8 s.
