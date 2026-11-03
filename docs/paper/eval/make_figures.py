"""Generate the paper's figures from the codebase and call logs.
Usage (from repo root):  python docs/paper/eval/make_figures.py apps/pipecat-agent/call-logs.txt
Writes PDF (for LaTeX) and PNG (for the Markdown draft) into docs/paper/latex/figures/."""
import os, re, sys, statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "latex", "figures")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix", "font.size": 8, "axes.linewidth": 0.6,
    "pdf.fonttype": 42, "ps.fonttype": 42,  # embedded TrueType, no Type 3 fonts
})
INK, PINE, TEAL, MINT, GREY = "#17202A", "#0E4D45", "#2A9D8F", "#DCEBE7", "#F2F4F4"


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".pdf"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def box(ax, x, y, w, h, title, body="", fill=GREY, dark=False, mono=False, fs=7, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.05",
                                fc=fill, ec=INK, lw=0.6, ls=ls))
    c = "white" if dark else INK
    ax.text(x + w / 2, y + h - 0.07, title, ha="center", va="top", fontsize=fs, weight="bold", color=c,
            family="monospace" if mono else None)
    if body:
        ax.text(x + w / 2, y + h - 0.07 - 0.15, body, ha="center", va="top", fontsize=fs - 1, color=c,
                linespacing=1.15, family="monospace" if mono else None)


def arrow(ax, p, q, text="", style="-|>", ls="-", rad=0.0, tpos=0.5, toff=(0, 0.05), fs=6, color=INK):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=7, lw=0.7, ls=ls, color=color,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=1, shrinkB=1))
    if text:
        ax.text(p[0] + (q[0] - p[0]) * tpos + toff[0], p[1] + (q[1] - p[1]) * tpos + toff[1], text,
                ha="center", va="bottom", fontsize=fs, style="italic", color=INK)


