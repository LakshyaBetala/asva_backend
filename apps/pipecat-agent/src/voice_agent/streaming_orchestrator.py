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
import os
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Mapping, Optional, Protocol

from .conversation_state import (
    ConversationState,
    Phase,
    native_hindi_script_enabled,
    native_tamil_script_enabled,
    system_prompt_addendum,
)
from .language_state import (
    Lang,
    LanguageState,
    STTUtterance,
    Transition,
    is_bare_ack,
)
from .industry.real_estate import LOCALITIES, LOCALITY_ALIASES
from .pain_library import pick_pain_hypothesis
from .phrase_cache import PINNED_VOICE_ID, load_or_synthesize_phrase, phrase_r2_key
from .sarvam_tts_ws import pcm16_to_wav
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
    """A piece of Priya's response, synthesized and ready to play.

    With the REST TTS path this is one full sentence (WAV). With the
    streaming TTS path one sentence arrives as SEVERAL events whose
    `audio` is raw PCM16 at the telephony rate (`is_raw_pcm=True`) —
    the first one lands ~100ms after the text is ready instead of after
    the whole clip is synthesized. `text` is set on the first chunk of
    a sentence and empty on its continuation chunks.
    """
    audio: bytes
    text: str
    sentence_idx: int
    used_cache: bool
    is_raw_pcm: bool = False


async def _sentence_audio_events(
    *,
    spoken: str,
    lang: str,
    deps,
    sentence_idx: int,
    stats: dict,
):
    """Yield playable AudioChunkEvents for one prepared sentence.

    Streaming-capable TTS (`synth_stream`) forwards raw PCM chunks the
    moment they arrive — first audio in ~100ms instead of after the full
    clip renders. Cache hits short-circuit either way; a streamed
    sentence is assembled and written back so the same line is a cache
    hit on the next call. Sets stats["used_cache"]."""
    streamer = getattr(deps.tts, "synth_stream", None)
    if streamer is None:
        phrase_result = await load_or_synthesize_phrase(
            text=spoken,
            lang=lang,
            r2_reader=deps.r2_reader,
            r2_writer=deps.r2_writer,
            synthesize=lambda t, l: deps.tts.synth(t, l),
            voice_id=deps.voice_id,
        )
        stats["used_cache"] = phrase_result.used_cache
        yield AudioChunkEvent(
            audio=phrase_result.audio, text=spoken,
            sentence_idx=sentence_idx, used_cache=phrase_result.used_cache,
        )
        return

    key = phrase_r2_key(text=spoken, lang=lang, voice_id=deps.voice_id)
    cached = await deps.r2_reader.get(key)
    if cached is not None:
        stats["used_cache"] = True
        yield AudioChunkEvent(
            audio=cached, text=spoken,
            sentence_idx=sentence_idx, used_cache=True,
        )
        return

    stats["used_cache"] = False
    pcm_parts: list[bytes] = []
    first = True
    async for chunk in streamer(spoken, lang):
        pcm_parts.append(chunk)
        yield AudioChunkEvent(
            audio=chunk,
            # text marks the start of a sentence (logging + pads);
            # continuation chunks carry no text.
            text=spoken if first else "",
            sentence_idx=sentence_idx,
            used_cache=False,
            is_raw_pcm=True,
        )
        first = False
    if pcm_parts:
        try:
            rate = getattr(deps.tts, "sample_rate", 8000)
            await deps.r2_writer.put(
                key, pcm16_to_wav(b"".join(pcm_parts), rate), "audio/wav"
            )
        except Exception:
            logger.debug("phrase write-back failed", exc_info=True)


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
    # Tenant's company name (e.g. "XYZ Broker"). Priya speaks AS this broker,
    # so warm-exit / referral lines must name THIS company — never our product
    # brand "Almmatix" (which leaked into those hardcoded lines, call 2809a134).
    company_name: str = ""


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
# Markup the LLM sometimes parrots from the prompt (e.g. "<lang>hi-IN</lang>"
# — the base prompt used to mention "the <lang> tag", so Gemini emitted it
# verbatim and the TTS SPOKE it, call 6d9dc0f8). Metadata tags carry a VALUE
# that must NOT be spoken (the "hi-IN" inside <lang>…</lang>), so those are
# removed with their content; any other stray tag is unwrapped (inner text
# kept) so a formatting slip like "<b>sir</b>" still says "sir".
_META_TAG_RE = re.compile(
    r"<(lang|current_language|lang_pin|format|phase|current_phase)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_LONE_TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,40}>")


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
    cleaned = _META_TAG_RE.sub("", text)
    cleaned = _LONE_TAG_RE.sub("", cleaned)
    cleaned = _PARENS_RE.sub("", cleaned)
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
        # The whole sentence was a bare ack the name-echo stripper consumed.
        # If it was genuinely short ("Haan ji.", "Sari sir."), speak it as-is
        # — natural. Otherwise drop the sentence (callers skip empties).
        # NEVER substitute a canned line here: the old fallback ("Sorry sir,
        # didn't catch that. Are you looking to buy or to rent?") fired
        # mid-call ignoring context, got phrase-cached, and re-asked
        # already-answered questions (calls d4cffcb9, 866614ad).
        original = _WRAPPING_QUOTES.sub("", text.strip()).strip()
        if 0 < len(original.split()) <= 4:
            return original
        return ""
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


def _ta_pacing_enabled() -> bool:
    """The ellipsis-pacing hack exists for the OLD Tamil voices (smallest
    meher / cartesia) that ran clauses together. Bulbul v3 has native Tamil
    prosody and renders each "..." as a long hole — testers heard them as
    gaps in the call (2026-06-13). Skip pacing entirely on the Sarvam stack."""
    return os.environ.get("TTS_PROVIDER", "").strip().lower() != "sarvam"


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


# -- Number → words (Indian system) ----------------------------------------
#
# The TTS reads bare digits digit-by-digit on 8kHz phone audio: "2000 square
# feet" came out as "two zero zero zero" (call d4cffcb9). Spell numbers out
# in English words — natural in Hinglish/Tanglish sentences too ("do hazaar"
# would be wrong inside an English phrase; "two thousand" is how Chennai
# actually says it).

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()


