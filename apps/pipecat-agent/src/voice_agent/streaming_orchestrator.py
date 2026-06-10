"""Streaming turn orchestrator — LLM tokens flow into sentence-by-sentence TTS.

This replaces run_turn() for the real telephony path. Instead of waiting
for the FULL LLM response before starting TTS, we:

  1. STT (same as before)
  2. Start streaming Gemini + slot extraction in parallel
  3. Accumulate LLM tokens until a sentence boundary (।, ., ?, !)
  4. TTS each sentence independently (phrase cache checked per sentence)
  5. YIELD audio as each sentence completes → Exotel plays immediately

Result: lead hears Priya's first sentence ~1.5s after they stop talking
(vs 8-10s in the sequential orchestrator).

The old run_turn() still works for the local harness and tests. This
module adds a STREAMING alternative consumed by the WS handler.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Mapping, Optional, Protocol

from .conversation_state import ConversationState, Phase, system_prompt_addendum
from .language_state import Lang, LanguageState, STTUtterance, Transition
from .pain_library import pick_pain_hypothesis
from .phrase_cache import PINNED_VOICE_ID, load_or_synthesize_phrase
from .qualification import QualificationSlots, extract_slots
from .prompts import build_system_message, load_priya_prompt
from .sarvam_stt import STTResult as _STTResult


# -- Protocols (same as turn_orchestrator but with streaming LLM) -----------

class STTAdapter(Protocol):
    async def transcribe(self, audio: bytes) -> "STTResultLike": ...


class STTResultLike(Protocol):
    transcript: str
    language_code: str
    confidence: float


class TTSAdapter(Protocol):
    async def synth(self, text: str, lang: str) -> bytes: ...


class StreamingLLMAdapter(Protocol):
    async def stream_respond(
        self, system_message: str, user_message: str
    ) -> AsyncIterator[str]:
        """Yield text chunks as the LLM generates them."""
        ...

    async def extract(self, prompt: str) -> str: ...


class R2Reader(Protocol):
    async def get(self, key: str) -> bytes | None: ...


class R2Writer(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...


# -- Events yielded to the caller ------------------------------------------

@dataclass
class AudioChunkEvent:
    """One sentence of Priya's response, synthesized and ready to play."""
    audio: bytes
    text: str
    sentence_idx: int
    used_cache: bool


@dataclass
class TurnCompleteEvent:
    """Final event — all sentences done, slots extracted."""
    lead_text: str
    lead_lang: str
    lead_confidence: float
    priya_full_text: str
    language_transition: Transition
    slots: QualificationSlots
    latency_ms: dict[str, int]
    total_sentences: int
    cache_hits: int
    end_call: bool = False  # True → WS handler hangs up after audio finishes
    lead_intent: str = "normal"  # classify_lead_intent result, for call logs


StreamEvent = AudioChunkEvent | TurnCompleteEvent


@dataclass
class StreamingDependencies:
    stt: STTAdapter
    tts: TTSAdapter
    llm: StreamingLLMAdapter
    r2_reader: R2Reader
    r2_writer: R2Writer
    voice_id: str = PINNED_VOICE_ID
    # Whole-word substitutions applied to TTS-bound text before sanitise/pace.
    # Sourced from the tenant config so each tenant gets deterministic
    # pronunciation (e.g. "Almmatix" → "All-matix", "Betala" → "Beh-ta-la")
    # instead of relying on the TTS engine's phoneme guesser.
    pronunciation_pack: Mapping[str, str] = field(default_factory=dict)


# -- Sentence splitting ----------------------------------------------------

_SENTENCE_BOUNDARY = re.compile(r'(?<=[।.?!])\s+')

def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_BOUNDARY.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# -- TTS text sanitiser ----------------------------------------------------
#
# The LLM occasionally emits stage directions, parenthetical translations,
# square-bracket markers, or wraps responses in quotes — all of which the
# TTS engine reads aloud verbatim. Observed in production:
#
#   '"Alright sir, so I\'ll get the team to..."'  → speaks the quote marks
#   "Vanakkam sarr (Translation: Hello sir...)"   → speaks "(Translation: ...)"
#   "[switches to Tamil] Vanakkam sarr"           → speaks the bracket bit
#
# Strip these before TTS. Keep the substantive reply.

_PARENS_RE = re.compile(r"\s*[\(\[][^)\]]{0,200}[\)\]]")
_TRANSLATION_PREFIX = re.compile(r"^\s*(translation|note|aside|stage)\s*:\s*", re.I)
_WRAPPING_QUOTES = re.compile(r'^[\'"“”‘’]+|[\'"“”‘’]+$')


def sanitize_for_tts(text: str) -> str:
    """Strip output artifacts the TTS would otherwise speak aloud.

    Removes parenthetical asides (often the LLM glossing its own Tamil into
    English), 'Translation:' / 'Note:' prefixes, and leading/trailing
    quotation marks added by the LLM dressing up its reply.

    Also catches the "I understand you received a recorded message"
    hallucination — when STT garbles a one-word lead reply as "Recorded",
    the LLM infers context and apologises for sending a recording. Replace
    with a gentle re-prompt instead.

    Order matters: trim whitespace BEFORE stripping wrapping quotes, otherwise
    leading/trailing spaces hide the quote chars from the anchored regex.
    """
    if not text:
        return text
    cleaned = _PARENS_RE.sub("", text)
    cleaned = _TRANSLATION_PREFIX.sub("", cleaned)
    cleaned = _WRAPPING_QUOTES.sub("", cleaned.strip()).strip()
    # Hallucination filter — strip the recorded-message apology completely.
    # If the whole reply is just this phrase, swap for a polite re-prompt.
    cleaned = _RECORDED_HALLUCINATION_RE.sub("", cleaned).strip()
    # Strip repetitive "Got it, Laksh." / "Hi Laksh," opening — they sound
    # like a stuck record after the first turn.
    cleaned = _NAME_ECHO_RE.sub("", cleaned).strip()
    # Capitalize first letter after strip
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    if not cleaned:
        cleaned = "Sorry sir, didn't catch that. Are you looking to buy or to rent?"
    return cleaned


# Catches every variant of "I understand/see/think you (have) received/got
# a/the (pre-)recorded message/call" that the LLM produces when STT garbles
# a one-word lead reply ("Recorded" / "Hello" / "Yes"). Drops these
# sentences entirely from the TTS output. Case-insensitive.
_RECORDED_HALLUCINATION_RE = re.compile(
    r"\bI\s+(?:understand|see|think|know|noticed|hear)\s+(?:that\s+)?"
    r"(?:you\s+)?(?:have\s+|just\s+)?(?:received|got|heard)\s+"
    r"(?:a|the|my|our)?\s*(?:pre-?)?recorded\s+(?:message|call|voice|note)\.?",
    re.IGNORECASE,
)

# Strip repetitive "Got it, Laksh." / "Hi Laksh, " prefixes that the LLM
# attaches to every turn. After the intro the lead already knows their name —
# repeating it on every reply makes Priya sound like a broken record. The
# regex catches: "Got it [Name][.,]" / "Hi [Name][.,]" / "Hello [Name][.,]"
# at sentence start, plus "Achha [Name]" / "Haan [Name] ji" (Hindi variants).
_NAME_ECHO_RE = re.compile(
    r"^(?:"
    r"(?:Got it|Hi|Hello|Hey|Okay|Sure|Right|Achha|Haan|Sari|Yes)"
    r"(?:,?\s+[A-Z][a-zA-Z]+)?"
    r"(?:\s+ji)?"
    r"[\.,!\s]+"
    r")+",
    re.IGNORECASE,
)