# ---------------------------------------------------------------- Fig. 1 architecture
def architecture():
    W, H = 7.16, 3.95
    fig, ax = plt.subplots(figsize=(W, H)); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    # telephony tier
    box(ax, 0.05, 3.05, 1.05, 0.8, "Lead", "PSTN phone\nen-IN / hi-IN / ta-IN")
    box(ax, 1.45, 3.05, 1.45, 0.8, "Exotel Voicebot", "8 kHz 16-bit PCM\nover WebSocket")
    box(ax, 3.25, 3.05, 2.35, 0.8, "Session handler", "exotel_ws_handler.py\nendpointing: server VAD + 400 ms merge,\n700 ms dangling hold | barge-in 2500/500 ms", fill=MINT)
    box(ax, 5.95, 3.05, 1.16, 0.8, "Cost guard", "cost_guard.py\nhard cap 600 s\n+10 s watchdog")
    arrow(ax, (1.1, 3.45), (1.45, 3.45), style="<|-|>")
    arrow(ax, (2.9, 3.45), (3.25, 3.45), style="<|-|>")
    arrow(ax, (5.95, 3.45), (5.6, 3.45), "kill", tpos=0.5)
    # trigger
    box(ax, 0.05, 1.7, 1.05, 1.05, "Call trigger", "call.ps1 →\nPOST /exotel/calls\n(tenant_id, lead_id)\nintro pre-synth")
    arrow(ax, (0.9, 2.75), (1.7, 3.05))
    ax.text(0.86, 2.86, "dial (REST)", ha="right", fontsize=6, style="italic")
    # turn engine
    ax.add_patch(FancyBboxPatch((1.4, 1.5), 5.71, 1.3, boxstyle="round,pad=0,rounding_size=0.05", fc="white", ec=PINE, lw=1.0))
    ax.text(1.5, 1.71, "Turn engine —\nstreaming_orchestrator.py", fontsize=6.8, weight="bold", color=PINE, va="center")
    stages = [("STT", "Sarvam Saaras\nstreaming | batch"),
              ("Language FSM", "language_state.py\n$\\tau_c$=0.75, H=2"),
              ("LLM stream", "Gemini 2.5 Flash\nkey pool → Groq\n→ hold line"),
              ("Sentence split", "boundary . ? ! danda\n≤ 2 sentences/turn"),
              ("TTS / cache", "Bulbul (Sarvam)\nsha256(text,voice,\nlang) → R2")]
    xs = [1.5 + i * 1.12 for i in range(5)]
    for x, (t, b) in zip(xs, stages):
        box(ax, x, 1.93, 1.0, 0.68, t, b, fill=MINT, fs=6.6)
    for i in range(4):
        arrow(ax, (xs[i] + 1.0, 2.27), (xs[i + 1], 2.27))
    box(ax, 3.74, 1.56, 1.0, 0.3, "Phase machine", "", fill=GREY, fs=6)
    box(ax, 4.86, 1.56, 2.1, 0.3, "Slot extractor (concurrent)", "", fill=GREY, fs=6, ls="--")
    arrow(ax, (4.24, 1.86), (4.24, 1.93))
    arrow(ax, (4.74, 2.05), (5.0, 1.86), ls="--")
    arrow(ax, (3.6, 3.05), (2.0, 2.61))
    ax.text(2.95, 2.93, "utterance", ha="center", fontsize=6, style="italic")
    arrow(ax, (6.0, 2.61), (5.2, 3.05))
    ax.text(6.05, 2.84, "audio, per sentence", ha="left", fontsize=6, style="italic")
    # persistence and back office
    box(ax, 0.05, 0.12, 1.05, 1.1, "Post-call", "lead_scorer.py\nhot | warm |\ncold | dead\n+ score 0–100")
    box(ax, 1.45, 0.12, 1.4, 1.1, "Persistence", "supabase_client.py\nasync background\ntasks: calls, turns,\nslots, latencies")
    box(ax, 3.2, 0.12, 2.05, 1.1, "PostgreSQL 17 (Supabase)", "13 tables · 37 RLS policies\nbilling trigger · 1 view · 4 functions\nrealtime: calls, transcripts,\nlead_scores", fill=PINE, dark=True)
    box(ax, 5.55, 0.7, 1.56, 0.6, "CRM (Next.js)", "JWT tenant claim → RLS\nrealtime subscription")
    box(ax, 5.55, 0.05, 1.56, 0.55, "Workers (Cloudflare)", "dispatch (spend cap)\nscore · handoff · webhooks")
    arrow(ax, (2.15, 1.5), (2.15, 1.22), "writes", tpos=0.5, toff=(0.22, -0.06))
    arrow(ax, (1.1, 0.67), (1.45, 0.67))
    arrow(ax, (2.85, 0.67), (3.2, 0.67))
    arrow(ax, (5.55, 1.0), (5.25, 0.85), style="<|-|>")
    arrow(ax, (5.55, 0.32), (5.25, 0.45), style="<|-|>")
    save(fig, "fig_architecture")