def _int_to_words(n: int) -> str:
    """0..99_99_99_999 in Indian-system English words (lakh / crore)."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, r = divmod(n, 10)
        return _TENS[t] + (f" {_ONES[r]}" if r else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{_ONES[h]} hundred" + (f" {_int_to_words(r)}" if r else "")
    if n < 100_000:
        th, r = divmod(n, 1000)
        return f"{_int_to_words(th)} thousand" + (f" {_int_to_words(r)}" if r else "")
    if n < 10_000_000:
        lk, r = divmod(n, 100_000)
        return f"{_int_to_words(lk)} lakh" + (f" {_int_to_words(r)}" if r else "")
    cr, r = divmod(n, 10_000_000)
    return f"{_int_to_words(cr)} crore" + (f" {_int_to_words(r)}" if r else "")


# Standalone integers up to 9 digits, with optional Indian comma grouping.
# Deliberately NOT matched: decimals handled separately, 10+ digit runs
# (phone numbers — those SHOULD be read digit-by-digit), times like 4:30.
_NUM_RE = re.compile(r"(?<![\d.,:])(\d{1,3}(?:,\d{2,3})*|\d{1,9})(\.\d+)?(?![\d,:])")


def spell_numbers_for_tts(text: str) -> str:
    def _sub(m: re.Match) -> str:
        whole = m.group(1).replace(",", "")
        if len(whole) > 9:  # defensive: leave huge runs alone
            return m.group(0)
        words = _int_to_words(int(whole))
        if m.group(2):  # decimal part: "1.5" -> "one point five"
            digits = " ".join(_ONES[int(d)] for d in m.group(2)[1:])
            words = f"{words} point {digits}"
        return words

    return _NUM_RE.sub(_sub, text)


def prepare_for_tts(
    text: str,
    lang: str,
    pack: Mapping[str, str] | None = None,
) -> str:
    """Sanitiser + number spelling + pronunciation pack + per-language pacing.

    Single entry point for TTS-bound text. Pack substitution runs *before*
    pacing so Tamil ellipsis insertion sees the final spelling, and it
    runs *above* the phrase cache so each substituted form gets its own
    cache entry (correct — different audio per tenant pronunciation).
    """
    cleaned = sanitize_for_tts(text)
    if not cleaned:
        return cleaned
    # Number spelling ("2000"→"two thousand") is for ROMAN output — inside a
    # Devanagari/Tamil sentence it produced English words next to native text
    # ("nine बजे" → heard as "9 bhajay", call 287e6c4d). In native mode keep
    # the digits; Sarvam's enable_preprocessing reads them in-language
    # ("9 बजे" → "नौ बजे").
    if not _native_script_for(lang):
        cleaned = spell_numbers_for_tts(cleaned)
    if pack:
        cleaned = apply_pronunciation_pack(cleaned, pack)
    if lang == "ta-IN" and _ta_pacing_enabled():
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
    if lang == "ta-IN" and _ta_pacing_enabled():
        out = pace_for_ta_tts(out)
    return out


# -- Main streaming entry point ---------------------------------------------

async def run_turn_streaming(
    *,
    ctx,  # CallContext
    audio_in: bytes,
    deps: StreamingDependencies,
    prior_slots: QualificationSlots,
    pre_transcribed=None,  # STTResult finalized by the streaming-STT WS
) -> AsyncIterator[StreamEvent]:
    """Stream audio chunks as LLM generates sentences.

    Yields AudioChunkEvent per sentence, then one final TurnCompleteEvent.
    The Exotel WS handler plays each AudioChunkEvent immediately.

    When `pre_transcribed` is set, the utterance was already finalized by
    Sarvam's streaming WebSocket (server-side endpointing) — step 1 is a
    no-op and audio_in may be empty.
    """
    timings: dict[str, int] = {}
    t0 = time.monotonic()

    # ---- 1. STT -----------------------------------
    if pre_transcribed is not None:
        stt_result = pre_transcribed
        timings["stt_ms"] = 0
    else:
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
        # Streaming STT only hands us non-empty finals, so on that path a
        # collapse to "(silence)" means we transcribed Priya's own echo.
        # Saying ANYTHING here is wrong — she just spoke (call 56e606ca
        # opened with a cached "Got it." aimed at her own intro echo). Skip
        # the turn silently; the lead's real words arrive as the next final.
        if pre_transcribed is not None:
            yield TurnCompleteEvent(
                lead_text="(silence)",
                lead_lang=ctx.language_state.current.value,
                lead_confidence=0.0,
                priya_full_text="",
                language_transition=Transition(
                    current_language=ctx.language_state.current,
                    switched=False, trigger="none", bridge_phrase=None,
                ),
                slots=prior_slots,
                latency_ms={"total_ms": int((time.monotonic() - t0) * 1000)},
                total_sentences=0,
                cache_hits=0,
                lead_intent="silence",
            )
            return
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

    # ---- 2b. Inaudible / garbled audio → ask to repeat (trust beats guessing)
    # Wrong-script short utterances and line noise mean we did NOT hear the
    # lead. The honest move — what a human caller does — is a quick "sorry,
    # could you repeat?". Deterministic (no LLM): instant, never invents an
    # answer to words the lead didn't say. Capped at 2 consecutive re-prompts
    # so a genuinely noisy line doesn't loop; after that the LLM does its best.
    cur_lang = transition.current_language.value
    if (
        stt_result.transcript != "(silence)"
        and is_garbled_utterance(stt_result.transcript, cur_lang)
        and ctx.conversation_state.repeat_request_count < 2
    ):
        ctx.conversation_state.repeat_request_count += 1
        repeat_line = _repeat_line(cur_lang)
        # prepare_intro_for_tts = pack + Tamil pacing WITHOUT the name-echo
        # sanitiser (which could eat the leading "Sorry sir" ack).
        spoken = prepare_intro_for_tts(repeat_line, cur_lang, deps.pronunciation_pack)
        tts_t0 = time.monotonic()
        phrase_result = await load_or_synthesize_phrase(
            text=spoken,
            lang=cur_lang,
            r2_reader=deps.r2_reader,
            r2_writer=deps.r2_writer,
            synthesize=lambda t, l: deps.tts.synth(t, l),
            voice_id=deps.voice_id,
        )
        timings["tts_first_sentence_ms"] = int((time.monotonic() - tts_t0) * 1000)
        timings["total_ms"] = int((time.monotonic() - t0) * 1000)
        ctx.conversation_state.record_priya_turn(spoken)
        ctx.phrase_cache_hits += 1 if phrase_result.used_cache else 0
        ctx.turn_idx += 1
        yield AudioChunkEvent(
            audio=phrase_result.audio, text=spoken,
            sentence_idx=0, used_cache=phrase_result.used_cache,
        )
        yield TurnCompleteEvent(
            lead_text=stt_result.transcript,
            lead_lang=cur_lang,
            lead_confidence=stt_result.confidence,
            priya_full_text=spoken,
            language_transition=transition,
            slots=prior_slots,
            latency_ms=timings,
            total_sentences=1,
            cache_hits=1 if phrase_result.used_cache else 0,
            lead_intent="garbled",
        )
        return
    if stt_result.transcript != "(silence)" and not is_garbled_utterance(
        stt_result.transcript, cur_lang
    ):
        ctx.conversation_state.repeat_request_count = 0

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

    if intent in ("normal", "backchannel") and _lead_chose_visit_slot(
        stt_result.transcript, ctx.conversation_state
    ):
        ctx.conversation_state.visit_slot_text = stt_result.transcript.strip()

    # Sales brain — decide whether to keep digging, close, or exit warmly.
    #
    #   "buying-ready" (real estate) = requirement captured (intent +
    #   BHK/locality live in product_interest) PLUS one more signal —
    #   a must-have, a timeline, or decent buying confidence. That's a
    #   bookable site visit; further discovery is dragging (call 9ed9a612:
    #   rent + Anna Nagar + 3 BHK on the table and Priya kept qualifying
    #   instead of proposing slots — the lead hung up).
    #
    #   "unproductive" = lead is on-topic but giving nothing back (short
    #   utterance, no slot info). After 5 of those in a row we exit
    #   politely. This prevents Call-1-style 371s dead-end conversations.
    # Bookable = locality or BHK known (not bare "rent"/"buy") — a broker
    # can't send matching listings or book a worthwhile visit without it.
    has_requirement = _requirement_bookable(prior_slots.product_interest)
    has_pain = bool(prior_slots.pain_point)
    has_timeline = prior_slots.timeline_days is not None
    is_buying_ready = has_requirement and (
        has_pain or has_timeline or prior_slots.buying_confidence >= 0.4
    )
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
        # Cheap text-level signal: if the lead's reply contains property
        # info (BHK, rent/buy, budget words, a locality name — or Tamil/
        # Hindi script equivalents), it's NOT unproductive even if the slot
        # extractor hasn't run yet. This protects warm-but-terse leads who
        # say "அண்ணா நகர்" / "do BHK chahiye" — true info, but only 2-3
        # space-separated tokens.
        if not produced_info and _mentions_property_info(stt_result.transcript):
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
        # Mark cut-off fragments in the rolling history. Without the marker
        # the LLM treats "Budget is around" as a complete statement and a
        # later turn may literally CONTINUE it — call 56e606ca produced a
        # reply starting mid-sentence ("Tak kiraye ke liye...").
        recorded = stt_result.transcript
        if transcript_unfinished(recorded):
            recorded = recorded.rstrip() + " … (cut off mid-sentence)"
        ctx.conversation_state.record_lead_turn(recorded)

    user_msg = _format_user_message(
        stt_result.transcript, prior_slots, ctx.conversation_state,
        lang=transition.current_language.value, intent=intent,
        company=getattr(deps, "company_name", "") or "",
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
                if sentence_idx == 0 and _is_echo_ack(spoken, stt_result.transcript):
                    # More text is still streaming behind this echo —
                    # dropping it can't leave the turn empty here.
                    continue
                if not first_sentence_done:
                    timings["llm_first_sentence_ms"] = int(
                        (time.monotonic() - llm_t0) * 1000
                    )
                    first_sentence_done = True

                tts_t0 = time.monotonic()
                full_text_parts.append(spoken)
                sent_stats: dict = {}
                async for audio_ev in _sentence_audio_events(
                    spoken=spoken,
                    lang=transition.current_language.value,
                    deps=deps,
                    sentence_idx=sentence_idx,
                    stats=sent_stats,
                ):
                    if "tts_first_sentence_ms" not in timings:
                        timings["tts_first_sentence_ms"] = int(
                            (time.monotonic() - tts_t0) * 1000
                        )
                    yield audio_ev
                if sent_stats.get("used_cache"):
                    cache_hits += 1
                sentence_idx += 1

            sentence_buffer = sentences[-1]  # keep incomplete tail

    # Flush remaining buffer (skipped if cap already reached)
    tail = prepare_for_tts(
        sentence_buffer.strip(),
        transition.current_language.value,
        deps.pronunciation_pack,
    )
    # Echo-ack guard for the tail: only when something was already spoken —
    # if the WHOLE reply is the echo, speaking it beats dead air.
    if tail and sentence_idx > 0 and _is_echo_ack(tail, stt_result.transcript):
        tail = ""
    if tail and sentence_idx < MAX_SENTENCES_PER_TURN:
        if not first_sentence_done:
            timings["llm_first_sentence_ms"] = int(
                (time.monotonic() - llm_t0) * 1000
            )
        tts_t0 = time.monotonic()
        full_text_parts.append(tail)
        tail_stats: dict = {}
        async for audio_ev in _sentence_audio_events(
            spoken=tail,
            lang=transition.current_language.value,
            deps=deps,
            sentence_idx=sentence_idx,
            stats=tail_stats,
        ):
            if "tts_first_sentence_ms" not in timings:
                timings["tts_first_sentence_ms"] = int(
                    (time.monotonic() - tts_t0) * 1000
                )
            yield audio_ev
        if tail_stats.get("used_cache"):
            cache_hits += 1
        sentence_idx += 1

    timings["llm_ms"] = int((time.monotonic() - llm_t0) * 1000)

    # Dead-air guard: if the whole reply sanitised away to nothing (or the
    # LLM stream yielded zero content — seen when a fallback model spends its
    # token budget on reasoning), the lead must NEVER hear silence. One short
    # neutral continue-prompt is safe in any call state. Skipped when the
    # turn is ending anyway — "Ji, boliye?" followed by a hangup is worse.
    if sentence_idx == 0 and not end_call:
        cont = _continue_line(transition.current_language.value)
        phrase_result = await load_or_synthesize_phrase(
            text=cont,
            lang=transition.current_language.value,
            r2_reader=deps.r2_reader,
            r2_writer=deps.r2_writer,
            synthesize=lambda t, l: deps.tts.synth(t, l),
            voice_id=deps.voice_id,
        )
        if phrase_result.used_cache:
            cache_hits += 1
        full_text_parts.append(cont)
        yield AudioChunkEvent(
            audio=phrase_result.audio, text=cont,
            sentence_idx=0, used_cache=phrase_result.used_cache,
        )
        sentence_idx = 1

    # ---- 6. Wait for slot extraction -----------------------------------
    new_slots = await slots_task

    # ---- 7. Update conversation state ----------------------------------
    priya_full = " ".join(full_text_parts)
    if priya_full:
        # An empty Priya turn in the window breaks the lead↔Priya interleave
        # the history formatter relies on — record only real speech.
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
_PROPERTY_ASCII = frozenset({
    "bhk", "flat", "apartment", "villa", "plot", "house", "property",
    "rent", "rental", "lease", "buy", "purchase", "investment",
    "budget", "lakh", "lakhs", "crore", "crores", "loan", "emi",
    "ready to move", "under construction", "possession", "site visit",
    "society", "builder", "resale", "deposit", "advance",
    "veedu", "ghar", "makaan", "kiraya", "vadagai",
})
_PROPERTY_SCRIPT_RE = re.compile(
    r"வீடு|வீட்டு|ஃப்ளாட்|பிளாட்|வாடகை|சொத்து|நகர்|"  # Tamil
    r"घर|मकान|फ्लैट|किराया|प्रॉपर्टी|बजट|लाख|करोड़|नगर"  # Hindi
)
# A locality name alone ("Anna Nagar", "Bandra West") is hard info for a
# broker — it must count as a productive turn even when the slot extractor
# hasn't filled product_interest yet.
_LOCALITY_TOKENS = frozenset(
    name.lower() for names in LOCALITIES.values() for name in names
) | frozenset(LOCALITY_ALIASES.keys())


def _requirement_bookable(product_interest: str | None) -> bool:
    """A site visit is only worth booking once we know WHERE (locality) or
    WHAT SIZE (BHK) — a broker can't send matching listings for bare 'rent'
    or 'buy'. Gates the close so it doesn't fire on intent alone (call
    22c86781: Priya offered a visit after the lead only said 'rent plan',
    booking with no area/BHK/budget). Once a locality or BHK lands, it's
    bookable — so this does NOT reintroduce dragging."""
    if not product_interest:
        return False
    pi = product_interest.lower()
    if "bhk" in pi or "bed" in pi:
        return True
    return any(loc in pi for loc in _LOCALITY_TOKENS)


def _mentions_property_info(text: str | None) -> bool:
    """True when the lead's transcript names property info (BHK / budget /
    buy-rent / locality) — useful "produced info" signal for the
    unproductive-turn counter even when the LLM slot extractor hasn't run."""
    if not text:
        return False
    lower = text.lower()
    for token in _PROPERTY_ASCII:
        if token in lower:
            return True
    for locality in _LOCALITY_TOKENS:
        if locality in lower:
            return True
    if _PROPERTY_SCRIPT_RE.search(text):
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


