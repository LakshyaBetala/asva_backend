"""Time-to-first-audio (STT + LLM first sentence + TTS first sentence) per turn from call-logs.txt,
split by STT mode, phrase-cache use and reply language. Usage: python ttfa.py call-logs.txt"""
import re, sys, statistics as st
rows, kinds = [], {}
for l in open(sys.argv[1], encoding='utf-8', errors='replace'):
    if m := re.search(r'\[([^\]]+)\] PRIYA\s+\[(cache|tts)', l):
        kinds.setdefault(m[1], set()).add(m[2])
    if m := re.search(r'\[([^\]]+)\] TURN\s+reply_lang=(\S+) stt=(\d+)ms llm=(\d+)ms tts=(\d+)ms total=(\d+)ms', l):
        k = kinds.pop(m[1], set()); s, lm, t = int(m[3]), int(m[4]), int(m[5])
        rows.append(dict(lang=m[2], stt=s, llm=lm, tts=t, ttfa=s + lm + t, cache=k == {'cache'}, streaming=s == 0))
def P(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p; f = int(k); c = min(f + 1, len(xs) - 1); return round(xs[f] + (xs[c] - xs[f]) * (k - f))
def S(name, xs): print(f"{name:34} n={len(xs):3} mean={round(st.mean(xs)):5} p50={P(xs, .5):5} p90={P(xs, .9):5} p95={P(xs, .95):5}")
v = [r for r in rows if r['ttfa'] > 0]
S('TTFA all', [r['ttfa'] for r in v])
S('TTFA streaming STT', [r['ttfa'] for r in v if r['streaming']]); S('TTFA batch STT', [r['ttfa'] for r in v if not r['streaming']])
S('STT (batch turns)', [r['stt'] for r in v if not r['streaming']])
S('TTFA phrase-cache turns', [r['ttfa'] for r in v if r['cache']]); S('TTFA synthesized turns', [r['ttfa'] for r in v if not r['cache']])
S('LLM first sentence', [r['llm'] for r in v if r['llm'] > 0]); S('TTS first sentence (synth)', [r['tts'] for r in v if not r['cache']])
for lg in ('en-IN', 'hi-IN', 'ta-IN'): S('TTFA ' + lg, [r['ttfa'] for r in v if r['lang'] == lg])
for thr in (1000, 1500, 2000): print(f'share TTFA < {thr} ms: {100 * sum(r["ttfa"] < thr for r in v) / len(v):.1f}%')
tot = sum(r['ttfa'] for r in v)
print('mean-TTFA share: ' + ', '.join(f"{k}={100 * sum(r[k] for r in v) / tot:.1f}%" for k in ('stt', 'llm', 'tts')))
