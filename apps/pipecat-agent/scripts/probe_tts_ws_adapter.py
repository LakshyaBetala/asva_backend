"""Live test of SarvamStreamingTTS: two sentences, language switch on one
connection, chunk timing. Costs ~Rs 0.1."""
import asyncio
import os
import sys
import time

from dotenv import dotenv_values

env = {**dotenv_values(".env"), **os.environ}
sys.path.insert(0, "src")

from voice_agent.sarvam_tts_ws import SarvamStreamingTTS  # noqa: E402


async def run(tts: SarvamStreamingTTS, text: str, lang: str) -> None:
    t0 = time.perf_counter()
    first = None
    total = 0
    n = 0
    async for chunk in tts.synth_stream(text, lang):
        if first is None:
            first = time.perf_counter() - t0
        total += len(chunk)
        n += 1
    dur = total / 2 / tts.sample_rate
    print(
        f"[{lang}] first={first*1000:.0f}ms chunks={n} "
        f"audio={dur:.1f}s wall={time.perf_counter()-t0:.2f}s :: {text[:40]}"
    )


async def main() -> None:
    tts = SarvamStreamingTTS(
        api_key=env["SARVAM_API_KEY"], speaker="priya", sample_rate=8000
    )
    await run(tts, "Endha area la property paakareenga sir?", "ta-IN")
    await run(tts, "Got it sir, Saturday or Sunday for the site visit?", "en-IN")
    await run(tts, "Bilkul sir, matching options WhatsApp pe bhej doongi.", "hi-IN")
    # Full-WAV interface used by the intro path.
    wav = await tts.synth("Hi Mouriyan, this is Priya from XYZ Broker.", "en-IN")
    print(f"synth() wav bytes={len(wav)} head={wav[:4]!r}")
    await tts.aclose()


asyncio.run(main())