# Per-language "home" script. Any OTHER Indic script in a short utterance is
# an STT misfire on unclear audio, not a real language switch — the streaming
# model picks a random script for mumbled audio (call 56e606ca: Gujarati
# "ઓકે", Telugu "ఓకే అండి" on a Hindi call).
_HOME_SCRIPT_RE: dict[str, re.Pattern[str]] = {
    "hi-IN": re.compile(r"[ऀ-ॿ]"),
    "ta-IN": re.compile(r"[஀-௿]"),
}


def _wrong_script_short(text: str, lang: str) -> bool:
    """True when a SHORT utterance carries Indic script that cannot belong to
    the pinned call language — almost certainly garbled/unclear audio."""
    t = (text or "").strip()
    if not t or len(t.split()) > 4:
        return False
    indic_chars = _INDIC_SCRIPT_RE.findall(t)
    if not indic_chars:
        return False
    home = _HOME_SCRIPT_RE.get(lang)
    if home is None:  # en-IN: any Indic script on a short utterance is noise
        return True
    return any(not home.match(c) for c in indic_chars)


def is_garbled_utterance(text: str, lang: str) -> bool:
    """The audio was probably inaudible/unclear: wrong-script short utterance
    or classic line noise. Used to trigger a polite 'can you repeat?' instead
    of letting the LLM guess — guessing wrong is what burns trust."""
    if is_bare_ack(text):
        return False  # an ack is meaningful even in the wrong script
    return _wrong_script_short(text, lang) or _looks_like_line_noise(text, lang=lang)