# -- Tamil pacing pre-processor --------------------------------------------
#
# Sarvam's bulbul ta-IN voice speaks slightly fast and tends to run clauses
# together on the cellular line. The model honours ellipses (...) as a real
# in-line pause but treats a plain comma as a near-zero gap. We pre-process
# Tamil-bound text to force breathing room:
#
#   "Sari sir, indha number ku WhatsApp la quote varum, team call pannuvaanga."
#   → "Sari sir... indha number ku WhatsApp la quote varum... team call pannuvaanga."
#
# Crucial after the opening ack ("Sari sir") which otherwise melts into the
# next clause. We don't touch en-IN / hi-IN — those voices already pace fine.

_TA_COMMA_RE = re.compile(r"\s*,\s+")
_TA_ELLIPSIS_RE = re.compile(r"\.{2,}")
_TA_ACK_RE = re.compile(
    r"^(sari sir|sari|aama sir|aama|enna sir|paarunga sir|paarunga|"
    r"vanakkam sir|hello sir|done sir|ok-aa|okay sir)\b\s*",
    re.IGNORECASE,
)


def pace_for_ta_tts(text: str) -> str:
    """Insert breath pauses suitable for Sarvam Tamil TTS.

    Sarvam's ta-IN voice treats "..." as a real ~300ms pause but treats a
    plain comma as a near-zero gap. To stop clauses melting together on the
    cellular line we:

      1. Force a pause right after the opening ack ("Sari sir, ..." → "Sari sir... ...").
      2. Convert every mid-sentence comma into an ellipsis (clause-boundary pause).
      3. Collapse any over-long ellipsis run to exactly "..." so timing stays predictable.
    """
    if not text:
        return text
    out = text.strip()

    # 1. Pause after opening ack — leading "Sari sir," → "Sari sir... "
    # Only inject the breath when there's a real clause to follow. "Done sir!"
    # alone should stay "Done sir!" — adding "..." before the "!" sounds wrong.
    m = _TA_ACK_RE.match(out)
    if m:
        ack = out[:m.end()].rstrip(", ")
        rest = out[m.end():].lstrip(", ")
        if rest and re.match(r"[A-Za-z]", rest):
            out = f"{ack}... {rest}"
        elif rest:
            # rest is just trailing punctuation like "!" — keep tight, no space.
            out = f"{ack}{rest}"
        else:
            out = ack

    # 2. Mid-sentence commas → ellipses (clause-boundary pause).
    out = _TA_COMMA_RE.sub("... ", out)

    # 3. Normalise any "..." run (2+ dots) to exactly "...".
    out = _TA_ELLIPSIS_RE.sub("...", out)

    # 4. Collapse any whitespace runs caused by the substitutions.
    out = re.sub(r"\s+", " ", out).strip()
    return out


_PACK_PATTERN_CACHE: dict[int, re.Pattern[str]] = {}


def apply_pronunciation_pack(
    text: str, pack: Mapping[str, str] | None
) -> str:
    """Whole-word substitute pronunciation_pack entries into TTS-bound text.

    Word-boundary anchored so "demo" won't replace "demolish". Longer keys
    win on overlap (sorted by length desc) so "Laksh Betala" beats "Laksh".
    Pattern compilation is cached per pack object so we don't rebuild the
    regex on every sentence.
    """
    if not text or not pack:
        return text
    key = id(pack)
    patt = _PACK_PATTERN_CACHE.get(key)
    if patt is None:
        escaped = sorted(
            (re.escape(k) for k in pack.keys() if k), key=len, reverse=True
        )
        if not escaped:
            return text
        patt = re.compile(r"\b(?:" + "|".join(escaped) + r")\b")
        _PACK_PATTERN_CACHE[key] = patt
    return patt.sub(lambda m: pack[m.group(0)], text)


def prepare_for_tts(
    text: str,
    lang: str,
    pack: Mapping[str, str] | None = None,
) -> str:
    """Sanitiser + pronunciation pack + per-language pacing.

    Single entry point for TTS-bound text. Pack substitution runs *before*
    pacing so Tamil ellipsis insertion sees the final spelling, and it
    runs *above* the phrase cache so each substituted form gets its own
    cache entry (correct — different audio per tenant pronunciation).
    """
    cleaned = sanitize_for_tts(text)
    if not cleaned:
        return cleaned
    if pack:
        cleaned = apply_pronunciation_pack(cleaned, pack)
    if lang == "ta-IN":
        cleaned = pace_for_ta_tts(cleaned)
    return cleaned


def prepare_intro_for_tts(
    text: str,
    lang: str,
    pack: Mapping[str, str] | None = None,
) -> str:
    """Prepare the OPENING line for TTS.

    Critical difference from prepare_for_tts: the intro is the one place we
    deliberately say the lead's name and the company name, so we MUST NOT run
    the per-turn reply sanitiser — its name-echo stripper would delete the
    leading "Hi Laksh," / "Namaste Laksh ji" and the whole greeting collapses.

    Historically the intro was synthesised from RAW template text and never
    saw the pronunciation pack at all — which is exactly why "XYZ Broker" came
    out of the TTS garbled on every call ("Hi XYZ is not pronounced"). The
    pack maps it to "Eks Why Zee Broker"; we apply that here, plus the Tamil
    breath-pacing pass, and nothing else.
    """
    if not text:
        return text
    out = text.strip()
    if pack:
        out = apply_pronunciation_pack(out, pack)
    if lang == "ta-IN":
        out = pace_for_ta_tts(out)
    return out


# -- Main streaming entry point ---------------------------------------------

