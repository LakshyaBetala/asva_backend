"""Deliberate language state machine for multilingual Indian calls.

Why this exists
---------------
Naive auto-detect-and-respond fails on Indian calls. A single one-word
reply like "haan" or "okay" mis-flips the agent's language for the rest
of the turn — the lead notices and the call dies.

This state machine layers on top of Sarvam STT's per-utterance language
tag and applies five rules:

  1. STT confidence below `MIN_LANG_CONFIDENCE` is ignored — keep state.
  2. State flips only after `SWITCH_HYSTERESIS` consecutive full-utterances
     in the new language. One-word utterances do NOT count toward the
     hysteresis even if confident.
  3. Explicit code-switch trigger phrases ("Hindi mein bolo", "speak in
     English", "Tamil-la pesa mudiyuma") flip state instantly.
  4. Code-mixed input (Hinglish, Tanglish) does NOT trigger a flip — it
     reports back the dominant language for response selection.
  5. The state machine emits an explicit `switch_bridge_phrase` event
     when a flip happens, so the pipeline can play "Sure, English mein
     bolte hain" before responding in the new language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Lang(str, Enum):
    EN = "en-IN"
    HI = "hi-IN"
    TA = "ta-IN"


# Threshold below which STT's language tag is treated as "unknown" — we
# don't act on noisy detection. Sarvam returns 0..1 confidence.
MIN_LANG_CONFIDENCE: float = 0.75

# Number of consecutive same-language full utterances required to flip.
# Set to 2: once we're in a language, a single stray utterance in another
# tongue (often a misdetect of code-mix or a loanword-heavy Tamil reply
# tagged hi-IN) shouldn't flip us back. Real switches show up across two
# full turns anyway. Marker-overrides bypass this when morphology is clear.
SWITCH_HYSTERESIS: int = 2

# Word count above which an utterance counts as "full" for hysteresis.
# 3+ words means the lead said more than a backchannel acknowledgement.
FULL_UTTERANCE_MIN_WORDS: int = 3


# Strong language-marker words. When Sarvam mis-tags a Tamil-heavy utterance
# as Hindi (or vice versa), these tokens override the STT tag. Pattern-matched
# as whole words, lowercase. Keep highly distinctive — common cross-language
# words (haan, ji, ok) do NOT belong here.
_TAMIL_MARKERS: frozenset[str] = frozenset({
    "irukku", "irukka", "irukken", "panren", "pannuren", "pannunga",
    "tharen", "tharaen", "tharudhu", "vaanga", "varum", "varudhu",
    "puriyala", "puriyalai", "puriyutha", "kekkala", "sariya",
    "epdi", "yepdi", "enna", "evvalavu", "anuppu", "anuppunga",
    "paesalama", "paesalaam", "ungalukku", "engaluku", "athunaala",
    "kandippa", "paathaachu", "paathuren", "paarunga", "paarungalen",
    "thirumba", "sollunga", "sonnel", "sonninga", "sonneenga",
    "venum", "venam", "naan", "naangal", "pesunga", "pesungo",
    "kitta", "dhaan", "iduku", "aduku", "enakku", "yenakku",
    "panreen", "panneenga", "pannittu", "vechu", "kondu", "ille",
    "illa-nu", "solren", "sonnen",
})
_HINDI_MARKERS: frozenset[str] = frozenset({
    "bilkul", "kijiye", "dijiye", "karenge", "karenga", "karungi",
    "achha", "accha", "matlab", "isiliye", "kyunki", "lekin", "magar",
    "bhaiya", "behen", "sahab", "saab", "bataiye", "bataye", "boliye",
    "dekhiye", "samjhaiye", "samjhaye", "kahiye", "rahiye", "jaiye",
    "aaiye", "padhiye", "lijiye", "leejiye", "bhejiye", "bhej",
})


# Minimum word count before a marker is allowed to flip language. A lone
# "sari" or "achha" is a backchannel ack, not a language signal.
_MARKER_MIN_WORDS: int = 3


# Unicode script ranges. The presence of even one Tamil or Devanagari
# character is a high-precision lang signal — way more reliable than
# Sarvam's `lang_code` field, which mislabels Tamil audio as hi-IN when
# the request hint was hi-IN. Run BEFORE marker scan + STT tag.
_TAMIL_SCRIPT_RE = re.compile(r"[஀-௿]")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


# Short acknowledgement tokens across the scripts Sarvam's streaming STT
# actually emits for them. A lead's "hmm / ok / haan / theek hai" gets
# transcribed in whatever script the model's language guess picked THAT
# utterance — call 56e606ca logged "ம்." (Tamil), "ઓકે."/"હા." (Gujarati),
# "ఓకే అండి." (Telugu) for what was plain Hindi/English backchannel. These
# must never count as a language signal (and intent-wise they are
# backchannels — see streaming_orchestrator._is_backchannel).
BACKCHANNEL_ACK_TOKENS: frozenset[str] = frozenset({
    # Roman
    "acha", "achha", "accha", "achchha", "achaa", "haan", "han", "haa",
    "hmm", "hm", "mm", "mmm", "hmmm", "ok", "okay", "okk", "theek", "thik",
    "sahi", "right", "ji", "sari", "seri", "aama", "yes", "yeah", "yep",
    "bilkul", "sure", "fine", "hello", "haanji",
    # Devanagari
    "हाँ", "हां", "हा", "जी", "ठीक", "है", "अच्छा", "अच्छी", "ओके", "ओक",
    "हूँ", "हम्म", "सही", "बिल्कुल", "सर", "मैडम",
    # Tamil
    "ம்", "ம்ம்", "ஓகே", "ஒகே", "சரி", "ஆமா", "ஆமாம்", "ஹா", "சார்", "சர்",
    # Gujarati
    "ઓકે", "હા", "ઠીક", "સારું", "જી",
    # Telugu
    "ఓకే", "ఒకే", "సరే", "హా", "అవును", "అండి", "సర్",
    # Kannada / Malayalam (same misdetect class)
    "ಸರಿ", "ಹೌದು", "ഓകെ", "ശരി",
})


def is_bare_ack(text: str) -> bool:
    """True when the utterance is ONLY acknowledgement tokens (any script).

    "ઓકે." / "अच्छा ठीक है।" / "hmm ok" → True. Anything carrying real
    content ("ठीक है, Saturday chalega") → False.
    """
    # \w alone would strip Indic combining marks (viramas/matras) and shred
    # "अच्छा" into "अच छा" — keep the full Indic blocks (U+0900-U+0D7F)
    # intact and only punctuation becomes a separator. The danda (।/॥) lives
    # INSIDE the Devanagari block, so it needs its own separator rule.
    words = re.sub(r"[^\w\sऀ-ൿ]|[।॥]", " ", text).split()
    if not words or len(words) > 4:
        return False
    return all(w.lower() in BACKCHANNEL_ACK_TOKENS for w in words)


def _script_override(text: str) -> Lang | None:
    """Detect language from Unicode script in the transcript.

    Tamil (U+0B80-U+0BFF) and Devanagari (U+0900-U+097F) are unambiguous
    signals — a single character is enough. Returns None for ASCII-only
    text (could be English, romanized Hindi, or romanized Tamil — falls
    through to STT tag / marker scan).
    """
    if _TAMIL_SCRIPT_RE.search(text):
        return Lang.TA
    if _DEVANAGARI_RE.search(text):
        return Lang.HI
    return None


def _marker_override(text: str) -> Lang | None:
    """Whole-word marker scan that overrides Sarvam's STT lang tag.

    A genuine Tamil utterance with Hindi-loanwords ("haan rate-uh sollunga
    sir") can come back tagged hi-IN. The presence of Tamil-distinctive
    morphology ("sollunga") should pull us back. Returns the overridden
    language if exactly one side has markers AND the utterance has enough
    surrounding words to be a real sentence (not a one-word ack).
    """
    words = re.findall(r"[a-z]+", text.lower())
    if len(words) < _MARKER_MIN_WORDS:
        return None
    ta = any(w in _TAMIL_MARKERS for w in words)
    hi = any(w in _HINDI_MARKERS for w in words)
    if ta and not hi:
        return Lang.TA
    if hi and not ta:
        return Lang.HI
    return None


# Explicit "switch language now" trigger phrases. These bypass hysteresis.
# Patterns are case-insensitive substring matches on the lead's utterance.
# Keep this list short and high-precision — false positives break the call.
_TRIGGER_PHRASES: dict[Lang, tuple[str, ...]] = {
    Lang.EN: (
        "speak in english",
        "english mein bolo",
        "english-la pesunga",
        "can we speak english",
        "can i speak in english",
        "talk in english",
        "english please",
        "in english please",
        # Native-script: pinned STT returns Devanagari/Tamil, so the lead's
        # request "इंग्लिश में बात करो" came back in script the romanized
        # forms above never matched (call 2809a134).
        "इंग्लिश में बोल", "इंग्लिश में बात", "अंग्रेज़ी में बोल",
        "ஆங்கிலத்தில் பேசு", "இங்கிலீஷ்ல பேசு",
    ),
    Lang.HI: (
        "hindi mein bolo",
        "hindi mein baat karo",
        "speak in hindi",
        "talk in hindi",
        "switch to hindi",
        "can i speak in hindi",
        "hindi-la pesunga",
        "hindi please",
        "in hindi please",
        "हिंदी में बोल", "हिंदी में बात", "हिन्दी में बोल", "हिन्दी में बात",
        "ஹிந்தில பேசு", "இந்தியில் பேசு",
    ),
    Lang.TA: (
        "tamil-la pesunga",
        "tamil le pesla",
        "tamil la pesla",
        "tamil mein bolo",
        "tamil mein baat karo",
        "speak in tamil",
        "talk in tamil",
        "switch to tamil",
        "can we speak in tamil",
        "can i speak in tamil",
        "tamizh-la pesunga",
        "tamizh le pesla",
        "tamil pesalama",
        "tamizh pesalama",
        "tamil please",
        "in tamil please",
        # Native-script (Devanagari "तमिल में बोल" was the exact miss in
        # call 2809a134, and Tamil-script for a lead already part-switched).
        "तमिल में बोल", "तमिल में बात", "तमिऴ में बोल",
        "தமிழ்ல பேசு", "தமிழில் பேசு", "தமிழ்ல பேசுங்க", "தமிழ் பேசுங்க",
    ),
}


# Spelling-robust language-request detection. Fixed _TRIGGER_PHRASES miss
# STT spelling variants (இங்கிலீஷில் vs இங்கிலீஷ்ல, ingilish vs english);
# this matches a language NAME stem in ANY script + a "speak/talk/change"
# cue, so "English-la sollunga", "हिंदी में बोल", "தமிழ்ல பேசுங்க",
# "can we continue in english" all flip. Cue required to avoid false
# positives like "I read a Tamil paper".
_LANG_NAME_RE: dict[Lang, "re.Pattern[str]"] = {
    Lang.EN: re.compile(r"english|ingl|ஆங்கில|இங்கில|இங்லீ|अंग्रेज|इंग्ल|इंगल", re.I),
    Lang.HI: re.compile(r"hindi|हिंदी|हिन्दी|இந்தி|ஹிந்தி|हिंद", re.I),
    Lang.TA: re.compile(r"tamil|tamizh|தமிழ|தமில|तमिल|तमिळ", re.I),
}
_LANG_REQUEST_CUE_RE = re.compile(
    r"pes|sollu|sollung|bol|baat|talk|speak|continue|chang|maath|maatu|"
    r"please|chahiye|switch|बोल|बात|करो|कर दो|में|पेसु|"
    # Tamil script: சொல்லு (tell), பேச (speak), மாற்/மாத்து (change),
    # பண்ண (do), + Tamil-script English loans ப்ளீஸ்/டாக்/ஸ்பீக். (No bare
    # "-la/-il" locative cue — "il\b" matched the END of "tamil" itself and
    # over-triggered; real requests carry a verb cue or are short anyway.)
    r"சொல்லு|பேச|மாத்து|மாற்|பண்ண|ப்ளீஸ்|டாக்|ஸ்பீக்",
    re.I,
)


def _detect_lang_request(text: str, current: "Lang") -> "Lang | None":
    if not text:
        return None
    low = text.lower()
    has_cue = bool(_LANG_REQUEST_CUE_RE.search(text)) or len(low.split()) <= 4
    if not has_cue:
        return None
    for lang, name_re in _LANG_NAME_RE.items():
        if lang == current:
            continue
        if name_re.search(text):
            return lang
    return None


# Smooth bridge phrases — said in the OLD language before switching to the
# new one. Avoids the jarring snap of mid-sentence language flip.
_BRIDGE_PHRASES: dict[tuple[Lang, Lang], str] = {
    (Lang.EN, Lang.HI): "Bilkul, Hindi mein baat karte hain.",
    (Lang.EN, Lang.TA): "Sari, Tamil-la pesalam.",
    (Lang.HI, Lang.EN): "Sure, let's talk in English.",
    (Lang.HI, Lang.TA): "Sari, Tamil-la pesalam.",
    (Lang.TA, Lang.EN): "Sure, let's talk in English.",
    (Lang.TA, Lang.HI): "Bilkul, Hindi mein baat karte hain.",
}


@dataclass
class STTUtterance:
    """One finalised utterance from Sarvam STT."""

    text: str
    lang: Lang | None  # None when STT confidence too low to tag
    confidence: float  # 0..1; Sarvam returns this per utterance
    is_code_mixed: bool = False  # true when STT flags Hinglish/Tanglish


@dataclass
class Transition:
    """Result of feeding one utterance through the state machine."""

    current_language: Lang
    switched: bool
    trigger: Literal["initial", "hysteresis", "explicit", "none"]
    bridge_phrase: str | None  # set when switched=True, except on initial


@dataclass
class LanguageState:
    """Per-call language state. Construct one instance per call."""

    current: Lang
    pending_lang: Lang | None = None
    pending_count: int = 0
    _history: list[STTUtterance] = field(default_factory=list)

    @classmethod
    def initial(cls, default_lang: Lang) -> LanguageState:
        return cls(current=default_lang)

    def _word_count(self, text: str) -> int:
        return len([w for w in re.split(r"\s+", text.strip()) if w])

    def _detect_trigger(self, text: str) -> Lang | None:
        normalized = text.lower().strip()
        for lang, phrases in _TRIGGER_PHRASES.items():
            for p in phrases:
                if p in normalized:
                    return lang
        # Spelling-robust fallback: a language NAME (any script/spelling) +
        # a request cue. Fixed phrases miss STT spelling variants — call
        # b850a198 the lead said "நம்ம இங்கிலீஷில் பேசலாம்" / "English-la
        # sollunga" and neither matched, so the call never switched.
        return _detect_lang_request(text, self.current)

    def _flip(self, to: Lang, trigger: Literal["hysteresis", "explicit"]) -> Transition:
        prev = self.current
        bridge = _BRIDGE_PHRASES.get((prev, to))
        self.current = to
        self.pending_lang = None
        self.pending_count = 0
        return Transition(
            current_language=to,
            switched=True,
            trigger=trigger,
            bridge_phrase=bridge,
        )

    def update(self, utt: STTUtterance) -> Transition:
        """Feed one STT utterance; return the resulting transition."""
        self._history.append(utt)

        # Rule 3 (highest priority): explicit trigger phrase.
        trigger_lang = self._detect_trigger(utt.text)
        if trigger_lang and trigger_lang != self.current:
            return self._flip(trigger_lang, "explicit")

        # Unicode-script override: Tamil/Devanagari characters in the
        # transcript are decisive regardless of STT confidence or lang_code.
        # This catches the very common case of Sarvam tagging Tamil audio
        # as hi-IN when the request hint was hi-IN (the script in the text
        # tells the truth even when the label lies).
        #
        # GATED for short utterances: the streaming STT hallucinates a random
        # script for one-word backchannels ("ம்." for "hmm", "हाँ" for an
        # English "yeah") — call 56e606ca went Tanglish off a single "ம்.".
        # A real language switch always arrives as a full sentence.
        script = _script_override(utt.text)
        if script is not None:
            if script == self.current:
                # Same as current — reset any drifting pending counter and stop.
                self.pending_lang = None
                self.pending_count = 0
                return Transition(self.current, False, "none", None)
            if self._word_count(utt.text) >= 2 and not is_bare_ack(utt.text):
                # One foreign-script sentence is a VOTE, not a flip. The
                # streaming STT regularly transcribes ENGLISH speech in
                # Indic script — call 9ed9a612 rendered "I am looking for
                # 3 BHK" as "ஐ அம் லுக்கிங் ஃபார் 3 பிஹெச்கே" and the old
                # instant flip sent an English call into Tanglish. A real
                # switcher produces script on consecutive turns; a one-off
                # is the STT mishearing.
                if self.pending_lang == script:
                    self.pending_count += 1
                else:
                    self.pending_lang = script
                    self.pending_count = 1
                if self.pending_count >= SWITCH_HYSTERESIS:
                    return self._flip(script, "explicit")
            # Foreign-script bare ack / one-worder: STT misdetect, keep state.
            return Transition(self.current, False, "none", None)

        # Marker-token override: if morphology unambiguously identifies a
        # language (e.g. "pesunga"/"irukku" = Tamil, "kijiye"/"bilkul" = Hindi),
        # bypass hysteresis and flip immediately. Markers are high-precision
        # so we trust them more than Sarvam's lang tag. This is what protects
        # a Tamil-with-loanwords reply from being mis-tagged hi-IN and
        # flipping us back. Gated by STT confidence — at low conf the text
        # itself can be a hallucination, so don't trust marker words inside.
        marker = (
            _marker_override(utt.text)
            if utt.confidence >= MIN_LANG_CONFIDENCE
            else None
        )
        if marker is not None and marker != self.current:
            return self._flip(marker, "explicit")
        if marker is not None:
            self.pending_lang = None
            self.pending_count = 0
            return Transition(self.current, False, "none", None)

        effective_lang = utt.lang

        # Rule 1: low STT confidence → ignore detection.
        if utt.confidence < MIN_LANG_CONFIDENCE or effective_lang is None:
            return Transition(self.current, False, "none", None)

        # Rule 4: code-mixed → don't change state, just keep dominant.
        if utt.is_code_mixed:
            return Transition(self.current, False, "none", None)

        # Already in detected language → reset any pending counter.
        if effective_lang == self.current:
            self.pending_lang = None
            self.pending_count = 0
            return Transition(self.current, False, "none", None)

        # Rule 2: hysteresis. Require N consecutive FULL utterances.
        is_full = self._word_count(utt.text) >= FULL_UTTERANCE_MIN_WORDS
        if not is_full:
            # Short utterance in a new language — don't count toward switch.
            return Transition(self.current, False, "none", None)

        if self.pending_lang == effective_lang:
            self.pending_count += 1
        else:
            self.pending_lang = effective_lang
            self.pending_count = 1

        if self.pending_count >= SWITCH_HYSTERESIS:
            return self._flip(effective_lang, "hysteresis")

        return Transition(self.current, False, "none", None)


def get_response_language_hint(state: LanguageState) -> Lang:
    """Public helper for the LLM/TTS pipeline to know what to respond in."""
    return state.current