# Words that almost never END a finished thought. Sarvam's streaming VAD can
# finalize mid-breath ("Budget is around" — call 56e606ca) and it auto-
# punctuates, so trailing punctuation alone can't be trusted as "complete".
_DANGLING_END_WORDS: frozenset[str] = frozenset({
    # English
    "around", "about", "is", "are", "was", "and", "or", "but", "the", "a",
    "an", "my", "your", "their", "our", "in", "of", "to", "for", "so",
    "very", "with", "than", "like",
    # Romanized Hindi
    "mein", "ke", "ki", "ka", "se", "ko", "aur", "ya", "kya", "main",
    "mai", "toh", "par", "wala", "wali", "liye",
    # Devanagari
    "में", "के", "की", "का", "से", "को", "और", "या", "क्या", "मैं", "तो",
    "पर", "लिए",
    # Tamil romanized connectors
    "la", "ku", "oda", "kitta",
})


def transcript_unfinished(text: str) -> bool:
    """Heuristic: the lead was probably cut off mid-sentence.

    The last word is a dangling connective ("around", "ke", "मैं") —
    nothing else. The WS handler uses this to hold the turn a little
    longer; the prompt uses it to ask the lead to finish instead of
    answering a fragment.

    There used to be a second rule — "no terminal punctuation = cut
    off" — but the streaming STT routinely emits complete finals with
    no punctuation ("Ya, tell me Priya", "Rent"), so that rule made
    EVERY turn pay the +700ms dangling hold (call 9ed9a612: 4 of 5
    turns held for nothing). Punctuation says nothing; the final word
    does.
    """
    t = (text or "").strip()
    if not t or is_bare_ack(t):
        return False
    words = t.rstrip(".?!।,…").split()
    last = words[-1].lower() if words else ""
    return last in _DANGLING_END_WORDS


# Deterministic outlier lines, per language. Synthesised via the phrase cache
# so repeats are free. Kept SHORT and context-free on purpose — they are safe
# in any state of the call (unlike the old canned buy-or-rent fallback).
_REPEAT_LINES = {
    "ta-IN": "Sorry sir, line clear-aa illa, konjam thirumba sollunga?",
    "en-IN": "Sorry, the line wasn't clear — could you say that once more?",
    "hi-IN": "Sorry sir, awaaz clear nahin aayi — ek baar phir boliye?",
}
_CONTINUE_LINES = {
    "ta-IN": "Sollunga sir?",
    "en-IN": "Yes, please go ahead?",
    "hi-IN": "Ji, boliye?",
}
# Native-script twins: Bulbul reads romanized Hindi/Tamil with English
# letter-phonetics, so every line that is SPOKEN verbatim needs a native
# form on the Sarvam stack (the LLM's prose is already pinned to native
# script; these canned lines were the leftover).
_REPEAT_LINES_NATIVE = {
    "ta-IN": "Sorry sir, line சரியா இல்ல, கொஞ்சம் திரும்ப சொல்லுங்க?",
    "hi-IN": "Sorry sir, आवाज़ clear नहीं आई — एक बार फिर बोलिए?",
}
_CONTINUE_LINES_NATIVE = {
    "ta-IN": "சொல்லுங்க sir?",
    "hi-IN": "जी, बोलिए?",
}


def _native_script_for(lang: str) -> bool:
    if lang == "ta-IN":
        return native_tamil_script_enabled()
    if lang == "hi-IN":
        return native_hindi_script_enabled()
    return False