# ---------------------------------------------------------------- Fig. 2 latency
def latency(log):
    rows, kinds = [], {}
    for l in open(log, encoding="utf-8", errors="replace"):
        if m := re.search(r"\[([^\]]+)\] PRIYA\s+\[(cache|tts)", l):
            kinds.setdefault(m[1], set()).add(m[2])
        if m := re.search(r"\[([^\]]+)\] TURN\s+reply_lang=(\S+) stt=(\d+)ms llm=(\d+)ms tts=(\d+)ms total=(\d+)ms", l):
            k = kinds.pop(m[1], set()); s, lm, t = int(m[3]), int(m[4]), int(m[5])
            if s + lm + t > 0:
                rows.append(dict(lang=m[2], stt=s, llm=lm, tts=t, T=s + lm + t, cache=k == {"cache"}, stream=s == 0))
    fig, (a, b) = plt.subplots(2, 1, figsize=(3.5, 4.0), gridspec_kw=dict(height_ratios=[1.35, 1], hspace=0.55))
    series = [("Streaming STT", [r["T"] for r in rows if r["stream"]], "-", PINE),
              ("Batch STT", [r["T"] for r in rows if not r["stream"]], "--", INK),
              ("Cached first sentence", [r["T"] for r in rows if r["cache"]], ":", TEAL)]
    for name, xs, ls, c in series:
        xs = sorted(x / 1000 for x in xs)
        a.step(xs, [(i + 1) / len(xs) for i in range(len(xs))], where="post", ls=ls, color=c, lw=1.1,
               label=f"{name} (n={len(xs)}, median {st.median(xs):.2f} s)")
    a.axvline(2.0, color="grey", lw=0.6, ls="-."); a.text(2.05, 0.47, "2 s", fontsize=7, color="grey")
    a.set_xlim(0, 5); a.set_ylim(0, 1.0); a.set_xlabel(r"$\hat{T}$ = STT + first LLM sentence + first TTS sentence (s)")
    a.set_ylabel("Fraction of turns"); a.grid(alpha=0.25, lw=0.4); a.legend(fontsize=6.3, loc="lower right", frameon=False)
    a.set_title("(a) Empirical CDF of time to first audio", fontsize=8)
    groups = [("All", rows)] + [(n, [r for r in rows if r["lang"] == c]) for n, c in (("English", "en-IN"), ("Hindi", "hi-IN"), ("Tamil", "ta-IN"))]
    y = list(range(len(groups)))[::-1]
    left = [0.0] * len(groups)
    for key, lab, fill, hatch in (("stt", "STT", "#BFD8D2", "///"), ("llm", "LLM, 1st sentence", PINE, ""), ("tts", "TTS, 1st sentence", TEAL, "...")):
        vals = [st.mean(r[key] for r in g) / 1000 for _, g in groups]
        b.barh(y, vals, left=left, color=fill, hatch=hatch, edgecolor=INK, lw=0.4, height=0.6, label=lab)
        left = [l + v for l, v in zip(left, vals)]
    for yi, (n, g), l in zip(y, groups, left):
        b.text(l + 0.04, yi, f"{l:.2f} s (n={len(g)})", va="center", fontsize=6.5)
    b.set_yticks(y); b.set_yticklabels([g[0] for g in groups]); b.set_xlim(0, 2.4)
    b.set_xlabel("Mean contribution to $\\hat{T}$ (s)"); b.grid(axis="x", alpha=0.25, lw=0.4)
    b.legend(fontsize=6.3, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.32), frameon=False, handlelength=1.4)
    b.set_title("(b) Mean stage composition by reply language", fontsize=8)
    save(fig, "fig_ttfa")


