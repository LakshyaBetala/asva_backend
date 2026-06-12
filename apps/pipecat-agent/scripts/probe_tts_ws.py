"""One-shot probe of Sarvam Bulbul v3 streaming TTS WebSocket.

Measures first-audio latency and dumps message shapes so the adapter
can be written against reality instead of docs. Costs ~Rs 0.05.
"""
import asyncio
import base64
import os
import sys
import time

from dotenv import dotenv_values

env = {**dotenv_values(".env"), **os.environ}
KEY = env.get("SARVAM_API_KEY", "")
if not KEY:
    sys.exit("no SARVAM_API_KEY")

from sarvamai import AsyncSarvamAI  # noqa: E402


async def main() -> None:
    client = AsyncSarvamAI(api_subscription_key=KEY)
    t0 = time.perf_counter()
    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        print(f"connected in {time.perf_counter()-t0:.2f}s")
        await ws.configure(
            target_language_code="ta-IN",
            speaker="priya",
            speech_sample_rate=8000,
            output_audio_codec="wav",
            min_buffer_size=30,
        )
        t1 = time.perf_counter()
        await ws.convert("Vanakkam sir, naan Priya. Neenga Chennai la property paatheenga-la?")
        await ws.flush()
        chunks = []
        first = None
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except asyncio.TimeoutError:
                print("recv timeout")
                break
            mtype = type(msg).__name__
            if hasattr(msg, "data") and hasattr(msg.data, "audio") and msg.data.audio:
                raw = base64.b64decode(msg.data.audio)
                if first is None:
                    first = time.perf_counter() - t1
                    print(f"FIRST AUDIO: {first*1000:.0f}ms  ({len(raw)} bytes, head={raw[:4]!r})")
                chunks.append(raw)
            else:
                print(f"msg type={mtype}: {str(msg)[:200]}")
                if "final" in str(msg).lower() or mtype == "EventResponse":
                    break
        total = sum(len(c) for c in chunks)
        print(f"chunks={len(chunks)} total_bytes={total} elapsed={time.perf_counter()-t1:.2f}s")
        for i, c in enumerate(chunks[:3]):
            print(f"chunk{i}: {len(c)} bytes head={c[:12]!r}")


asyncio.run(main())