def _repeat_line(lang: str) -> str:
    if _native_script_for(lang) and lang in _REPEAT_LINES_NATIVE:
        return _REPEAT_LINES_NATIVE[lang]
    return _REPEAT_LINES.get(lang, _REPEAT_LINES["en-IN"])


def _continue_line(lang: str) -> str:
    if _native_script_for(lang) and lang in _CONTINUE_LINES_NATIVE:
        return _CONTINUE_LINES_NATIVE[lang]
    return _CONTINUE_LINES.get(lang, _CONTINUE_LINES["en-IN"])


def _is_echo_ack(sentence: str, lead_text: str) -> bool:
    """True when a SHORT opening sentence is mostly the lead's own words —
    the LLM echoing their answer back as its ack ("Annanagar." after they
    said Annanagar, "two BHK." after "do BHK", "fifteen to twentyk." after
    "15 to 20k"). The prompt bans this; llama ignores the ban (call
    2b674c4c, every turn). Deterministic guard: drop the sentence instead
    of speaking it. Numbers are spelled on both sides so "20k" matches
    "twentyk".

    Bare acks ("Haan ji.", "Theek hai.") are exempt — they're natural
    fillers even when the lead used the same words."""
    if is_bare_ack(sentence):
        return False
    words = re.findall(r"\w+", spell_numbers_for_tts(sentence.lower()))
    if not words:
        return False
    lead_words = set(
        re.findall(r"\w+", spell_numbers_for_tts((lead_text or "").lower()))
    )
    if not lead_words:
        return False
    overlap = sum(1 for w in words if w in lead_words)
    # Short echoes ("two BHK.") need half their words shared; longer ones
    # ("thirty five se forty five hazaar tak." — 7 words, 4 shared after
    # number spelling, call be21ced9) get a 0.55 bar — high enough that a
    # real confirmation ("Saturday subah ten baje pakka sir?" = 0.33
    # overlap) never trips it.
    if len(words) <= 4:
        return overlap / len(words) >= 0.5
    if len(words) <= 7:
        return overlap / len(words) >= 0.55
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
        parts.append(f"Requirement discussed: {slots.product_interest}")
    if slots.volume_monthly_kg and slots.volume_monthly_kg > 0:
        parts.append(f"Volume: {slots.volume_monthly_kg} kg/month")
    if slots.current_supplier:
        parts.append(f"Other broker they already use: {slots.current_supplier}")
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
    # NATIVE SCRIPT — pinned STT now returns Devanagari/Tamil, so the romanized
    # forms above never matched and the call wouldn't end (call 287e6c4d: lead
    # said "ठीक है, थैंक यू" and Priya kept talking).
    "थैंक यू", "थैंक्यू", "धन्यवाद", "थैंक यू बाय", "बाय",
    "भेज दीजिए", "भेज दो", "भेज दीजिये", "व्हाट्सएप में भेज", "व्हाट्सएप पे भेज",
    "व्हाट्सएप पर भेज", "देख लूँगा", "देख लेता", "देख लेंगे", "देख लूंगा",
    "ठीक है थैंक", "ठीक है बाय",
    "நன்றி", "சரி நன்றி", "போதும்", "அனுப்புங்க", "வாட்ஸ்அப்ல அனுப்பு",
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
    is NOT a backchannel.

    is_bare_ack covers the native-script forms the streaming STT emits for
    mumbled acks ("अच्छा ठीक है।", "ઓકે.", "ఓకే అండి.") — call 56e606ca
    classified those as intent=normal "answers" and the LLM re-asked the same
    visit-day question three times trying to make sense of them."""
    if is_bare_ack(text):
        return True
    cleaned = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = cleaned.split()
    if not words or len(words) > 4:
        return False
    if not all(w in _BACKCHANNEL_TOKENS or w in _BACKCHANNEL_CONNECTORS for w in words):
        return False
    return any(w in _BACKCHANNEL_TOKENS for w in words)


# Question openers across the call languages (Roman + native script).
# Used to catch lead questions even when STT drops the "?" — tester
# feedback (2026-06-12): "if ask anything in between, it will ask its
# next question" — Priya was ignoring lead questions and ploughing on.
_QUESTION_WORDS = frozenset({
    # English
    "what", "how", "why", "when", "where", "who", "which", "whose",
    # Romanized Hindi
    "kya", "kaise", "kaisa", "kaisi", "kyu", "kyun", "kyon", "kitna",
    "kitne", "kitni", "kab", "kaun", "kahan", "kahaan",
    # Devanagari
    "क्या", "कैसे", "कैसा", "क्यों", "कितना", "कितने", "कितनी",
    "कब", "कौन", "कहां", "कहाँ",
    # Romanized Tamil
    "enna", "eppadi", "yen", "eppo", "eppadhu", "evlo", "evvalavu",
    "yaaru", "yaar", "edhu", "enga", "engey",
    # Tamil script
    "என்ன", "எப்படி", "ஏன்", "எப்போ", "எவ்ளோ", "எவ்வளவு",
    "யாரு", "யார்", "எது", "எங்க",
})


# Day words across scripts — the lead picking a visit day. STT renders
# English day names in whatever script it fancies ("సాటర్డే", "सैटरडे").
# ANY weekday the lead might pick, across scripts + STT spelling variants.
# Call 287e6c4d: regex had only "सैटरडे" but STT wrote "साटरडे", and Monday
# ("मंडे") wasn't listed at all — so the chosen day was never captured and
# Priya re-offered "Saturday ya Sunday" forever. Stems (शनि, सैटर/साटर/सेटर,
# मंडे/सोमवार…) are spelling-robust on purpose.
_VISIT_DAY_RE = re.compile(
    r"monday|mande|मंडे|मनडे|सोमवार|திங்க|"
    r"tuesday|ट्यूज|मंगल|செவ்வாய|"
    r"wednesday|बुध|புதன|"
    r"thursday|गुरु|बृहस्पति|வியாழ|"
    r"friday|फ्राइडे|शुक्र|வெள்ளி|"
    r"saturday|satar|सैटर|साटर|सेटर|शनि|சனி|సాటర్డే|శనివారం|"
    r"sunday|sande|संडे|सन्डे|रवि|ஞாயி|సండే|ఆదివారం|సోమవారం|"
    r"समय|टाइम",
    re.IGNORECASE,
)
# Tokens that show Priya was proposing/confirming a visit slot — gates the
# day capture so a stray day word elsewhere doesn't trigger it.
_VISIT_CONTEXT_RE = re.compile(
    r"visit|विज़िट|विजिट|விசிட்|site|साइट|समय|time|कब|day|बजे|நேரம்",
    re.IGNORECASE,
)


def _lead_chose_visit_slot(text: str, conv) -> bool:
    """True when the lead names a day/time while Priya has been proposing
    visit slots. That answer must STICK — site_visit isn't an extractor
    slot, so without this Priya re-offers the same choice forever
    (calls be21ced9, 287e6c4d)."""
    if not text or not _VISIT_DAY_RE.search(text):
        return False
    recent = " ".join(conv.recent_priya_turns[-3:])
    return bool(_VISIT_CONTEXT_RE.search(recent))


def _lead_asked_question(text: str) -> bool:
    """True when the lead's utterance is (or contains) a question."""
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    words = re.sub(r"[^\w\sऀ-ൿ]|[।॥]", " ", t.lower()).split()
    return any(w in _QUESTION_WORDS for w in words)


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


