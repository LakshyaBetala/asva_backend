"""System-prompt assembly with per-turn language injection.

The Priya system prompt lives at
`packages/shared/src/prompts/priya-system.md`. We load it once at agent
startup and inject `<current_language>...</current_language>` per turn
so the LLM stops drifting back to the prior-language context after a
state-machine switch.

The intro-text builder reads from the per-call TenantConfig + IndustryBrain,
so a chemicals tenant gets "Supreme Petrochemicals" and a real-estate
tenant gets the broker pitch — same code path, different config row.

Parity note: packages/shared/src/intro-cache.ts is the TS twin used by
the web/Node cache. Until that's migrated to tenant-aware lookup, the
TS side returns the legacy SPC strings. The Python runtime is the source
of truth for what Exotel actually plays; the TS cache is a hot-path
optimization that falls back to live synth on miss.
"""
from __future__ import annotations

import re
from pathlib import Path

from voice_agent.industry import get_brain
from voice_agent.tenant_config import TenantConfig

# Resolved at import time. Override in tests via load_priya_prompt(path=...).
_DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "shared"
    / "src"
    / "prompts"
    / "priya-system.md"
)

_PLACEHOLDER_RE = re.compile(r"^(unknown|n/?a|test|na)$", re.IGNORECASE)


def load_priya_prompt(path: Path | None = None) -> str:
    """Read priya-system.md as the base system prompt."""
    p = path or _DEFAULT_PROMPT_PATH
    return p.read_text(encoding="utf-8")


def is_usable_first_name(name: str | None) -> bool:
    if not name:
        return False
    trimmed = name.strip()
    return len(trimmed) >= 2 and not _PLACEHOLDER_RE.match(trimmed)


def build_intro_text(
    *,
    tenant: TenantConfig,
    lang: str,
    first_name: str | None,
) -> str:
    """Render the opening line for this tenant + language + lead.

    The industry brain owns the language-specific template (with a
    `{name}` placeholder); this function fills the name slot. A usable
    first name produces "Haan Naman ji, namaste! ..."; an empty/placeholder
    name swaps in a neutral honorific ("Namaste sir! ...").
    """
    name = first_name.strip() if is_usable_first_name(first_name) else ""
    brain = get_brain(tenant.industry_key)
    template = brain.intro_template(lang, tenant)

    # Swap the `{name}` slot. The placeholder is followed by a space + the
    # next word in the template ("Haan {name} ji"), so an empty name leaves
    # a double-space — fix that in one pass.
    if name:
        rendered = template.replace("{name}", name)
    else:
        # Drop "{name} " entirely. Falls back to a neutral honorific phrase
        # in the template if present, else just removes the slot cleanly.
        rendered = (
            template.replace("{name} ", "")
            .replace(" {name}", "")
            .replace("{name}", "")
        )
        # Per-lang neutral lead-in when the template's opener was name-shaped.
        if lang == "hi-IN" and rendered.startswith("Haan ji"):
            rendered = rendered.replace("Haan ji, namaste!", "Namaste sir!", 1)
        elif lang == "en-IN" and rendered.startswith("Hi, "):
            pass  # already neutral
        elif lang == "ta-IN" and rendered.startswith("Vanakkam sir"):
            pass  # already neutral

    return rendered


def build_system_message(
    *,
    base_prompt: str,
    current_language: str,
    lead_first_name: str | None,
    lead_company: str | None,
) -> str:
    """Assemble the per-turn system message.

    Injecting <current_language> is the cure for LLM drift after a
    state-machine switch — without this, the model often keeps replying
    in the original language for several turns post-switch.
    """
    name = lead_first_name.strip() if is_usable_first_name(lead_first_name) else ""
    company = (lead_company or "").strip()
    header = (
        f"<lang>{current_language}</lang> <lead>{name}</lead> <company>{company}</company>\n"
    )
    return header + base_prompt