async def run_turn_streaming(
    *,
    ctx,  # CallContext
    audio_in: bytes,
    deps: StreamingDependencies,
    prior_slots: QualificationSlots,
) -> AsyncIterator[StreamEvent]:
    """Stream audio chunks as LLM generates sentences.

    Yields AudioChunkEvent per sentence, then one final TurnCompleteEvent.
    The Exotel WS handler plays each AudioChunkEvent immediately.
    """
    timings: dict[str, int] = {}
    t0 = time.monotonic()

    # ---- 1. STT -----------------------------------
    stt_t0 = time.monotonic()
    stt_result = await deps.stt.transcribe(audio_in)
    timings["stt_ms"] = int((time.monotonic() - stt_t0) * 1000)

    raw_transcript = (stt_result.transcript or "").strip()

    is_echo = False
    if raw_transcript and ctx.conversation_state.recent_priya_turns:
        for prev in ctx.conversation_state.recent_priya_turns[-3:]:
            overlap = _text_overlap(raw_transcript, prev)
            if overlap > 0.4:
                is_echo = True
                break

    if not raw_transcript or is_echo:
        stt_result = _STTResult(
            transcript="(silence)",
            language_code=stt_result.language_code or "hi-IN",
            confidence=0.0,
            request_id=getattr(stt_result, 'request_id', ''),
        )

    # ---- 2. Language + Phase -------------------------------------------
    lang = _coerce_lang(stt_result.language_code)
    transition = ctx.language_state.update(
        STTUtterance(
            text=stt_result.transcript,
            lang=lang,
            confidence=stt_result.confidence,
        )
    )
    ctx.conversation_state.advance_phase_if_due(
        elapsed_sec=ctx.elapsed(),
        buying_confidence=prior_slots.buying_confidence,
    )

    # ---- 3. Language flip — no bridge phrase, just switch silently ------

    # ---- 4. Build system message (same as sequential) ------------------
    base_prompt = _cached_prompt(ctx.industry_key)
    system_msg = build_system_message(
        base_prompt=base_prompt,
        current_language=transition.current_language.value,
        lead_first_name=ctx.lead_first_name,
        lead_company=ctx.lead_company,
    )
    system_msg += "\n\n" + system_prompt_addendum(
        ctx.conversation_state, language=transition.current_language.value
    )

    pain = _pain_hypothesis_for_turn(ctx, prior_slots, transition.current_language.value)
    if pain:
        system_msg += f"\n\n<pain_hypothesis>{pain}</pain_hypothesis>"

    context_summary = _build_context_summary(prior_slots, ctx)
    if context_summary:
        system_msg += f"\n\n<call_context>{context_summary}</call_context>"

    intent = classify_lead_intent(stt_result.transcript, ctx.conversation_state)
    if intent == "reject":
        ctx.conversation_state.reject_count += 1
    elif intent == "offtopic":
        ctx.conversation_state.off_topic_count += 1
    elif intent == "backchannel":
        ctx.conversation_state.backchannel_count += 1
    elif intent == "normal":
        ctx.conversation_state.backchannel_count = 0

    # Sales brain — decide whether to keep digging, close, or exit warmly.
    #
    #   "buying-ready" = lead has given us at least one hard requirement
    #   AND surfaced a pain point. That's enough to qualify; further
    #   discovery is overkill, hand it to the human team via the close.
    #
    #   "unproductive" = lead is on-topic but giving nothing back (short
    #   utterance, no slot info). After 3 of those in a row we exit
    #   politely. This prevents Call-1-style 371s dead-end conversations.
    has_pain = bool(prior_slots.pain_point)
    has_timeline = prior_slots.timeline_days is not None
    has_volume = prior_slots.volume_monthly_kg is not None
    has_supplier_complaint = bool(prior_slots.current_supplier) and has_pain
    is_buying_ready = has_pain and (has_timeline or has_volume or has_supplier_complaint)
    if is_buying_ready:
        ctx.conversation_state.close_armed = True

    if intent == "normal":
        word_count = len(stt_result.transcript.split()) if stt_result.transcript else 0
        produced_info = (
            prior_slots.product_interest
            or prior_slots.volume_monthly_kg
            or prior_slots.pain_point
            or prior_slots.current_supplier
            or (prior_slots.timeline_days is not None)
        )
        # Cheap text-level signal: if the lead's reply contains an industry
        # word (pharma, paints, plastics, etc. — or Tamil/Hindi script
        # equivalents), it's NOT unproductive even if the slot extractor
        # hasn't run yet. This protects warm-but-terse leads who say
        # "ஃபார்மாவில் இருக்கேன்" / "pharma mein hai" — true info,
        # but only 2-3 space-separated tokens.
        if not produced_info and _mentions_industry(stt_result.transcript):
            produced_info = True

        if word_count < 6 and not produced_info:
            ctx.conversation_state.unproductive_turn_count += 1
        else:
            ctx.conversation_state.unproductive_turn_count = 0

    end_call = should_end_call(intent, ctx.conversation_state)

    # Record what the lead actually said BEFORE formatting the user message —
    # the formatter uses recent_lead_turns to remind the LLM of past answers
    # so it stops re-asking already-answered questions. Skip pure silence /
    # backchannels which add nothing and crowd the window.
    if intent not in ("silence", "backchannel") and stt_result.transcript != "(silence)":
        ctx.conversation_state.record_lead_turn(stt_result.transcript)

    user_msg = _format_user_message(
        stt_result.transcript, prior_slots, ctx.conversation_state,
        lang=transition.current_language.value, intent=intent,
    )

    # ---- 5. Start streaming LLM + slot extraction in parallel ----------
    llm_t0 = time.monotonic()
    slots_task = asyncio.create_task(
        extract_slots(
            transcript=[
                {"speaker": "lead", "text": stt_result.transcript},
                *_recent_priya_turns_as_transcript(ctx.conversation_state),
            ],
            prior_slots=prior_slots,
            llm=deps.llm.extract,
        )
    )

    # Accumulate LLM tokens, split by sentence, TTS + yield each sentence.
    # HARD CAP: only the first MAX_SENTENCES_PER_TURN sentences are spoken;
    # anything the LLM generates after that is silently dropped. The prompt
    # asks for <=2 sentences but the LLM regularly produces 4-5 — this code
    # cap is the only thing that reliably enforces brevity on the line.
    MAX_SENTENCES_PER_TURN = 2

    sentence_buffer = ""
    full_text_parts: list[str] = []
    sentence_idx = 0
    cache_hits = 0
    first_sentence_done = False
    cap_reached = False

    async for chunk in deps.llm.stream_respond(system_msg, user_msg):
        if cap_reached:
            break  # stop consuming LLM tokens once cap hit
        sentence_buffer += chunk

        # Check for sentence boundary
        sentences = split_sentences(sentence_buffer)
        if len(sentences) > 1:
            # All but last are complete sentences → TTS + yield
            for complete_sentence in sentences[:-1]:
                if sentence_idx >= MAX_SENTENCES_PER_TURN:
                    cap_reached = True
                    break
                spoken = prepare_for_tts(
                    complete_sentence,
                    transition.current_language.value,
                    deps.pronunciation_pack,
                )
                if not spoken:
                    continue  # whole sentence was an aside / stage marker
                if not first_sentence_done:
                    timings["llm_first_sentence_ms"] = int(
                        (time.monotonic() - llm_t0) * 1000
                    )
                    first_sentence_done = True

                tts_t0 = time.monotonic()
                phrase_result = await load_or_synthesize_phrase(
                    text=spoken,
                    lang=transition.current_language.value,
                    r2_reader=deps.r2_reader,
                    r2_writer=deps.r2_writer,
                    synthesize=lambda t, l: deps.tts.synth(t, l),
                    voice_id=deps.voice_id,
                )
                if sentence_idx == 0:
                    timings["tts_first_sentence_ms"] = int(
                        (time.monotonic() - tts_t0) * 1000
                    )
                if phrase_result.used_cache:
                    cache_hits += 1

                full_text_parts.append(spoken)
                yield AudioChunkEvent(
                    audio=phrase_result.audio,
                    text=spoken,
                    sentence_idx=sentence_idx,
                    used_cache=phrase_result.used_cache,
                )
                sentence_idx += 1

            sentence_buffer = sentences[-1]  # keep incomplete tail

    # Flush remaining buffer (skipped if cap already reached)
    tail = prepare_for_tts(
        sentence_buffer.strip(),
        transition.current_language.value,
        deps.pronunciation_pack,
    )
    if tail and sentence_idx < MAX_SENTENCES_PER_TURN:
        if not first_sentence_done:
            timings["llm_first_sentence_ms"] = int(
                (time.monotonic() - llm_t0) * 1000
            )
        tts_t0 = time.monotonic()
        phrase_result = await load_or_synthesize_phrase(
            text=tail,
            lang=transition.current_language.value,
            r2_reader=deps.r2_reader,
            r2_writer=deps.r2_writer,
            synthesize=lambda t, l: deps.tts.synth(t, l),
            voice_id=deps.voice_id,
        )
        if sentence_idx == 0:
            timings["tts_first_sentence_ms"] = int(
                (time.monotonic() - tts_t0) * 1000
            )
        if phrase_result.used_cache:
            cache_hits += 1

        full_text_parts.append(tail)
        yield AudioChunkEvent(
            audio=phrase_result.audio,
            text=tail,
            sentence_idx=sentence_idx,
            used_cache=phrase_result.used_cache,
        )
        sentence_idx += 1

    timings["llm_ms"] = int((time.monotonic() - llm_t0) * 1000)

    # ---- 6. Wait for slot extraction -----------------------------------
    new_slots = await slots_task

    # ---- 7. Update conversation state ----------------------------------
    priya_full = " ".join(full_text_parts)
    ctx.conversation_state.record_priya_turn(priya_full)
    ctx.phrase_cache_hits += cache_hits
    ctx.turn_idx += 1

    timings["total_ms"] = int((time.monotonic() - t0) * 1000)

    yield TurnCompleteEvent(
        lead_text=stt_result.transcript,
        lead_lang=transition.current_language.value,
        lead_confidence=stt_result.confidence,
        priya_full_text=priya_full,
        language_transition=transition,
        slots=new_slots,
        latency_ms=timings,
        total_sentences=sentence_idx,
        cache_hits=cache_hits,
        end_call=end_call,
        lead_intent=intent,
    )


