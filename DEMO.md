# SPC live-demo runbook

End-to-end: from cold laptop to your phone ringing with Priya on the line.

## Pre-flight checklist

| | What | Status |
|---|---|---|
| 1 | Exotel account verified + ExoPhone allocated (04446973311) | ✅ |
| 2 | Personal mobile (+918072116397) on Whitelist Numbers | ✅ |
| 3 | API credentials saved in `apps/pipecat-agent/.env` | ✅ |
| 4 | Sarvam + Gemini + R2 keys in `.env` | ✅ |
| 5 | Supabase schema applied (SETUP.sql Block 1+2) | ✅ |
| 6 | Block 3 run (link auth user to tenant) | ❓ confirm |
| 7 | JWT custom claims hook enabled in Supabase dashboard | ❓ confirm |
| 8 | **Exotel Voice Streaming enabled** by support (email sent) | ❓ confirm |

If 6/7/8 are not done, do them before the demo or the audio stream won't connect.

---

## Track A: validate Priya **without** a phone (mic + speaker only)

Run this **first**. It proves Sarvam STT + Gemini + Sarvam TTS + R2 cache
work end-to-end, before any telephony.

```powershell
cd C:\Users\laksh\ai_voice\apps\pipecat-agent
pip install -e ".[dev,local-audio]"
python -m voice_agent.local_audio --lang hi-IN --lead-name Suresh
```

Press ENTER → speak → ENTER again → Priya responds through speakers.

**Validate:**
- Hindi turn → Priya answers in Hindi.
- Say "speak in english please" → she switches with a bridge phrase.
- Mention "we buy 500kg toluene monthly" → watch `buying_conf` climb.
- After ~30s, phase moves GREETING → CONNECT → DISCOVER.
- Hard cap kicks in at 360s.

If this works, the voice loop is sound. Phone call adds one layer: telephony.

---

## Track B: live phone call via Exotel

### Step 1 — start the FastAPI server

```powershell
cd C:\Users\laksh\ai_voice\apps\pipecat-agent
uvicorn voice_agent.server:app --host 0.0.0.0 --port 8080 --reload
```

Leave it running. You should see `Uvicorn running on http://0.0.0.0:8080`.

### Step 2 — expose port 8080 publicly with ngrok

In a second terminal:

```powershell
ngrok http 8080
```

ngrok prints a forwarding URL like `https://abcd-1234.ngrok-free.app`.
Copy that.

### Step 3 — set the stream URL in `.env`

Edit `apps/pipecat-agent/.env`:

```
EXOTEL_STREAM_URL=wss://abcd-1234.ngrok-free.app
```

Restart uvicorn so it picks up the new env var.

### Step 4 — place the call

In a third terminal:

```powershell
cd C:\Users\laksh\ai_voice\apps\pipecat-agent
python -m voice_agent.demo_call
```

This POSTs to `http://127.0.0.1:8080/exotel/calls` with your whitelisted
mobile from `.env`. Exotel dials it, your phone rings.

**Pick up. Priya is live.**

---

## Troubleshooting

### "exotel: 401" or "auth invalid"
- API key/token mismatched. Re-copy from Exotel dashboard → API Credentials.
- Note the region (`sg` for Singapore) is in `.env` as `EXOTEL_REGION`.

### Call connects but no audio / immediate hangup
- **Most common: Voice Streaming not enabled on your account.** Email
  support@exotel.in (CC sales@exotel.in) with subject "Enable Voice
  Streaming on trial account almmatix1" — they unlock in 2-4 business hours.
- Verify your ngrok URL is `wss://...` not `https://...` in `.env`.

### "exotel: 422 Whitelist"
- The destination number isn't on Whitelist Numbers. Add it in dashboard:
  Manage → Whitelist Numbers → enter + give missed call to verify.

### Priya silent for >2s after I speak
- Sarvam STT cold-start. First call always slow; subsequent turns <1s.
- Check uvicorn logs for `orchestrator failure` — usually Sarvam quota.

### Call hard-cuts at 360s
- That's the cap. Working as designed. Bill is 2 units.

### Want to demo to SPC live, not just to your own phone
- After KYC clears (24-48hr after document submission), you can whitelist
  any number. Add SPC's contact, re-run the demo CLI with `--to +91...`.

---

## What a "successful demo" looks like

```
$ python -m voice_agent.demo_call --lang hi-IN

→ Placing Exotel call to +918072116397  (lang=hi-IN)
  backend: http://127.0.0.1:8080
  stream URL Exotel will hit: wss://abcd-1234.ngrok-free.app

← 200 OK
  call_sid:   exo-3f4b8c92ab
  status:     queued
  stream_url: wss://abcd-1234.ngrok-free.app/exotel/stream/demo-3a7c

Your phone should ring within ~3 seconds. Pick up and talk to Priya.
```

**Your phone rings. You answer.**

> **PRIYA (Hindi):** "Namaste Suresh-ji, main Priya bol rahi hoon Supreme
> Petrochemicals se. Kya 30 second baat kar sakte hain aapke chemicals
> sourcing ke baare mein?"
>
> **YOU:** "Haan ji, batayie."
>
> **PRIYA:** "Achha, aap mainly kaunse chemicals procure karte hain
> aajkal? Solvents, polymers, ya kuch specific?"
>
> **YOU:** "Hum monthly 500kg toluene lete hain."
>
> **PRIYA:** *(phase advances to QUALIFY)* "Theek hai, 500kg toluene
> monthly. Currently kis supplier se le rahe hain?"
>
> ...

After 60-90s, uvicorn console shows the qualification slots being
extracted live:

```
INFO: call_id=demo-3a7c turn=4 phase=qualify
      slots: product_interest='toluene' volume=500 frequency=monthly
             buying_confidence=0.65 score=warm
```

That's Priya doing what she'll do for SPC, 2000 times per month.

---

## After the demo: clean up

```powershell
# Stop uvicorn (Ctrl+C)
# Stop ngrok (Ctrl+C)
```

Call recording auto-saved to your Exotel account → CALLS → Inbox.

Per-call latency telemetry goes to `turn_latencies` table once we wire
the DB writer in CP5.
