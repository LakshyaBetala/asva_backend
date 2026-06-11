"""Live smoke test for SarvamStreamingSTT against the real Sarvam API.

Synthesizes hi/ta/en test lines with our own TTS (bulbul), downsamples to the
exact 8 kHz pcm_s16le frames Exotel gives us, streams them over ONE Sarvam
streaming session in ~100 ms chunks, and reports:

  - the final transcript + detected language per utterance (auto-detect must
    track the hi -> ta -> en switch on a single connection)
  - VAD START/END_SPEECH events
  - latency from "last voiced chunk sent" to "final transcript received"

Run from apps/pipecat-agent:  python smoke_streaming_stt.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from voice_agent.audio_codec import tts_wav_to_exotel_pcm  # noqa: E402
from voice_agent.sarvam_streaming_stt import SarvamStreamingSTT  # noqa: E402
from voice_agent.sarvam_tts import synthesize  # noqa: E402

CHUNK = 1600  # 100 ms at 8 kHz s16le mono — same as Exotel media frames
RATE = 8000

LINES = [
    ("hi-IN", "Anna Nagar mein teen BHK chahiye, budget pachaas lakh tak hai."),
    ("ta-IN", "வேளச்சேரியில வீடு வேணும், வாடகைக்கு."),
    ("en-IN", "I am looking for a two BHK apartment in Adyar."),
]


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(__file__).parent / ".env"
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m:
            env[m.group(1)] = m.group(2).strip('"').strip("'")
    return env


async def main() -> None:
    env = _load_env()
    key = env.get("SARVAM_API_KEY") or os.environ.get("SARVAM_API_KEY", "")
    if not key:
        raise SystemExit("SARVAM_API_KEY not found in .env")

    print("synthesizing test clips via bulbul ...")
    clips: list[tuple[str, bytes]] = []
    for lang, text in LINES:
        result = await synthesize(text=text, lang=lang, api_key=key)
        pcm = tts_wav_to_exotel_pcm(result.audio, RATE)
        clips.append((lang, pcm))
        print(f"  {lang}: {len(pcm)/2/RATE:.1f}s audio")

    stt = SarvamStreamingSTT(api_key=key, sample_rate=RATE)
    t0 = time.monotonic()
    await stt.start()
    print(f"connected in {time.monotonic()-t0:.2f}s")

    silence = b"\x00" * CHUNK
    for expected_lang, pcm in clips:
        sent_last_voiced = 0.0
        for i in range(0, len(pcm), CHUNK):
            await stt.feed(pcm[i : i + CHUNK])
            sent_last_voiced = time.monotonic()
            await asyncio.sleep(0.1)  # real-time pacing — honest VAD latency
        # trail silence so server VAD endpoints the utterance
        got: object | None = None
        for _ in range(60):  # up to ~6 s of trailing silence
            await stt.feed(silence)
            await asyncio.sleep(0.1)
            got = stt.pop_final()
            if got is not None:
                break
        if got is None:
            print(f"  EXPECTED {expected_lang}: NO TRANSCRIPT (timeout)  "
                  f"failed={stt.failed}")
            continue
        merged = stt.drain_finals(got)
        dt = time.monotonic() - sent_last_voiced
        print(f"  EXPECTED {expected_lang} -> got lang={merged.language_code} "
              f"conf={merged.confidence:.2f} (+{dt:.2f}s after last voiced)")
        print(f"    transcript: {merged.transcript!r}")

    await stt.close()
    print("done. failed flag:", stt.failed)


if __name__ == "__main__":
    asyncio.run(main())