# -- Helpers (same as turn_orchestrator) ------------------------------------

def _cached_prompt(industry_key: str = "real_estate") -> str:
    """Per-industry base prompt. load_priya_prompt() does the caching."""
    return load_priya_prompt(industry_key)


_INDIC_SCRIPT_RE = re.compile(
    # Devanagari, Bengali, Gujarati, Tamil, Telugu, Kannada, Malayalam, Odia, Gurmukhi
    r"[ऀ-ॿঀ-৿઀-૿஀-௿ఀ-౿"
    r"ಀ-೿ഀ-ൿ଀-୿਀-੿]"
)


# Industry/sector words that count as "produced info" even when the lead
# reply is otherwise terse. Lowercase ASCII matches romanized speech and
# English; the unicode patterns catch native-script mentions ("ஃபார்மா").
# Keep these high-signal — don't add common verbs/adjectives.
_INDUSTRY_ASCII = frozenset({
    "pharma", "pharmaceutical", "pharmaceuticals", "paint", "paints",
    "coating", "coatings", "adhesive", "adhesives", "plastic", "plastics",
    "polymer", "polymers", "rubber", "textile", "textiles", "leather",
    "automotive", "auto", "food", "beverage", "beverages", "cosmetic",
    "cosmetics", "detergent", "detergents", "cleaning", "construction",
    "agro", "agri", "agriculture", "fertilizer", "fertilizers", "ink",
    "inks", "printing", "packaging", "lubricant", "lubricants",
    "petrochemical", "petrochemicals", "chemical", "chemicals", "soap",
    "personal care", "homecare", "industrial", "manufacturing",
})
_INDUSTRY_SCRIPT_RE = re.compile(
    r"ஃபார்மா|ஃபார்ம|பெயிண்|பெயின்ட|ப்ளாஸ்டிக|ரப்பர|"  # Tamil
    r"फार्मा|पेंट|प्लास्टिक|रबर|कोटिंग|"  # Hindi
    r"फार्मा|पेंट"
)


def _mentions_industry(text: str | None) -> bool:
    """True when the lead's transcript names an industry/sector — useful
    "produced info" signal for the unproductive-turn counter even when the
    LLM slot extractor hasn't run yet."""
    if not text:
        return False
    lower = text.lower()
    for token in _INDUSTRY_ASCII:
        if token in lower:
            return True
    if _INDUSTRY_SCRIPT_RE.search(text):
        return True
    return False


def _looks_like_line_noise(text: str, *, lang: str) -> bool:
    """Heuristic: STT output that's almost certainly garbled audio rather
    than a real lead utterance. Common in production:
      - Indic script chars while lead has been speaking English consistently
      - Very short noise tokens with no Latin/business words
    Used so we re-prompt politely instead of quoting the gibberish back."""
    t = (text or "").strip()
    if not t:
        return True
    # English call + Indic script chars → STT misfire (Bengali/Gujarati/Hindi
    # in an EN conversation are tell-tale signs Sarvam guessed wrong on
    # background noise).
    if lang == "en-IN" and _INDIC_SCRIPT_RE.search(t):
        return True
    # Very short utterance with no alphanumeric content
    if len(t) < 4 and not any(c.isalnum() for c in t):
        return True
    return False


def _text_overlap(a: str, b: str) -> float:
    """Fraction of words in `a` that also appear in `b`. Used for echo detection."""
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def _build_context_summary(slots, ctx) -> str:
    """Build a running summary of what's known so far. Prevents re-asking."""
    parts = []
    if slots.product_interest:
        parts.append(f"Products discussed: {slots.product_interest}")
    if slots.volume_monthly_kg and slots.volume_monthly_kg > 0:
        parts.append(f"Volume: {slots.volume_monthly_kg} kg/month")
    if slots.current_supplier:
        parts.append(f"Current supplier: {slots.current_supplier}")
    if slots.pain_point:
        parts.append(f"Pain: {slots.pain_point}")
    if slots.decision_role:
        parts.append(f"Role: {slots.decision_role}")
    contact = slots.slot_confidence.get("contact_info")
    if contact:
        parts.append(f"Contact captured: yes")
    if parts:
        parts.append("DO NOT re-ask anything already captured above.")
    return " | ".join(parts) if parts else ""


def _coerce_lang(code: str) -> Lang | None:
    try:
        return Lang(code)
    except ValueError:
        return None


def _pain_hypothesis_for_turn(ctx, slots, lang: str) -> Optional[str]:
    if ctx.conversation_state.phase != Phase.DISCOVER:
        return None
    try:
        lang_enum = Lang(lang)
    except ValueError:
        return None
    return pick_pain_hypothesis(
        product_interest=slots.product_interest,
        lang=lang_enum,
        turn_idx=ctx.turn_idx,
    )


