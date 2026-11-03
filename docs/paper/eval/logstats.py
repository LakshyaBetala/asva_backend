"""Turn-level statistics from apps/pipecat-agent/call-logs.txt (real calls + local-harness sessions)."""
import re, statistics as st, sys, collections, json
lines = open(sys.argv[1], encoding='utf-8', errors='replace').read().splitlines()
turns, calls, cur = [], {}, {}
lead_re = re.compile(r'\] LEAD\s+\[(\S+) conf=([\d.]+) intent=(\w+)\]')
turn_re = re.compile(r'\[([^\]]+)\] TURN\s+reply_lang=(\S+) stt=(\d+)ms llm=(\d+)ms tts=(\d+)ms total=(\d+)ms')
end_re = re.compile(r'\[([^\]]+)\] END\s+elapsed=([\d.]+)s turns=(\d+) cache_hits=(\d+)')
start_re = re.compile(r'\[([^\]]+)\] START\s+lang=(\S+)')
last_lead, prev_lang = {}, {}
for l in lines:
    if m := start_re.search(l): prev_lang[m[1]] = m[2]
    if m := lead_re.search(l): last_lead = dict(lang=m[1], conf=float(m[2]), intent=m[3])
    if m := turn_re.search(l):
        cid = m[1]; t = dict(call=cid, reply_lang=m[2], stt=int(m[3]), llm=int(m[4]), tts=int(m[5]), total=int(m[6]), **last_lead)
        t['switch'] = prev_lang.get(cid) not in (None, m[2]); prev_lang[cid] = m[2]
        turns.append(t)
    if m := end_re.search(l): calls[m[1] + l[:12]] = dict(elapsed=float(m[2]), turns=int(m[3]), cache=int(m[4]))
def pct(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p; f = int(k); c = min(f + 1, len(xs) - 1); return xs[f] + (xs[c] - xs[f]) * (k - f)
def summ(xs): return dict(n=len(xs), mean=round(st.mean(xs)), p50=round(pct(xs, .5)), p90=round(pct(xs, .9)), p95=round(pct(xs, .95)), min=min(xs), max=max(xs)) if xs else {}
out = {}
for k in ('stt', 'llm', 'tts', 'total'):
    out[k] = summ([t[k] for t in turns])
out['other_ms(total-stt-llm-tts)'] = summ([t['total'] - t['stt'] - t['llm'] - t['tts'] for t in turns])
out['total_by_reply_lang'] = {lg: summ([t['total'] for t in turns if t['reply_lang'] == lg]) for lg in sorted({t['reply_lang'] for t in turns})}
out['tts_by_reply_lang'] = {lg: summ([t['tts'] for t in turns if t['reply_lang'] == lg]) for lg in sorted({t['reply_lang'] for t in turns})}
out['total_switch_vs_not'] = {'switch': summ([t['total'] for t in turns if t['switch']]), 'same': summ([t['total'] for t in turns if not t['switch']])}
out['lead_intent_counts'] = dict(collections.Counter(t.get('intent') for t in turns))
out['lead_lang_counts'] = dict(collections.Counter(t.get('lang') for t in turns))
out['stt_conf'] = summ([round(t['conf'] * 100) for t in turns if 'conf' in t])
out['share_turns_total_under_ms'] = {thr: round(100 * sum(t['total'] < thr for t in turns) / len(turns), 1) for thr in (1000, 1500, 2000, 3000)}
real = [c for c in calls.values() if c['turns'] > 0]
out['calls_with_turns'] = dict(n=len(real), turns=summ([c['turns'] for c in real]), elapsed_s=summ([round(c['elapsed']) for c in real]),
                               cache_hits_total=sum(c['cache'] for c in real))
out['distinct_call_ids_with_turns'] = len({t['call'] for t in turns})
# stage share of total
tot = sum(t['total'] for t in turns)
out['stage_share_pct'] = {k: round(100 * sum(t[k] for t in turns) / tot, 1) for k in ('stt', 'llm', 'tts')}
print(json.dumps(out, indent=1))
