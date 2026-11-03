"""Controlled provider benchmark through the agent's own clients: n trials each, same input."""
import asyncio, os, sys, time, json, statistics as st
AGENT = r"C:\Users\laksh\almmatix_voice\apps\pipecat-agent"
sys.path.insert(0, AGENT + r"\src")
from dotenv import dotenv_values
env = {k: v for k, v in dotenv_values(AGENT + r"\.env").items() if v}
os.environ.update(env)
import httpx
from voice_agent import smallest_tts, cartesia_tts, elevenlabs_tts, groq_llm, gemini_llm

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
SYS = "You are Priya, a polite real-estate assistant on a phone call. Reply in one short sentence."
USER = "Hi, I saw your listing. Is the 2 BHK in Anna Nagar still available?"
TEXT_HI = "Ji sir, Anna Nagar mein do BHK abhi available hai. Aap kab visit karna chahenge?"
GROQ = "https://api.groq.com/openai/v1"

async def time_stream(gen):
    t = time.perf_counter(); first = None; n = 0
    async for tok in gen:
        if first is None and tok.strip(): first = time.perf_counter() - t
        n += 1
    return first * 1000, (time.perf_counter() - t) * 1000

async def main():
    res = {}
    async with httpx.AsyncClient(timeout=40) as h:
        cases = {
            "LLM Gemini 2.5 Flash (stream)": lambda: time_stream(gemini_llm.stream_generate(system_message=SYS, user_message=USER, api_key=env["GEMINI_API_KEY"], model=env.get("GEMINI_MODEL", "gemini-2.5-flash"), client=h)),
            "LLM gpt-oss-120b @Groq (stream)": lambda: time_stream(groq_llm.stream_generate(system_message=SYS, user_message=USER, api_key=env["GROQ_API_KEY"], model="openai/gpt-oss-120b", client=h, base_url=GROQ)),
            "LLM gpt-oss-20b @Groq (stream)": lambda: time_stream(groq_llm.stream_generate(system_message=SYS, user_message=USER, api_key=env["GROQ_API_KEY"], model="openai/gpt-oss-20b", client=h, base_url=GROQ)),
        }
        async def tts(fn, **kw):
            t = time.perf_counter(); r = await fn(text=TEXT_HI, lang="hi-IN", client=h, **kw); d = (time.perf_counter() - t) * 1000
            return d, len(r.audio)
        cases.update({
            "TTS Smallest": lambda: tts(smallest_tts.synthesize, api_key=env["SMALLEST_API_KEY"], voice=env.get("SMALLEST_VOICE", smallest_tts.DEFAULT_VOICE), model=env.get("SMALLEST_MODEL", smallest_tts.DEFAULT_MODEL)),
            "TTS Cartesia": lambda: tts(cartesia_tts.synthesize, api_key=env["CARTESIA_API_KEY"], voice=env.get("CARTESIA_VOICE", cartesia_tts.DEFAULT_VOICE)),
            "TTS ElevenLabs": lambda: tts(elevenlabs_tts.synthesize, api_key=env["ELEVENLABS_API_KEY"]),
        })
        for name, mk in cases.items():
            xs, err = [], None
            for i in range(N):
                try:
                    xs.append((await mk())[0])
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:120]}"
                await asyncio.sleep(0.5)
            xs.sort()
            res[name] = dict(n=len(xs), p50=round(st.median(xs)) if xs else None, mean=round(st.mean(xs)) if xs else None,
                             min=round(xs[0]) if xs else None, max=round(xs[-1]) if xs else None, last_error=err)
            print(name, res[name], flush=True)
    json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench.json"), "w"), indent=1)

asyncio.run(main())