def _format_user_message(lead_text, slots, conv, *, lang: str = "hi-IN", intent: str = "normal", company: str = ""):
    turn = len(conv.recent_priya_turns)
    is_silence = intent == "silence"
    # Priya speaks AS the broker tenant — exit/referral lines must name THIS
    # company, never our product brand "Almmatix" (call 2809a134). Fallback
    # is a neutral phrase so an unconfigured tenant never voices the wrong name.
    co = company.strip() if company else ""
    co_hi = co or "hamari team"
    co_ta = co or "enga team"

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
        # Devanagari frustration seen on pinned-STT calls (287e6c4d):
        "पागल", "क्या हो गया", "फिर से फिर", "रिपीट क्यों", "समझा नहीं",
        "क्या बोल रहे", "क्या बोलना चाह",
    )
    lead_frustrated = any(k in lead_lc or k in (lead_text or "") for k in _FRUSTRATION_KEYWORDS)

    if lang == "ta-IN" and native_tamil_script_enabled():
        script_rule = (
            '[Tamil words in TAMIL SCRIPT; English terms (BHK, budget, '
            'WhatsApp) stay in English letters. No Devanagari.]'
        )
    elif lang == "hi-IN" and native_hindi_script_enabled():
        script_rule = (
            '[Hindi words in DEVANAGARI; English terms (BHK, budget, '
            'WhatsApp) stay in English letters. No Tamil script.]'
        )
    else:
        script_rule = '[ROMAN SCRIPT ONLY. No Devanagari. No Tamil script.]'
    parts = [
        script_rule,
        # Anti-parrot — the #1 complaint from live calls. "Acknowledge" means
        # 2-4 words, NEVER a restatement of what the lead just told you.
        '[NEVER restate or summarise the lead\'s words back to them '
        '("aap rent pe dekh rahe hain...", "aapko lagta hai ki..."), and '
        'NEVER echo their answer as your ack ("For rent." after they said '
        'rent / "Anna Nagar." after they named it — banned). They '
        'KNOW what they said. Ack in 2-4 words max, then ANSWER their '
        'question or ask the next NEW thing. VARY the ack — never open two '
        'replies in a row with the same word (rotate: Achha / Sari sir / '
        'Got it / Theek hai / Right / Samjhi / Okay sir — or skip the ack '
        'entirely). Every reply must END with a question or a concrete '
        'next step — never with an observation.]',
    ]
    # Mid-sentence cutoff guard: batch STT flushes on silence, so a thinking
    # pause ("can I know how many, what is—") arrives as a half-question.
    # Call 0b3ba6e2: Priya answered the fragment with a non-sequitur apology
    # and the lead snapped "do you forget things?". If the utterance looks
    # unfinished, prompt them to continue instead of guessing.
    _lt = (lead_text or "").strip()
    if (
        len(_lt.split()) >= 3
        and transcript_unfinished(_lt)
        and intent in ("normal", "backchannel")
    ):
        parts.append(
            '[The lead\'s line may be CUT OFF mid-sentence (phone STT '
            'flushes on pauses). If it reads incomplete, do NOT answer the '
            'half-question, do NOT complete their sentence for them, and do '
            'NOT change topic — invite them to finish in 2-4 words: "Haan '
            'sir, boliye?" / "Yes sir, tell me?" / "Sollunga sir?". If it '
            'reads complete, reply normally.]'
        )
    elif intent == "normal" and len(_lt.split()) >= 5:
        # Longer utterances that survived the deterministic garble check can
        # still be mis-transcribed nonsense ("क्या मैंने तो तू नहीं चेंज
        # किया?"). Give the LLM explicit permission to ask for a repeat
        # instead of bluffing an answer — bluffing is what kills trust.
        parts.append(
            '[If the lead\'s line reads as NONSENSE / random words that '
            'don\'t fit the conversation, the phone audio was garbled. Do '
            'NOT guess or change topic — ask them to repeat once, briefly: '
            '"Sorry sir, awaaz clear nahin aayi — ek baar phir boliye?" '
            '(match the call language). If it makes sense, reply normally.]'
        )

    # Lead asked something — answer it BEFORE any scripted next question.
    # Tester feedback (2026-06-12): the call felt like a one-way Q&A; when
    # the lead asked anything mid-flow, Priya ignored it and fired her next
    # qualifier. Nothing kills trust faster than an unanswered question.
    slot_chosen = bool(getattr(conv, "visit_slot_text", ""))
    if slot_chosen and intent in ("normal", "backchannel"):
        parts.append(
            f'[The lead ALREADY chose the site-visit slot — their words: '
            f'"{conv.visit_slot_text}". Do NOT offer day/time choices '
            'again. CONFIRM that exact slot in one short sentence, say the '
            'property details + confirmation will come on WhatsApp, thank '
            'them and wind up. Asking the day again = the lead hangs up.]'
        )

    lead_question = intent in ("normal", "backchannel") and _lead_asked_question(_lt)
    if lead_question:
        parts.append(
            '[The lead just asked a QUESTION. Answer THAT first, in one '
            'short honest sentence, before anything else. Never invent '
            'prices, availability, or property details — if you don\'t '
            'have it, say the team will share exact details on WhatsApp. '
            'Only AFTER answering may you ask ONE follow-up question.]'
        )

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

    # KNOWN SLOTS — the extractor's per-turn output, surfaced to the model.
    # Without this, the model re-asked "which area?" after the lead had
    # already said "Anna Nagar" (the question order read as a script). The
    # qualify order is a PRIORITY LIST for what's missing, not a sequence.
    known_bits: list[str] = []
    if slots is not None:
        if getattr(slots, "product_interest", None):
            known_bits.append(f"requirement: {slots.product_interest}")
        if getattr(slots, "pain_point", None):
            known_bits.append(f"must-have: {slots.pain_point}")
        if getattr(slots, "timeline_days", None) is not None:
            known_bits.append(f"timeline: ~{slots.timeline_days} days")
    if known_bits:
        parts.append(
            "[ALREADY KNOWN — " + "; ".join(known_bits) + ". Do NOT ask "
            "about any of this again. Ask ONLY the single most important "
            "thing still missing (intent / locality / BHK / budget — in that "
            "priority). If nothing important is missing, propose the visit "
            "slot now (choice of two). If the lead gave several details in "
            "one breath, acknowledge once and jump ahead — never walk a "
            "script.]"
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
        if "hello" in lead_lc or "ஹலோ" in (lead_text or ""):
            # "Hello?" mid-call is a line check, not a listening ack — the
            # lead likely missed Priya's last line (call 3cfaeed8: Priya
            # answered "Hello" with her next qualifier; lead hung up).
            parts.append(
                '[Lead said "hello" MID-CALL — they are checking the line; '
                'they likely did NOT hear you. Confirm you are here in 2-3 '
                'words ("Yes sir, I\'m here" / "Haan sir, sun rahi hoon" / '
                '"Sollunga sir, naan line la irukken" — match call language), '
                'then repeat your LAST question in a SHORTER form. Do NOT '
                'move to a new question.]'
            )
        elif conv.backchannel_count >= 2:
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

    native = _native_script_for(lang)
    if intent == "close":
        if lang == "ta-IN":
            line = (
                '"சரி sir, இந்த number-கு WhatsApp-ல property details + site visit slot அனுப்புறேன், team confirm பண்ணுவாங்க. Thank you sir!"'
                if native else
                '"Sari sir, indha number ku WhatsApp la property details + site visit slot anuppuren, team confirm pannuvaanga. Thank you sir!"'
            )
            parts.append(f'Lead wants to CLOSE. Say ONLY: {line} Then STOP.')
        elif lang == "en-IN":
            parts.append('Lead wants to CLOSE. Say ONLY: "Got it sir, our team will send the property details + site visit slot on WhatsApp to this number. Thank you, sir!" Then STOP.')
        else:
            line = (
                '"बिल्कुल sir, इसी number पे WhatsApp पे property details और site visit slot भेज देती हूँ. Thank you!"'
                if native else
                '"Bilkul sir, isi number pe WhatsApp pe property details aur site visit slot bhej dete hain. Thank you!"'
            )
            parts.append(f'Lead wants to CLOSE. Say ONLY: {line} Then STOP.')
    elif intent == "reject":
        if conv.reject_count >= 2:
            if lang == "ta-IN":
                line = (
                    f'"சரி sir, நல்ல property தேடும்போது {co_ta}-கு call பண்ணுங்க. Thank you sir!"'
                    if native else
                    f'"Sari sir, naala property thedumbothu {co_ta}-ku call pannunga. Thank you sir!"'
                )
                parts.append(f'Still no. Warm exit: {line} Then STOP.')
            elif lang == "en-IN":
                parts.append(f'Still no. Warm exit: "No problem sir, whenever you start looking for a property do remember {co or "us"}. Good day!" Then STOP.')
            else:
                line = (
                    f'"कोई बात नहीं sir, घर देखना हो तो {co_hi} को याद रखिएगा. Good day!"'
                    if native else
                    f'"Koi baat nahi sir, ghar dekhna ho to {co_hi} yaad rakhiyega. Good day!"'
                )
                parts.append(f'Still no. Warm exit: {line} Then STOP.')
        else:
            if lang == "ta-IN":
                line = (
                    '"சரி sir. உங்க friend யாராவது வீடு தேடினா, இந்த number-கு சொல்லுங்க, நாங்க நல்லா site visit set பண்ணுவோம்."'
                    if native else
                    '"Sari sir. Ungal nanban yaaravadhu ghar or flat thedanna, indha number ku sollunga, naanga nalla site visit set pannuvom."'
                )
                parts.append(f"Lead not interested. Don't push — ask for a REFERRAL ONCE: {line}")
            elif lang == "en-IN":
                parts.append('Lead not interested. Don\'t push — ask for a REFERRAL ONCE: "No problem sir. If anyone you know is looking for a property, do share our number — we will arrange site visits for them."')
            else:
                line = (
                    '"कोई बात नहीं sir. आपके किसी जान-पहचान को घर ढूँढना हो तो बता दीजिए, हम site visit set कर देंगे?"'
                    if native else
                    '"Koi baat nahi sir. Aapke kisi jaan-pehchaan ko ghar dhoondhna ho to bata dijiye, hum site visit set kar denge?"'
                )
                parts.append(f"Lead not interested. Don't push — ask for a REFERRAL once: {line}")
    elif intent == "abuse":
        if lang == "ta-IN":
            parts.append(
                'Lead abusive. Say ONLY: "சரி sir, good day." Nothing else.'
                if native else
                'Lead abusive. Say ONLY: "Sari sir, good day." Nothing else.'
            )
        elif lang == "en-IN":
            parts.append('Lead abusive. Say ONLY: "Thank you sir, good day." Nothing else.')
        else:
            parts.append(
                'Lead abusive. Say ONLY: "ठीक है sir, good day." Nothing else.'
                if native else
                'Lead abusive. Say ONLY: "Theek hai sir, good day." Nothing else.'
            )
    elif intent == "wrong":
        if lang == "ta-IN":
            parts.append(
                'Wrong person / off-topic. Say ONLY: "Sorry sir, உங்க time எடுத்துட்டேன். Good day sir!" Then STOP.'
                if native else
                'Wrong person / off-topic. Say ONLY: "Sorry sir, ungal time waste pannitten. Good day sir!" Then STOP.'
            )
        elif lang == "en-IN":
            parts.append('Wrong person / off-topic. Say ONLY: "Sorry sir, took your time. Good day!" Then STOP.')
        else:
            parts.append(
                'Wrong person / off-topic. Say ONLY: "Sorry sir, आपका time लिया. Good day!" Then STOP.'
                if native else
                'Wrong person / off-topic. Say ONLY: "Sorry sir, aapka time liya. Good day!" Then STOP.'
            )
    elif intent == "offtopic":
        if conv.off_topic_count >= 2:
            if lang == "ta-IN":
                parts.append(
                    'Still off-topic. End: "சரி sir, good day sir!" STOP.'
                    if native else
                    'Still off-topic. End: "Sari sir, good day sir!" STOP.'
                )
            elif lang == "en-IN":
                parts.append('Still off-topic. End: "No problem sir, good day!" STOP.')
            else:
                parts.append(
                    'Still off-topic. End: "कोई बात नहीं sir, good day!" STOP.'
                    if native else
                    'Still off-topic. End: "Koi baat nahi sir, good day!" STOP.'
                )
        else:
            if lang == "ta-IN":
                parts.append(
                    'Lead off-topic. Probe ONCE: "Sir, உங்களுக்கு இப்போ வீடு தேடணும்-ஆ, இல்ல investment-கான property பாக்கறீங்களா sir?"'
                    if native else
                    'Lead off-topic. Probe ONCE: "Sir, ungalukku ipo ghar or flat thedanum-aa, illa investment-kana property paakareenga sir?"'
                )
            elif lang == "en-IN":
                parts.append('Lead off-topic. Probe ONCE: "Sir, are you actively looking for a home, or scouting for an investment property right now?"')
            else:
                parts.append(
                    'Lead off-topic. Probe ONCE: "Sir, अभी आप घर ढूँढ रहे हैं या investment के लिए property देख रहे हैं?"'
                    if native else
                    'Lead off-topic. Probe ONCE: "Sir, abhi aap ghar dhoondh rahe hain ya investment ke liye property dekh rahe hain?"'
                )
    else:
        # ---- Tire-kicker exit (5 unproductive turns in a row) ----
        # Threshold was 3 — too aggressive for Tamil/Hindi cold calls where
        # a real buyer often opens with 1-3 word replies ("haan", "achha",
        # "Anna Nagar") before warming up. 5 gives the lead a fair chance to
        # surface a slot. We also stop counting turns where the lead names
        # property info — see _mentions_property_info().
        if conv.unproductive_turn_count >= 5:
            if lang == "ta-IN":
                exit_phrase = (
                    f"சரி sir, உங்களுக்கு என்ன property வேணும்-னு confirm ஆனா, "
                    f"{co_ta}-கு call பண்ணுங்க, நான் help பண்றேன். Thank you sir!"
                    if native else
                    f"Sari sir, ungalukku enna property venum-nu confirm aana, {co_ta}-ku "
                    f"call pannunga, naan help pannuren. Thank you sir!"
                )
            elif lang == "en-IN":
                exit_phrase = (
                    f"No worries sir, whenever you have a specific property requirement, "
                    f"do remember {co or 'us'}. Thank you for your time, sir!"
                )
            else:
                exit_phrase = (
                    f"कोई बात नहीं sir, जब भी कोई specific property ढूँढनी हो, "
                    f"{co_hi} को याद रखिएगा. आपका time दिया, thank you sir!"
                    if native else
                    f"Koi baat nahin sir, jab bhi koi specific property dhoondhni ho, "
                    f"{co_hi} yaad rakhiyega. Aapka time diya, thank you sir!"
                )
            parts.append(
                f'[EXIT NOW. Lead is not a qualifying buyer ('
                f'{conv.unproductive_turn_count} short/non-info turns). '
                f'Say EXACTLY: "{exit_phrase}". Nothing else.]'
            )
            return "\n".join(parts)

        # ---- Close NOW (buying signals firm) ----
        # When the requirement is captured plus one more signal (must-have /
        # timeline / confidence), more discovery is dragging. Book the visit.
        # A pending lead question outranks the scripted close/heat lines —
        # "Say EXACTLY" over an unanswered question reads as a robot.
        if (
            conv.close_armed
            and conv.consecutive_close_attempts < 1
            and not lead_question
            and not slot_chosen  # slot picked → confirm path, not a re-offer
        ):
            if lang == "ta-IN":
                close_phrase = (
                    "சரி sir, matching properties இந்த number-கு WhatsApp-ல "
                    "அனுப்புறேன். Site visit-கு Saturday-ஆ Sunday-ஆ sir?"
                    if _native_script_for(lang) else
                    "Sari sir, matching properties indha number ku WhatsApp la "
                    "anuppuren. Site visit ku Saturday-aa, Sunday-aa sir?"
                )
            elif lang == "en-IN":
                close_phrase = (
                    "Got it sir — I'll WhatsApp the matching options to this "
                    "number. For the site visit, Saturday or Sunday?"
                )
            else:
                close_phrase = (
                    "बिल्कुल sir, matching options इसी number पे WhatsApp कर "
                    "दूँगी. Site visit के लिए Saturday ठीक रहेगा या Sunday?"
                    if _native_script_for(lang) else
                    "Bilkul sir, matching options isi number pe WhatsApp kar "
                    "doongi. Site visit ke liye Saturday theek rahega ya Sunday?"
                )
            parts.append(
                f'[CLOSE NOW. Lead gave hard requirements — stop discovery. '
                f'Say EXACTLY: "{close_phrase}". Nothing else.]'
            )
            return "\n".join(parts)

        # ---- Lead temperature — concrete sales directive every turn -----
        # Without an explicit temperature tag, the LLM treats every lead the
        # same: keep selling, keep asking. A real TN sales operator reads
        # heat instantly — hot leads get closed in the next sentence, warm
        # leads get ONE pain probe, cold leads get a warm goodbye. We surface
        # the heat here so Priya's next line matches the room.
        temperature = (
            "unknown"
            if (lead_question or slot_chosen)
            else slots.live_temperature(turn_idx=turn)
        )
        if temperature == "hot":
            if lang == "ta-IN":
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'சரி sir, matching properties WhatsApp-ல அனுப்புறேன். "
                    "Site visit-கு Saturday-ஆ Sunday-ஆ sir?']"
                    if _native_script_for(lang) else
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Sari sir, matching properties indha number ku WhatsApp la "
                    "anuppuren. Site visit ku Saturday-aa, Sunday-aa sir?']"
                )
            elif lang == "en-IN":
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Got it sir, I'll WhatsApp the matching options to this "
                    "number. For the site visit, Saturday or Sunday?']"
                )
            else:
                heat_directive = (
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'बिल्कुल sir, matching options WhatsApp पे भेज दूँगी — "
                    "site visit Saturday या Sunday?']"
                    if _native_script_for(lang) else
                    "[TEMPERATURE: HOT. Stop discovery. CLOSE this turn — "
                    "'Bilkul sir, matching options isi number pe WhatsApp kar "
                    "doongi. Site visit Saturday ya Sunday?']"
                )
            parts.append(heat_directive)
        elif temperature == "warm":
            if lang == "ta-IN":
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (budget / area / BHK / buy-vs-rent) in TAMIL — "
                    "start with 'Sari sir, ...' + the question. Build toward "
                    "the site-visit close, do NOT recite listings.]"
                )
            elif lang == "en-IN":
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (budget / locality / BHK / buy-vs-rent). Build "
                    "toward the site-visit close, do NOT recite listings.]"
                )
            else:
                parts.append(
                    "[TEMPERATURE: WARM. Lead is engaged. Ask the ONE missing "
                    "qualifier (budget / locality / BHK / buy-vs-rent). Build "
                    "toward the site-visit close, do NOT recite listings.]"
                )
        elif temperature == "cold":
            # No quoted example sentence here — llama parrots any quoted
            # line verbatim regardless of context (calls 43ea487c, 3cfaeed8).
            parts.append(
                "[TEMPERATURE: COLD. No buying signals after 3+ turns. "
                "ONE last attempt — ask ONE short concrete question about "
                "their area or budget, phrased to fit what the lead just "
                "said. If still no answer next turn, exit warmly.]"
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
            known.append(f"other broker they already use: {slots.current_supplier}")
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