_CLOSE_WORDS = [
    # Send-it-on-WhatsApp (Hindi)
    "bhej do", "bhej de", "bhej dena", "bhej dijiye",
    "send karo", "send kar do", "send kar dena",
    "whatsapp karo", "whatsapp pe bhej", "whatsapp bhej",
    "quote bhejo", "quote bhej do",
    # Send-it-on-WhatsApp (Tamil)
    "anuppunga", "anuppu", "send pannunga", "whatsapp la anuppu",
    "whatsapp la anuppunga", "quote anuppunga",
    # Done / English bye
    "okay done", "ok done", "kar dijiye", "kar dena",
    "bye", "bye bye", "good bye", "goodbye", "see you",
    "thank you", "thanks", "thank you bye", "thanks bye",
    "alright then", "alright bye", "ok bye", "okay bye",
    "ok thanks", "ok thank you", "good day", "have a good day",
    # I'll-look-into-it (Hindi)
    "dekh leta", "dekh lunga", "dekhta hoon", "dekhti hoon",
    "rakh leta", "rakh lunga", "phone rakhta", "phone rakhti",
    "theek hai bye", "theek hai thanks", "theek hai done", "theek hai bhej",
    # Enough / I'm leaving (Tamil — these were missed in the test call)
    "podhum", "podhumda", "podhumaa", "podhumaachu", "podhum sarr",
    "podhum sir", "podhum madam", "podhum mam", "podhum mem",
    "ippo podhum", "ippa podhum",
    "vidunga", "vidu", "vittu vidu", "vittu vidunga",
    "varen", "vaaren", "naa varen", "naan vaaren",
    "vechirukken", "vechikko",
    "vendaam sarr", "vendam sarr", "vendam sir",
    "namaskaram", "vanakkam sarr bye",
    # I'll-go-now / let-it-go (Tamil + Malayalam observed in call)
    "ippo poren", "appuram pesalam", "pesalam aprm", "later pesalam",
    "podhum madam", "ippam pottu", "pottu vidu", "pottu vidunga",
    "let it go", "let go", "leave it",
    # Drop-it / never mind
    "rehne do", "chodo", "chod do", "chhod do", "chhodo",
    "skip karo", "skip kar do",
]
_REJECT_WORDS = [
    "not interested", "interested nahi", "nahi chahiye", "nahin chahiye",
    "zaroorat nahi", "zarurat nahi", "zaroorat nahin", "mat karo",
    "band karo", "interest nahi", "call mat", "pareshan mat",
    # Tamil rejections (these were missed — lead told us pronunciation was bad
    # and we treated it as a normal turn instead of a reject)
    "venam", "vendam", "vendaam", "thevai illa", "thevai illai",
    "puriyala mam", "puriyalai mam", "puriyala madam",
    "tamil pesala", "tamilil pesala", "tamil-la pesala",
    "tamil correct illa", "tamil illa",
    "konjam kashtam", "konjam problem",
    "kathru kathukka", "kathru kollunga",  # "go learn first"
    "sari mam", "sorry mam", "sorry sarr",  # apologetic-end
]
# Clearly wrong person / wrong number → end politely, no probe.
_WRONG_WORDS = [
    "galat number", "wrong number", "kaun bol", "kaun hai", "personal call",
]
# Off-topic / not a business prospect → probe ONCE for a real requirement,
# then end. ("can't sell chemicals to a tiger" — but try first.)
_OFFTOPIC_WORDS = [
    "student", "padhta", "padhai", "college", "school",
    "pizza", "khana", "biryani", "time pass", "timepass", "bored",
]
_ABUSE_WORDS = [
    "chutiya", "bhosdi", "madarchod", "behenchod", "gaand", "lavda",
    "randi", "harami", "kutte", "saala kutta", "fuck", "bastard",
]
# Lead didn't catch what Priya said — she should REPHRASE, not parrot.
# Covers Hindi, Tamil, English, and code-mix re-ask phrases. Checked BEFORE
# close/normal so a clarification request never gets read as agreement.
_CLARIFY_WORDS = [
    # English
    "didn't get", "didnt get", "did not get", "couldn't hear", "couldnt hear",
    "could not hear", "say again", "come again", "what was that", "what did you say",
    "pardon", "repeat please", "please repeat", "one more time", "again sir",
    "sorry sir", "sorry didn't", "sorry didnt",
    # Hindi
    "phir se", "phir bolo", "phir boliye", "dobara", "dubara", "kya bola",
    "kya kaha", "kya kaha sir", "samajh nahi", "samjha nahi", "samjhi nahi",
    "nahi suna", "nahi sunai", "suna nahi", "sunai nahi",
    "thoda dheere", "dheere boliye", "aaram se boliye",
    # Tamil / Tanglish
    "enna sonninga", "enna sonneenga", "enna sonneenge", "enna sonnel",
    "puriyala", "puriyalai", "puriyale", "kekkala", "kekkalai",
    "thirumba sollunga", "thirumba sollu", "innum oru thadava",
    "konjam meadhu", "meadhu sollunga", "slow ah sollunga",
]


# Pure acknowledgment tokens — the lead is listening, not answering.
_BACKCHANNEL_TOKENS: frozenset[str] = frozenset({
    "acha", "achha", "accha", "achchha", "haan", "han", "haa", "hmm", "hm",
    "mm", "mmm", "ok", "okay", "okk", "theek", "thik", "sahi", "right",
    "ji", "sari", "seri", "aama", "yes", "yeah", "yep", "bilkul", "sun",
    "suno", "hmmm", "achaa",
})
# Harmless connectors allowed alongside an ack without changing the meaning
# ("theek hai", "haan ji", "haan boliye", "ok sir").
_BACKCHANNEL_CONNECTORS: frozenset[str] = frozenset({
    "hai", "ji", "haan", "na", "to", "sir", "madam", "boliye", "bolo",
    "kahiye", "batao", "bataiye",
})


