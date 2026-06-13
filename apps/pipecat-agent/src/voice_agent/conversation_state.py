"""Conversation phase machine + anti-AI sound enforcement.

Why this exists
---------------
Latency and language are necessary but not sufficient. The "this is a robot"
moment comes from three behaviors that humans don't do:

  1. Repeating the same acknowledgment ("Got it. Got it. Got it.").
  2. Zero filler words across the whole call (no "ji", "haan", "achha").
  3. Paraphrasing yourself (Priya saying the same idea two turns apart).

This module encodes those as hard state. The system prompt receives the
current state every turn and the LLM is instructed to avoid the recorded
patterns. A post-turn audit catches anything that slipped through.

Phases drive a second behavior: Priya doesn't ask qualifying questions
during the CONNECT phase (it's rapport time), and doesn't pitch during
DISCOVER (it's listening time). The phase machine advances on time +
extracted-slot count + buying_confidence; never goes backwards.

EXTENSION phase is the dual-billing seam: at 170s, if buying_confidence
is high, Priya gets another 180s of runway (call bills as 2 units).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


def native_tamil_script_enabled() -> bool:
    """True when Tamil replies should be written in Tamil script.

    Bulbul v3 pronounces native Tamil script far better than romanized
    Tanglish (romanized text is read with English letter-phonetics —
    the "Tamil pronunciation is bad" feedback, 2026-06-13). Only active
    on the all-Sarvam stack; the old smallest/cartesia voices needed
    Roman text. TTS_NATIVE_TA=0 reverts."""
    return (
        os.environ.get("TTS_PROVIDER", "").strip().lower() == "sarvam"
        and os.environ.get("TTS_NATIVE_TA", "1") != "0"
    )


def native_hindi_script_enabled() -> bool:
    """True when Hindi replies should be written in Devanagari.

    Same mechanism as Tamil: romanized Hinglish ("dekh rahe hain") gets
    English letter-phonetics from the TTS — user rated Hindi 5/10 on
    pronunciation (call f838d0d5, 2026-06-13). Devanagari hits Bulbul's
    native Hindi phonemes; English business words stay in English
    letters inside the sentence. TTS_NATIVE_HI=0 reverts."""
    return (
        os.environ.get("TTS_PROVIDER", "").strip().lower() == "sarvam"
        and os.environ.get("TTS_NATIVE_HI", "1") != "0"
    )


class Phase(str, Enum):
    GREETING = "greeting"
    CONNECT = "connect"
    DISCOVER = "discover"
    QUALIFY = "qualify"
    CLOSE = "close"
    EXTENSION = "extension"


# Phase transition thresholds (seconds elapsed).
# Aligned with credit boundaries: 150s (1 credit), 300s (2 credits), 450s (3 credits).
GREETING_END_SEC = 8.0
CONNECT_END_SEC = 35.0
DISCOVER_END_SEC = 70.0
QUALIFY_END_SEC = 130.0   # Qualify before 1st credit boundary
CLOSE_END_SEC = 140.0     # Soft close at 140s → hard boundary at 150s
EXTENSION_END_SEC = 290.0  # Extension before 2nd credit boundary

# Minimum buying_confidence at 170s soft-close to enter EXTENSION instead
# of wrapping up. Below this, we go to CLOSE and end gracefully.
EXTENSION_CONFIDENCE_FLOOR = 0.6

# Anti-repetition rolling window: last N Priya turns kept verbatim in
# context with rule "do not paraphrase your own recent turns".
# 8 turns ≈ a full qualification arc (intent→locality→BHK→budget→slot→
# confirm). 4 was too small — the lead's "rent" answer fell out of the
# window before the budget question, producing crore-questions to renters.
RECENT_TURNS_WINDOW = 8

# Minimum fillers per N turns. If Priya goes 3 turns without "ji/haan/
# achha/right/okay", the audit flags it.
MIN_FILLERS_PER_WINDOW = 1
FILLER_AUDIT_WINDOW = 3

# Fillers that count for the audit. Multilingual on purpose — Priya uses
# Hindi fillers in English turns and vice versa (human bilinguals do this).
FILLERS: frozenset[str] = frozenset({
    "ji", "haan", "achha", "acha", "theek", "sahi", "bilkul",
    "right", "okay", "ok", "sure", "got it", "i see", "mhm", "hmm",
    "sari", "aama", "seri",
})


@dataclass
class ConversationState:
    """Per-call conversation state. One instance lives for the call."""

    phase: Phase = Phase.GREETING

    # Acknowledgments Priya has already used this call. The LLM is told to
    # avoid these and pick a different one.
    used_acknowledgments: set[str] = field(default_factory=set)

    # Recent Priya turns (verbatim) for self-repetition prevention.
    recent_priya_turns: list[str] = field(default_factory=list)

    # Recent lead turns (verbatim, trimmed). Without this the LLM has zero
    # memory of what the lead said across turns and keeps re-asking the same
    # questions even after the lead just answered them.
    recent_lead_turns: list[str] = field(default_factory=list)

    # Rolling window of "did the last K turns contain at least one filler?"
    # Used to nudge the LLM if Priya is sounding too formal.
    filler_window: list[bool] = field(default_factory=list)

    # Tracking for the soft-close: number of consecutive turns Priya has
    # tried to close vs the lead extended the conversation. Prevents the
    # robot loop of "alright, anything else?" / "no" / "alright, anything else?"
    consecutive_close_attempts: int = 0

    # How many times the lead has been off-topic (pizza, "kaun bol raha",
    # random chat). Priya probes ONCE for a real requirement; on the second
    # off-topic turn we end the call. See classify_lead_intent.
    off_topic_count: int = 0

    # How many times the lead has refused. First refusal → ask for a referral;
    # second → warm goodbye + hang up. ("Try our best, then stop.")
    reject_count: int = 0

    # Consecutive "passive listener" turns — lead only acknowledges ("acha",
    # "haan", "hmm") without answering. After a couple of these Priya stops
    # explaining and asks a short, direct question to pull them in.
    backchannel_count: int = 0

    # Consecutive "normal" turns that produced no new qualifying info AND
    # were short / non-committal. Three of these in a row = not a buyer,
    # exit warmly. Call 1 went 371s because we had no such counter — lead
    # kept asking general chemistry questions and Priya kept selling.
    unproductive_turn_count: int = 0

    # Set once buying signals are firm (pain_point + timeline OR supplier
    # complaint). The next turn MUST close — no more discovery questions.
    close_armed: bool = False

    # Consecutive turns where the lead's audio came through garbled (wrong
    # script for the call language / line noise) and Priya asked them to
    # repeat. Capped at 2 — after that we stop re-prompting and let the LLM
    # do its best, so a noisy line never becomes a "can you repeat?" loop.
    repeat_request_count: int = 0

    # The lead's own words choosing a site-visit slot ("सैटरडे सुबह").
    # site_visit isn't one of the extractor's slots, so without this Priya
    # had no memory of the choice and re-offered "Saturday ya Sunday?"
    # FOUR times in call be21ced9 — lead: "मैम पागल हो गया मैम".
    visit_slot_text: str = ""

    # Phase entry timestamps for telemetry + debugging.
    phase_entered_at: dict[Phase, float] = field(default_factory=dict)

    def advance_phase_if_due(
        self,
        *,
        elapsed_sec: float,
        buying_confidence: float,
    ) -> Phase:
        """Compute the phase Priya should be in right now. Monotonic — never goes back.

        - <8s: GREETING
        - 8-35s: CONNECT (rapport, no product questions)
        - 35-70s: DISCOVER (pain hypothesis floated)
        - 70-150s: QUALIFY (slot-filling questions interleaved with value statements)
        - 150-170s: CLOSE (commit-question based on score)
        - 170-350s: EXTENSION (only if buying_confidence >= 0.6 at 170s)
        - >350s: CLOSE again (final wrap), 360s = hard stop in pipeline.py
        """
        if elapsed_sec < GREETING_END_SEC:
            target = Phase.GREETING
        elif elapsed_sec < CONNECT_END_SEC:
            target = Phase.CONNECT
        elif elapsed_sec < DISCOVER_END_SEC:
            target = Phase.DISCOVER
        elif elapsed_sec < QUALIFY_END_SEC:
            target = Phase.QUALIFY
        elif elapsed_sec < CLOSE_END_SEC:
            target = Phase.CLOSE
        elif elapsed_sec < EXTENSION_END_SEC:
            # 170-350s: extend only if real buying signal present.
            if (
                self.phase == Phase.EXTENSION
                or buying_confidence >= EXTENSION_CONFIDENCE_FLOOR
            ):
                target = Phase.EXTENSION
            else:
                target = Phase.CLOSE
        else:
            target = Phase.CLOSE

        # Monotonic advance: never go back to an earlier phase. The one
        # exception is GREETING → anything (initial transition).
        if _phase_rank(target) > _phase_rank(self.phase):
            self.phase = target
            self.phase_entered_at.setdefault(target, elapsed_sec)
        return self.phase

    def record_priya_turn(self, text: str) -> None:
        """Called after Priya speaks. Updates ack tracker + recent buffer + filler audit.

        Filler audit tracks Priya's own filler density — too few fillers in a
        row and she starts sounding formal/robotic. The lead's fillers are
        irrelevant to that.
        """
        ack = _extract_leading_ack(text)
        if ack:
            self.used_acknowledgments.add(ack)

        self.recent_priya_turns.append(text)
        if len(self.recent_priya_turns) > RECENT_TURNS_WINDOW:
            self.recent_priya_turns = self.recent_priya_turns[-RECENT_TURNS_WINDOW:]

        self.filler_window.append(_contains_filler(text))
        if len(self.filler_window) > FILLER_AUDIT_WINDOW:
            self.filler_window = self.filler_window[-FILLER_AUDIT_WINDOW:]

    def record_lead_turn(self, text: str) -> None:
        """Append a lead utterance to the rolling window. Empty/whitespace skipped."""
        t = (text or "").strip()
        if not t:
            return
        self.recent_lead_turns.append(t)
        if len(self.recent_lead_turns) > RECENT_TURNS_WINDOW:
            self.recent_lead_turns = self.recent_lead_turns[-RECENT_TURNS_WINDOW:]

    def filler_audit_failing(self) -> bool:
        """True when the last N Priya turns had fewer than required fillers.

        When True, the next system prompt nudges: "Add a natural filler word
        like 'ji', 'haan', 'achha' to your next response."
        """
        if len(self.filler_window) < FILLER_AUDIT_WINDOW:
            return False
        return sum(self.filler_window) < MIN_FILLERS_PER_WINDOW

    def note_close_attempt(self, lead_extended: bool) -> None:
        """Called in CLOSE/EXTENSION when Priya attempts a wrap-up.

        If the lead keeps talking (lead_extended=True), reset the counter.
        If Priya tries to close 3 turns in a row and the lead is silent,
        we force-end to avoid the robot loop.
        """
        if lead_extended:
            self.consecutive_close_attempts = 0
        else:
            self.consecutive_close_attempts += 1

    def should_force_end(self) -> bool:
        """Stop the robot loop of 'anything else?' / 'no' / 'anything else?'
        OR exit warmly when the lead has spent 5 turns saying nothing useful.

        Threshold raised from 3 → 5: terse cold-call openers in Tamil/Hindi
        (1-3 word replies) are normal warm behaviour, not tire-kicking."""
        return (
            self.consecutive_close_attempts >= 3
            or self.unproductive_turn_count >= 5
        )


def _phase_rank(p: Phase) -> int:
    return {
        Phase.GREETING: 0,
        Phase.CONNECT: 1,
        Phase.DISCOVER: 2,
        Phase.QUALIFY: 3,
        Phase.CLOSE: 4,
        Phase.EXTENSION: 5,
    }[p]


_ACK_PATTERNS: tuple[str, ...] = (
    "got it", "understood", "makes sense", "i see", "i understand",
    "achha", "acha", "theek hai", "sahi", "bilkul", "haan ji",
    "sari", "aama", "puriyudhu",
    "right", "okay", "sure", "alright",
)


def _extract_leading_ack(text: str) -> str | None:
    """Pull the leading acknowledgment from a Priya turn, normalized.

    "Got it. So you handle 500kg per month?" → "got it"
    "Achha, and what about delivery times?" → "achha"
    """
    lower = text.lower().strip()
    for ack in _ACK_PATTERNS:
        if lower.startswith(ack):
            return ack
    return None


def _contains_filler(text: str) -> bool:
    """True if the Priya turn contains at least one filler word/phrase."""
    lower = " " + text.lower() + " "
    for f in FILLERS:
        # Pad with spaces to avoid matching "okay" inside "okayed".
        if f" {f} " in lower or f" {f}." in lower or f" {f}," in lower:
            return True
    return False


def system_prompt_addendum(state: ConversationState, language: str = "hi-IN") -> str:
    """Per-turn dynamic addendum injected into Priya's system prompt.

    The hints below are language-aware. Earlier the close hint was hard-coded
    Hindi ("isi number pe WhatsApp pe quote"), which kept leaking Hindi tokens
    into Tamil replies — exactly what TN leads notice and complain about.
    """
    parts: list[str] = []

    native_ta = language == "ta-IN" and native_tamil_script_enabled()
    native_hi = language == "hi-IN" and native_hindi_script_enabled()
    if native_ta or native_hi:
        parts.append(
            "<format>1-2 sentences. "
            "Never re-introduce yourself or greet again. If the lead asks who "
            "you are or your name, answer it briefly, then continue.</format>"
        )
    else:
        parts.append(
            "<format>ROMAN SCRIPT ONLY. 1-2 sentences. "
            "Never re-introduce yourself or greet again. If the lead asks who "
            "you are or your name, answer it briefly, then continue.</format>"
        )

    # Hard language pin per turn. Critical for Tamil: without this the LLM
    # keeps drifting back to Hindi tokens because the corpus skews that way.
    if language == "ta-IN" and native_ta:
        parts.append(
            "<LANG_PIN>RESPOND IN TAMIL SCRIPT (தமிழ்) — casual SPOKEN "
            "Chennai Tamil, the way a broker's assistant actually talks on "
            "the phone. NEVER written/literary Tamil — a lead hung up "
            "calling it 'மோசமான தமிழ்'.\n"
            "RIGHT (spoken): 'சரி sir, Anna Nagar-ல two BHK பாக்கலாம். "
            "உங்க budget எவ்ளோ sir?' / 'நீங்க rent-கு பாக்கறீங்களா, "
            "வாங்கறதுக்கா?'\n"
            "WRONG (literary, banned): 'நீங்கள் வாங்க விரும்புகிறீர்களா?' / "
            "'எவ்வளவு செலவு செய்ய விரும்புகிறீர்கள்?'\n"
            "Rules: verb endings -ங்க/-றீங்க (பாக்கறீங்க, சொல்லுங்க), never "
            "-கிறீர்கள்; உங்க not உங்கள்; எவ்ளோ not எவ்வளவு; இல்ல not "
            "இல்லை; வேணும் not வேண்டும். English business words (BHK, "
            "budget, WhatsApp, site visit, Saturday) stay in English "
            "letters. ZERO HINDI TOKENS (subah, bilkul, theek are Hindi — "
            "banned). Always a comma after the opening ack.</LANG_PIN>"
        )
    elif language == "ta-IN":
        parts.append(
            "<LANG_PIN>RESPOND IN TANGLISH (Tamil grammar + English business words). "
            "ZERO HINDI TOKENS. Banned: isi, aa jayega, jayega, deti hoon, "
            "karte hain, achha, bilkul, theek hai, mai, hum, hain, kijiye, "
            "bhejna, bhej, toh, abhi. Use clean spellings: sir (not sarr), "
            "sari (not sariyaa), irukku, tharen, pannuren, sollunga, anuppuren, "
            "pesalam, kandippa, evlo. Always comma after the opening ack.</LANG_PIN>"
        )
    if language == "ta-IN":
        # Override ack filler nudge for Tamil — Hindi fillers sound wrong here.
        ack_nudge_lang = "sari/aama/enna"
        close_hint = (
            "Close in PURE TAMIL: "
            "'Sari sir, matching properties indha number ku WhatsApp la "
            "anuppuren. Site visit ku Saturday-aa, Sunday-aa?' "
            "Confirm the slot, then thank + stop."
        )
        connect_hint = (
            "Veedu vaanganum-aa illa rent-ku-aa paakareenga sir? "
            "ONE question only, in Tamil."
        )
        discover_hint = (
            "Find their must-have in Tamil — endha area-aa, budget-aa, "
            "school pakkathula-aa? Tamil only, no Hindi."
        )
        qualify_hint = (
            "Ask the missing one of budget / area / BHK in Tamil "
            "(evlo budget, endha area, ethana BHK). "
            "Give ONE value point in Tamil."
        )
        ext_hint = "Strong buying signal. Push for the Tamil close NOW."
    elif language == "en-IN":
        parts.append(
            "<LANG_PIN>RESPOND IN INDIAN BUSINESS ENGLISH. "
            "No Hindi or Tamil tokens unless the lead just used them.</LANG_PIN>"
        )
        ack_nudge_lang = "right/sure/got it"
        close_hint = (
            "Close: 'I'll WhatsApp matching options to this number, sir. "
            "Saturday or Sunday for the site visit?' "
            "Confirm the slot, then thank + stop."
        )
        connect_hint = "Ask buying or renting. ONE question only."
        discover_hint = "Find their must-have — locality? budget? possession timeline?"
        qualify_hint = (
            "Ask the missing one of budget / locality / BHK. "
            "Give ONE value point."
        )
        ext_hint = "Strong signal. Push for close."
    else:  # hi-IN
        if native_hi:
            parts.append(
                "<LANG_PIN>RESPOND IN DEVANAGARI (हिंदी) — casual broker-"
                "phone Hindi, the way a Mumbai broker's assistant actually "
                "talks.\n"
                "RIGHT (spoken): 'अच्छा जी, Anna Nagar में 2 BHK देखते हैं. "
                "Budget क्या रखा है आपने?' / 'घर अपने रहने के लिए चाहिए या "
                "rent पे देना है?'\n"
                "WRONG (shuddh, banned): 'आप कितना व्यय करना चाहते हैं?' / "
                "'कृपया अपना निवास स्थान बताइए.'\n"
                "Everyday words only (घर, दिखा दूँगी, मिल जाएगा, बता दीजिए); "
                "निवास/आवास/कृपया banned. You are FEMALE — always समझ गई / "
                "कर दूँगी / पूछ रही हूँ, NEVER समझ गया / पूछ रहा हूँ. "
                "English business words (BHK, budget, WhatsApp, site visit, "
                "Saturday) stay in English letters inside the "
                "sentence.</LANG_PIN>"
            )
        else:
            parts.append(
                "<LANG_PIN>RESPOND IN COLLOQUIAL HINGLISH (Roman script) — the "
                "way a broker's assistant talks on the phone: 'aap', 'ji', "
                "short sentences, everyday words (ghar, flat, dekh lijiye, "
                "bata dijiye, mil jayega). NEVER textbook shuddh Hindi "
                "(nivas, awas, kripya are banned). English business words "
                "(BHK, budget, WhatsApp, site visit) stay as-is.</LANG_PIN>"
            )
        ack_nudge_lang = "ji/haan/achha"
        if native_hi:
            close_hint = (
                "Close: 'Matching options इसी number पे WhatsApp कर दूँगी. "
                "Site visit Saturday या Sunday?' "
                "Confirm the slot, then thank + stop."
            )
        else:
            close_hint = (
                "Close: 'Matching options isi number pe WhatsApp kar doongi. "
                "Site visit Saturday ya Sunday?' "
                "Confirm the slot, then thank + stop."
            )
        connect_hint = "Ask buying or renting. ONE question only."
        discover_hint = "Find their must-have — locality? budget? possession timeline?"
        qualify_hint = (
            "Ask the missing one of budget / locality / BHK. "
            "Give ONE value point."
        )
        ext_hint = "Strong signal. Push for close."

    parts.append(f"<current_phase>{state.phase.value}</current_phase>")

    if state.used_acknowledgments:
        used = ", ".join(sorted(state.used_acknowledgments))
        parts.append(f"<used_acks>{used}</used_acks>")

    if state.recent_priya_turns:
        last3 = state.recent_priya_turns[-3:]
        parts.append(
            f"<DO_NOT_REPEAT_THESE>\n"
            + "\n".join(f"- {t}" for t in last3)
            + "\n</DO_NOT_REPEAT_THESE>"
            "\nYou MUST say something COMPLETELY DIFFERENT from all of the above."
        )

    if state.filler_audit_failing():
        parts.append(f"<nudge>Add filler: {ack_nudge_lang}</nudge>")

    if state.close_armed:
        parts.append(
            f"<CLOSE_NOW>Buying signal detected. Do the close THIS TURN. "
            f"{close_hint}</CLOSE_NOW>"
        )

    phase_hints = {
        Phase.CONNECT: connect_hint,
        Phase.DISCOVER: discover_hint,
        Phase.QUALIFY: qualify_hint,
        Phase.CLOSE: close_hint,
        Phase.EXTENSION: ext_hint,
    }
    hint = phase_hints.get(state.phase)
    if hint:
        parts.append(f"<phase>{hint}</phase>")

    return "\n\n".join(parts)