# ---------------------------------------------------------------- Fig. 3 schema
def schema():
    W, H, Y0 = 7.16, 4.2, 0.3
    fig, ax = plt.subplots(figsize=(W, H - Y0)); ax.set_xlim(0, W); ax.set_ylim(Y0, H); ax.axis("off")
    E, ROW = {}, 0.125

    def ent(name, x, top, w, cols, kind="", tenant=False):
        h = 0.2 + ROW * len(cols); y = top - h
        fill = PINE if kind == "root" else MINT if kind == "core" else GREY
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.03", fc=fill, ec=INK, lw=0.6))
        c = "white" if kind == "root" else INK
        ax.text(x + 0.05, top - 0.04, name, va="top", fontsize=6.6, weight="bold", family="monospace", color=c)
        if tenant:
            ax.text(x + w - 0.05, top - 0.04, "T", va="top", ha="right", fontsize=6, weight="bold", color=TEAL,
                    bbox=dict(boxstyle="round,pad=0.1", fc="white", ec=TEAL, lw=0.5))
        for i, col in enumerate(cols):
            ax.text(x + 0.05, top - 0.19 - ROW * i, col, va="top", fontsize=5.0, family="monospace", color=c)
        E[name] = (x, y, w, h, top)

    def row_y(name, i):  # vertical centre of column row i
        return E[name][4] - 0.19 - ROW * i - 0.05

    def fk(p, q):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=6, lw=0.55, color=INK, shrinkA=0, shrinkB=0))

    ent("tenants", 0.05, 4.12, 1.35, ["PK id", "UQ slug", "persona_lang_default", "monthly_unit_allowance",
                                      "daily_spend_cap_inr", "agent_enabled", "telephony_mode"], "root")
    ent("users", 1.62, 4.12, 1.72, ["PK id -> auth.users", "FK tenant_id -> tenants (R)", "role CHECK admin|rep"])
    ent("campaigns", 1.62, 2.6, 1.72, ["PK id", "FK created_by -> users (N)", "script_version"], tenant=True)
    ent("dnc_list", 1.62, 1.05, 1.72, ["PK (tenant_id, phone_e164)", "reason, added_at"], tenant=True)
    ent("leads", 3.58, 4.12, 1.86, ["PK id", "FK assigned_to -> users (N)", "UQ (tenant_id, phone_e164)",
                                  "status CHECK (9 values)", "preferred_lang CHECK"], "core", tenant=True)
    ent("calls", 3.58, 2.15, 1.86, ["PK id", "FK lead_id -> leads (C)", "FK campaign_id -> campaigns (N)",
                                  "billed_units CHECK 0-4", "estimated_cost_inr >= 0", "TRIGGER compute_billed_units"], "core", tenant=True)
    right = [("lead_intro_audio", ["FK lead_id -> leads (C)", "UQ (lead_id, lang)"], True),
             ("handoffs", ["FK lead_id -> leads (C)", "FK call_id -> calls (N)"], False),
             ("lead_scores", ["FK lead_id -> leads (C)", "FK call_id -> calls (C) 1:1"], False),
             ("qualification_slots", ["PK/FK call_id -> calls 1:1", "FK lead_id -> leads (C)"], True),
             ("transcripts", ["FK call_id -> calls (C)", "UQ (call_id, idx)"], False),
             ("call_events", ["FK call_id -> calls (C)", "UQ (call_id, event_id)"], False),
             ("turn_latencies", ["FK call_id -> calls (C)", "UQ (call_id, turn_idx)"], True)]
    top = 4.12
    for name, cols, t in right:
        ent(name, 5.52, top, 1.6, cols, tenant=t); top -= 0.2 + ROW * len(cols) + 0.1

    L, R = (lambda n: E[n][0]), (lambda n: E[n][0] + E[n][2])
    fk((L("users"), row_y("users", 1)), (R("tenants"), row_y("tenants", 0)))
    fk((L("users") + 0.8, E["campaigns"][4]), (L("users") + 0.8, E["users"][1]))          # campaigns.created_by
    fk((L("leads"), row_y("leads", 1)), (R("users"), row_y("users", 0)))
    fk((L("calls") + 0.9, E["calls"][4]), (L("calls") + 0.9, E["leads"][1]))              # calls.lead_id
    fk((L("calls"), row_y("calls", 2)), (R("campaigns"), row_y("campaigns", 0)))
    lead_t = iter([E["leads"][4] - 0.25 - 0.13 * i for i in range(4)])
    call_t = iter([E["calls"][4] - 0.12 - 0.15 * i for i in range(6)])
    for name, cols, _ in right:
        for i, col in enumerate(cols):
            if "-> leads" in col:
                fk((L(name), row_y(name, i)), (R("leads"), next(lead_t)))
            elif "-> calls" in col:
                fk((L(name), row_y(name, i)), (R("calls"), next(call_t)))
    ax.text(0.05, 2.85, "Arrow: foreign key,\n  child -> parent\nON DELETE:\n  C = CASCADE\n  N = SET NULL\n  R = RESTRICT\n"
            "T = FK tenant_id ->\n  tenants (C)\n1:1 = one row per call\nRLS on every table:\n  tenant_id, or EXISTS\n  through calls / leads",
            fontsize=5.8, va="top", linespacing=1.25, family="monospace")
    save(fig, "fig_schema")


if __name__ == "__main__":
    architecture()
    latency(sys.argv[1] if len(sys.argv) > 1 else "apps/pipecat-agent/call-logs.txt")
    schema()
    print("written to", os.path.normpath(OUT))