def _is_backchannel(text: str) -> bool:
    """True when a SHORT utterance is only acknowledgment ("acha", "haan haan",
    "theek hai", "ok ji") — the lead is passively listening, not answering and
    not asking to close. Anything with real content (e.g. "theek hai bhej do")
    is NOT a backchannel."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = cleaned.split()
    if not words or len(words) > 4:
        return False
    if not all(w in _BACKCHANNEL_TOKENS or w in _BACKCHANNEL_CONNECTORS for w in words):
        return False
    return any(w in _BACKCHANNEL_TOKENS for w in words)


def classify_lead_intent(lead_text: str, conv) -> str:
    """Coarse intent for end-of-call decisions. One of:
    silence | backchannel | close | reject | wrong | abuse | offtopic | normal.
    """
    t = lead_text.lower().strip()
    if not t or "silence" in t:
        return "silence"
    if any(w in t for w in _ABUSE_WORDS):
        return "abuse"
    # Check backchannel BEFORE close: a lone "theek hai"/"ok"/"acha" is the lead
    # listening, NOT asking to end the call. (Bug fix: these used to hang up.)
    if _is_backchannel(t):
        return "backchannel"
    # Check close BEFORE clarify: "okay bye thanks" should hang up even though
    # "ok" and "thanks" can read as soft acks. Close cues are decisive.
    if any(w in t for w in _CLOSE_WORDS):
        return "close"
    # Check reject BEFORE clarify when the utterance is "long": when a lead
    # MONOLOGUES about how bad Tamil pronunciation is and also says "puriyala",
    # the dominant signal is reject (they want out), not "please rephrase".
    # Short utterances containing clarify markers stay clarify (a real re-ask).
    word_count = len([w for w in t.split() if w])
    has_reject = any(w in t for w in _REJECT_WORDS)
    if has_reject and word_count >= 6:
        return "reject"
    if any(w in t for w in _CLARIFY_WORDS):
        return "clarify"
    if any(w in t for w in _OFFTOPIC_WORDS):
        return "offtopic"
    if any(w in t for w in _REJECT_WORDS):
        return "reject"
    if any(w in t for w in _WRONG_WORDS):
        return "wrong"
    return "normal"


def should_end_call(intent: str, conv) -> bool:
    """Decide whether Priya hangs up after this turn.

    We give the lead a chance before ending: a rejection first gets a
    referral ask, an off-topic turn first gets one requirement probe.
    """
    if intent in ("close", "abuse", "wrong"):
        return True
    if intent == "reject" and conv.reject_count >= 2:
        return True
    if intent == "offtopic" and conv.off_topic_count >= 2:
        return True
    if conv.should_force_end():
        return True
    return False


def _format_user_message(lead_text, slots, conv, *, lang: str = "hi-IN", intent: str = "normal"):
    turn = len(conv.recent_priya_turns)
    is_silence = intent == "silence"

    # CLOSE NUDGES — two levels, neither dictates a canned "booked" line.
    # The old version force-injected a verbatim "Saturday 11 AM reserved"
    # confirmation after just 2 turns, regardless of what the lead said —
    # Priya repeated it word-for-word every turn while leads asked "who are
    # you?" (calls 7301f7a0, 40ec03f3). A close is PROPOSED as a question;
    # only the lead's yes books it.
    lead_lc = (lead_text or "").lower()
    _VISIT_ASK_KEYWORDS = (
        "site visit", "site-visit", "schedule a visit", "schedule visit",
        "book a visit", "book visit", "appointment", "visit kab",
        "visit kar", "kab visit", "visit ke liye",
        "visit la", "site la", "site varuven", "site varum",
        "visit aanaa", "visit panna", "appointment podu",
    )
    lead_wants_visit = any(k in lead_lc for k in _VISIT_ASK_KEYWORDS)
    # After several lead turns, nudge toward the slot — but only if the
    # conversation has actually produced a requirement to book against.
    nudge_close = turn >= 4 and intent in ("normal", "backchannel")
    # Lead is calling out repetition / time-waste. Call 3ec7c49d melted down
    # because Priya answered each complaint with ANOTHER apology + restatement.
    _FRUSTRATION_KEYWORDS = (
        "repeat kyu", "kyu repeat", "repeat kyon", "kyon repeat", "baar baar",
        "time waste", "टाइम वेस्ट", "रिपीट", "wahi cheez", "dimag", "दिमाग",
        "bore", "irritate", "pareshaan kar", "same thing again",
        "repeating the same", "rakh raha", "rakh deta", "रख दो", "रख रहा",
        "phone vai", "vei da", "madhupadi", "thirupi thirupi",
    )
    lead_frustrated = any(k in lead_lc or k in (lead_text or "") for k in _FRUSTRATION_KEYWORDS)

    parts = [
        '[ROMAN SCRIPT ONLY. No Devanagari. No Tamil script.]',
        # Anti-parrot — the #1 complaint from live calls. "Acknowledge" means
        # 2-4 words, NEVER a restatement of what the lead just told you.
        '[NEVER restate or summarise the lead\'s words back to them '
        '("aap rent pe dekh rahe hain...", "aapko lagta hai ki..."). They '
        'KNOW what they said. Ack in 2-4 words max ("Achha sir" / "Sari sir" '
        '/ "Got it"), then ANSWER their question or ask the next NEW thing. '
        'Every reply must END with a question or a concrete next step — '
        'never with an observation.]',
    ]

    if turn == 0:
        parts.append('[Intro DONE. Do not introduce yourself.]')

    # ROLLING TRANSCRIPT — the context fix. Before this, the LLM saw only the
    # lead's CURRENT sentence + Priya's single last line; everything the lead
    # said earlier ("rent pe dekh raha hoon", "Anna Nagar side") vanished, so
    # the model re-asked answered questions and asked crore-budget to a rent
    # lead (call 3ec7c49d). record_lead_turn() runs before this formatter, so
    # the current utterance is the LAST entry — exclude it from history.
    lead_hist = conv.recent_lead_turns[:-1] if conv.recent_lead_turns else []
    priya_hist = list(conv.recent_priya_turns)
    if lead_hist:
        lines = []
        # Interleave oldest-first. Priya replies follow lead turns 1:1 in the
        # normal flow; mismatched lengths just truncate to the shorter side.
        offset = len(priya_hist) - len(lead_hist)
        for i, lt in enumerate(lead_hist):
            lines.append(f"Lead: {lt}")
            pi = i + offset
            if 0 <= pi < len(priya_hist):
                lines.append(f"You: {priya_hist[pi]}")
        parts.append(
            "[CONVERSATION SO FAR — the lead already told you this. NEVER "
            "re-ask anything answered below; build on it.]\n" + "\n".join(lines[-12:])
        )

    last_priya = conv.recent_priya_turns[-1] if conv.recent_priya_turns else ""
    if lang == "ta-IN":
        # Strong pin + pronunciation guard: examples in the system prompt skew
        # Hindi so the LLM drifts back. Also forbid the stilted slang forms
        # (sariyaa / sarr / paesalaam / kandipaa) — the Tamil TTS over-stresses
        # them and listeners complained.
        parts.append(
            '[TANGLISH ONLY. Tamil grammar + English business words. '
            'ZERO Hindi words — no "achha", "bilkul", "haan ji", "theek hai", '
            '"karenge", "kijiye", "dijiye", "boliye", "bataiye". '
            'USE THESE clean forms: sir (NOT sarr), sari (NOT sariyaa), '
            'irukku (NOT iruku), tharen (NOT thaaren), pannuren (NOT panren), '
            'pesalam (NOT paesalaam), kandippa (NOT kandipaa), evlo (NOT yevalavu), '
            'rate (NOT raate-uh), quote (NOT kot), delivery (NOT delivary), '
            'WhatsApp (NOT watts-aap). Always insert a comma after the opening '
            'ack. Open ONLY with "Vanakkam sir" or "Hello sir" — never "Vaanga '
            'sir" (vaanga = welcome in; wrong on outbound). Stay in Tamil.]'
        )
        if last_priya:
            parts.append(f'[Your last reply (Tamil): "{last_priya}"]')
    elif lang == "en-IN":
        parts.append(
            '[ENGLISH. Indian-cadence English ONLY. ZERO Hindi words. '
            'ZERO Tamil words. Do NOT mix languages. If lead replied in '
            'Hindi/Tamil but state is still en-IN, keep replying English — '
            'lead will trigger an explicit switch when ready.]'
        )
        if last_priya:
            parts.append(f'[Your last reply (English): "{last_priya}"]')
    else:
        parts.append(
            '[HINDI in ROMAN LETTERS ONLY — "Bilkul sir, budget kya hai?" '
            'NEVER Devanagari script (the voice layer cannot pace it). '
            'ZERO English sentences. Only use English for property nouns '
            '(BHK, sqft, lakh, crore, area names). NEVER reply "Got it, '
            'sir" or "Sure, so you want..." — those are English sentences. '
            'Reply structure: 2-4 word Hindi ack → one short Hindi '
            'question. No Tamil grammar (no "irukku", "tharen", "panren").]'
        )
        if last_priya:
            parts.append(f'[Your last reply (Hindi): "{last_priya}"]')

    if is_silence:
        # Language-aware silence prompt — say it in whatever the lead's
        # current language is. Previously hardcoded Hindi, which broke
        # English calls (lead heard random Hindi mid-EN conversation).
        if lang == "ta-IN":
            parts.append('Lead silent. Ask once gently: "Sir, line clear-aa keka mudiyutha?"')
        elif lang == "en-IN":
            parts.append('Lead silent. Ask once gently: "Sir, are you there? Can you hear me?"')
        else:
            parts.append('Lead silent. Ask once gently: "Sir, sun pa rahe hain?"')
        return "\n".join(parts)

    parts.append(f'Lead: "{lead_text}"')

    # Frustrated lead beats everything except silence/garble: stop the
    # apology-restatement loop and deliver value in ONE line, or wrap up.
    if lead_frustrated:
        parts.append(
            '[LEAD IS FRUSTRATED — they feel you are repeating / wasting '
            'time. Do NOT apologise at length. Do NOT restate anything. '
            'ONE short line that goes STRAIGHT to the concrete next step '
            'using what you already know: e.g. "Sir seedha point pe aati '
            'hoon — [their locality] mein [their BHK] ke options abhi '
            'WhatsApp pe bhej rahi hoon. Visit ke liye weekend mein time '
            'milega?" If they have ALREADY complained before this, or they '
            'said to hang up: thank them in one line and END the call '
            'gracefully instead.]'
        )
        return "\n".join(parts)

    # Close nudges. Never a verbatim script, never a fait-accompli booking —
    # the LLM composes the words, responds to what the lead JUST said, and
    # proposes the slot as a question the lead can say yes to.
    if lead_wants_visit:
        parts.append(
            '[LEAD ASKED FOR A VISIT — close now. First acknowledge what they '
            'just said in their words. Then offer a CHOICE of two specific '
            'slots (e.g. Saturday morning vs Sunday morning) as a QUESTION. '
            'Confirm only AFTER they pick one — then repeat day + time + '
            'locality back, say the address comes on this WhatsApp number, '
            'and stop. Never say a visit is already reserved before they '
            'choose. Speak AS the brokerage — "I/we/our team" — never refer '
            'to "the broker" as a third person.]'
        )
        return "\n".join(parts)
    if nudge_close:
        parts.append(
            '[TIME TO MOVE TOWARD THE SLOT — but earn it. First respond to '
            'what the lead just said. If you already know their intent '
            '(buy/rent) AND a locality/requirement: propose a visit slot as a '
            'CHOICE of two options, as a question. If you do NOT yet know '
            'those, ask the single most important missing question instead '
            '(locality first, then BHK, then budget). NEVER announce a '
            'booking the lead has not said yes to.]'
        )
        return "\n".join(parts)

    if intent == "backchannel":
        if conv.backchannel_count >= 2:
            parts.append(
                'Lead is just listening passively (only said "' + lead_text.strip()
                + '"), not answering. STOP explaining. Ask ONE short, direct question to '
                'pull them in — e.g. aapka budget kya hai, ya kitne BHK chahiye, ya kis '
                'locality mein dekh rahe hain. Do NOT repeat your previous question.'
            )
        else:
            parts.append(
                'Lead is acknowledging (listening), NOT answering and NOT closing. '
                'Do NOT repeat your last question. Move FORWARD: add ONE new useful point '
                'or ask the NEXT short question.'
            )
        return "\n".join(parts)

    if intent == "clarify":
        last_priya = conv.recent_priya_turns[-1] if conv.recent_priya_turns else ""
        # When the STT is garbled (e.g. Indic script mid-English conversation,
        # or just 1-3 chars of nonsense), the lead almost certainly had bad
        # audio — not a comprehension issue. Don't try to rephrase a whole
        # sales line at them; just ask them to repeat once.
        garbled = (
            len(lead_text.strip()) < 6
            or _looks_like_line_noise(lead_text, lang=lang)
        )
        if garbled:
            if lang == "ta-IN":
                reprompt = "Sir, line clear-aa keka mudiyala, konjam meadhuva sollunga sir?"
            elif lang == "en-IN":
                reprompt = "Sorry sir, line wasn't clear — could you say that one more time?"
            else:
                reprompt = "Sir, line clear nahin aa rahi — ek baar phir bolen?"
            parts.append(
                f'[GARBLED audio — do NOT quote the lead\'s STT back. '
                f'Do NOT rephrase your last line. Say EXACTLY: "{reprompt}"]'
            )
            return "\n".join(parts)

        parts.append(
            f'Lead did NOT catch you. Your last line was: "{last_priya}". '
            'REPHRASE that idea — DO NOT repeat it verbatim. '
            'Use simpler/shorter words, add a "..." pause, spell tricky terms '
            'phonetically — keep budget/BHK/locality/visit/calendar as plain English. '
            'Drop one detail if packed. Stay in the SAME language the lead used. '
            'One short sentence, then a question if natural. NEVER copy your '
            'previous sentence word-for-word. NEVER quote the lead\'s words back '
            'at them as "could you elaborate on X" — that\'s humiliating on a phone call.'
        )
        return "\n".join(parts)

    if intent == "close":
        if lang == "ta-IN":
            parts.append('Lead wants to CLOSE. Say ONLY: "Sari sir, indha number ku WhatsApp la property details + site visit slot anuppuren, team confirm pannuvaanga. Thank you sir!" Then STOP.')
        elif lang == "en-IN":
            parts.append('Lead wants to CLOSE. Say ONLY: "Got it sir, our team will send the property details + site visit slot on WhatsApp to this number. Thank you, sir!" Then STOP.')
        else:
            parts.append('Lead wants to CLOSE. Say ONLY: "Bilkul sir, isi number pe WhatsApp pe property details aur site visit slot bhej dete hain. Thank you!" Then STOP.')
    elif intent == "reject":
        if conv.reject_count >= 2:
            if lang == "ta-IN":
                parts.append('Still no. Warm exit: "Sari sir, naala property thedumbothu Almmatix-ku call pannunga. Thank you sir!" Then STOP.')
            elif lang == "en-IN":
                parts.append('Still no. Warm exit: "No problem sir, whenever you start looking for a property do remember Almmatix. Good day!" Then STOP.')
            else:
                parts.append('Still no. Warm exit: "Koi baat nahi sir, ghar dekhna ho to Almmatix yaad rakhiyega. Good day!" Then STOP.')
        else:
            if lang == "ta-IN":
                parts.append('Lead not interested. Don\'t push — ask for a REFERRAL ONCE: "Sari sir. Ungal nanban yaaravadhu ghar or flat thedanna, indha number ku sollunga, naanga nalla site visit set pannuvom."')
            elif lang == "en-IN":
                parts.append('Lead not interested. Don\'t push — ask for a REFERRAL ONCE: "No problem sir. If anyone you know is looking for a property, do share our number — we will arrange site visits for them."')
            else:
                parts.append('Lead not interested. Don\'t push — ask for a REFERRAL once: "Koi baat nahi sir. Aapke kisi jaan-pehchaan ko ghar dhoondhna ho to bata dijiye, hum site visit set kar denge?"')
    elif intent == "abuse":
        if lang == "ta-IN":
            parts.append('Lead abusive. Say ONLY: "Sari sir, good day." Nothing else.')
        elif lang == "en-IN":
            parts.append('Lead abusive. Say ONLY: "Thank you sir, good day." Nothing else.')
        else:
            parts.append('Lead abusive. Say ONLY: "Theek hai sir, good day." Nothing else.')
    elif intent == "wrong":
        if lang == "ta-IN":
            parts.append('Wrong person / off-topic. Say ONLY: "Sorry sir, ungal time waste pannitten. Good day sir!" Then STOP.')
        elif lang == "en-IN":
            parts.append('Wrong person / off-topic. Say ONLY: "Sorry sir, took your time. Good day!" Then STOP.')
        else:
            parts.append('Wrong person / off-topic. Say ONLY: "Sorry sir, aapka time liya. Good day!" Then STOP.')
    elif intent == "offtopic":
        if conv.off_topic_count >= 2:
            if lang == "ta-IN":
                parts.append('Still off-topic. End: "Sari sir, good day sir!" STOP.')
            elif lang == "en-IN":
                parts.append('Still off-topic. End: "No problem sir, good day!" STOP.')
            else:
                parts.append('Still off-topic. End: "Koi baat nahi sir, good day!" STOP.')
        else:
            if lang == "ta-IN":
                parts.append('Lead off-topic. Probe ONCE: "Sir, ungalukku ipo ghar or flat thedanum-aa, illa investment-kana property paakareenga sir?"')
            elif lang == "en-IN":
                parts.append('Lead off-topic. Probe ONCE: "Sir, are you actively looking for a home, or scouting for an investment property right now?"')
            else:
                parts.append('Lead off-topic. Probe ONCE: "Sir, abhi aap ghar dhoondh rahe hain ya investment ke liye property dekh rahe hain?"')
    else:
        # ---- Tire-kicker exit (5 unproductive turns in a row) ----
        # Threshold was 3 — too aggressive for Tamil/Hindi cold calls where
        # a real buyer often opens with 1-3 word replies ("haan", "achha",
        # "in pharma") before warming up. 5 gives the lead a fair chance to
        # surface a slot. We also stop counting turns where the lead names
        # an industry — see _mentions_industry().
        if conv.unproductive_turn_count >= 5:
            if lang == "ta-IN":
                exit_phrase = (
                    "Sari sir, ungalukku enna property venum-nu confirm aana, Almmatix-ku "
                    "call pannunga... naan help pannuren. Thank you sir!"
                )
            elif lang == "en-IN":
                exit_phrase = (
                    "No worries sir, whenever you have a specific property requirement, "
                    "do remember Almmatix. Thank you for your time, sir!"
                )
            else:
                exit_phrase = (
                    "Koi baat nahin sir, jab bhi koi specific property dhoondhni ho, "
                    "Almmatix yaad rakhiyega. Aapka time diya, thank you sir!"
                )
            parts.append(
                f'[EXIT NOW. Lead is not a qualifying buyer ('
                f'{conv.unproductive_turn_count} short/non-info turns). '
                f'Say EXACTLY: "{exit_phrase}". Nothing else.]'
            )
            return "\n".join(parts)

        # ---- Close NOW (buying signals firm) ----
        # When the lead has stated a pain AND a hard constraint (timeline /
        # volume / supplier complaint), more discovery is overkill. Close.
        if conv.close_armed and conv.consecutive_close_attempts < 1:
            if lang == "ta-IN":
                close_phrase = (
                    "Sari sir, indha number ku WhatsApp la quote varum, "
                    "team indre call pannuvaanga. Thank you sir!"
                )
            elif lang == "en-IN":
                close_phrase = (
                    "Got it sir — our team will send a quote on WhatsApp to "
                    "this number and call you today. Thank you, sir!"
                )
            else:
                close_phrase = (
                    "Bilkul sir, isi number pe WhatsApp pe quote aa jayega, "
                    "hamari team aaj hi follow-up karegi. Thank you sir!"
                )
            parts.append(
                f'[CLOSE NOW. Lead gave hard requirements — stop asking '
                f'questions. Say EXACTLY: "{close_phrase}". Nothing else.]'
            )
            return "\n".join(parts)

        # ---- Lead temperature — concrete sales directive every turn -----
        # Without an explicit temperature tag, the LLM treats every lead the
        # same: keep selling, keep asking. A real TN sales operator reads
        # heat instantly — hot leads get closed in the next sentence, warm
        # leads get ONE pain probe, cold leads get a warm goodbye. We surface
        # the heat here so Priya's next line matches the room.
        temperature = slots.live_temperature(turn_idx=turn)
        if temperature == "hot":
            if lang == "ta-IN":
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Sari sir, indha number ku WhatsApp la quote varum, "
                    "team indre call pannuvaanga. Thank you sir!']"
                )
            elif lang == "en-IN":
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Got it sir, our team will send a quote on WhatsApp to "
                    "this number and call you today. Thank you, sir!']"
                )
            else:
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Bilkul sir, isi number pe WhatsApp pe quote aa jayega, "
                    "team aaj hi call karegi. Thank you sir!']"
                )
            parts.append(heat_directive)
        elif temperature == "warm":
            if lang == "ta-IN":
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (volume / timeline / pain) in TAMIL — start with "
                    "'Sari sir, ...' + the question. Build toward the close, do "
                    "NOT list products.]"
                )
            elif lang == "en-IN":
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (volume / timeline / pain). Build toward the "
                    "close, do NOT list products.]"
                )
            else:
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (volume / timeline / pain). Build toward the "
                    "close, do NOT list products.]"
                )
        elif temperature == "cold":
            if lang == "ta-IN":
                parts.append(
                    "[TEMPERATURE: COLD. No buying signals after 3+ turns. "
                    "ONE last attempt — single concrete pain question in TAMIL "
                    "('Ungal current supplier la enna problem irukku sir?'). "
                    "If still no answer next turn, exit warmly.]"
                )
            else:
                parts.append(
                    "[TEMPERATURE: COLD. No buying signals after 3+ turns. "
                    "ONE last attempt — single concrete pain question. "
                    "If still no answer next turn, exit warmly.]"
                )
        # "unknown" → no extra directive; let phase hints drive.

        # Surface EVERY known slot — without this the LLM has no memory of
        # earlier answers and re-asks "what's your delivery timeline?" right
        # after the lead said "deliver in a week". Each non-empty slot becomes
        # a "do not re-ask" reminder.
        known: list[str] = []
        if slots.product_interest:
            known.append(f"product/interest: {slots.product_interest}")
        if slots.volume_monthly_kg:
            known.append(f"monthly volume: ~{slots.volume_monthly_kg}kg")
        if getattr(slots.buying_frequency, "value", "unknown") not in ("unknown", None):
            known.append(f"buying frequency: {slots.buying_frequency.value}")
        if slots.current_supplier:
            known.append(f"current supplier: {slots.current_supplier}")
        if slots.pain_point:
            known.append(f"pain point: {slots.pain_point}")
        if getattr(slots.decision_role, "value", "unknown") not in ("unknown", None):
            known.append(f"role: {slots.decision_role.value}")
        if slots.timeline_days is not None:
            known.append(f"timeline: {slots.timeline_days} days")

        if known:
            parts.append(
                "[ALREADY ANSWERED — do NOT ask about these again: "
                + "; ".join(known)
                + ". Acknowledge what's known, then move to the NEXT unknown.]"
            )

        # Show the lead's last few lines verbatim so the LLM can ground its
        # acknowledgement in actual words instead of inventing a paraphrase
        # that drifts from what was said.
        prior_lead = conv.recent_lead_turns[:-1] if conv.recent_lead_turns else []
        if prior_lead:
            tail = prior_lead[-3:]
            quoted = " | ".join(f'"{t}"' for t in tail)
            parts.append(f"[Lead said earlier: {quoted}]")

        if slots.buying_confidence >= 0.7:
            parts.append("High interest → push for close.")
        elif conv.consecutive_close_attempts >= 2:
            parts.append("Two rejections → goodbye.")

    return "\n".join(parts)


def _recent_priya_turns_as_transcript(conv):
    return [{"speaker": "priya", "text": t} for t in conv.recent_priya_turns[-4:]]
