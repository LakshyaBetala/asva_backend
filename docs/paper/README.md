# Paper materials

| File | Phase | Content |
|---|---|---|
| `PAPER_ANALYSIS.md` | 1 | Technical analysis: problem, contributions, formal model, implementation, metrics, limitations |
| `IEEE_PAPER_DRAFT.md` | 2 | Full IEEE-style draft |
| `latex/main.tex`, `latex/references.bib` | 3 | IEEEtran conference source for Overleaf (single file, ASCII only, no external images) |
| `ASVA_ieee_overleaf.zip` | 3 | The two LaTeX files zipped for Overleaf "Upload Project" |
| `eval/` | — | Scripts and raw output behind every number in the paper |

## Reproducing the numbers

```powershell
cd apps/pipecat-agent
python ../../docs/paper/eval/logstats.py call-logs.txt   # sessions, turns, intents, languages
python ../../docs/paper/eval/ttfa.py call-logs.txt       # Tables I and II
python ../../docs/paper/eval/bench.py 10                  # Table III (calls live APIs; uses .env keys)
```

`call-logs.txt` is gitignored (it contains pilot-call transcripts), so the log-derived tables can only be regenerated on a machine that has it. `eval/bench.json` holds the benchmark run of 2026-11-03.

## Before submission

- Fill in authors and affiliation in `latex/main.tex` and the draft.
- The three figures are drawn placeholder boxes (`\figplaceholder`); replace each with `\includegraphics` once the figure file is uploaded alongside `main.tex`.
- Check every reference on IEEE Xplore / the publisher's site (pages, volume) before submitting.
- Results come from internal pilot sessions; the paper states this. Do not describe them as customer deployments.
