"""TenantConfig — the single source of per-client customization.

This is what makes Almmatix Voice a SaaS instead of a fork-per-client
codebase. Every place that used to reference "Supreme Petrochemicals"
or "Priya" or "chemicals industry" now reads from a TenantConfig.

Three layers of customization, all expressed here:

1. **Identity** — agent_name, company_name, city, default_lang, voice_id
2. **Pronunciation** — a per-tenant JSON file mapping spellings to
   phonemic hints (e.g. {"Bandra": "Baandra", "Powai": "Pow-eye"})
3. **Industry brain** — a Python module under `industry/` that owns
   the qualification slot schema, pain-point overlay prompt, and the
   end-of-call hook (book calendar, fire WhatsApp, etc.)

At call boot, the runtime fetches a TenantConfig by `tenant_id` and
hot-caches it for the call. Mid-call config edits do NOT take effect
until the next call — by design (avoids in-flight surprises).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class TenantConfig:
    """Per-tenant runtime configuration.

    Constructed from a row in the `tenants` Supabase table (see migration).
    `industry_key` selects which module under `industry/` runs the brain.
    """

    # --- identity ---
    tenant_id: str  # uuid string
    company_name: str  # e.g. "Supreme Petrochemicals", "Sunshine Realty"
    agent_name: str  # e.g. "Priya", "Anjali"
    city: str  # e.g. "Chennai", "Mumbai"
    default_lang: str  # BCP-47, e.g. "hi-IN"

    # --- voice ---
    voice_id_en: str  # provider voice ID for English
    voice_id_hi: str
    voice_id_ta: str

    # --- behaviour ---
    industry_key: str  # e.g. "chemicals", "real_estate"
    intro_overrides: Mapping[str, str] = field(default_factory=dict)
    # lang BCP-47 → custom intro template. If empty, industry brain default.

    # --- pronunciation pack ---
    pronunciation_pack: Mapping[str, str] = field(default_factory=dict)
    # e.g. {"Bandra": "Baandra", "SPC": "S-P-C"}

    # --- integrations (optional, empty disables that feature) ---
    google_calendar_id: str = ""  # e.g. "primary" or a calendar resource id
    whatsapp_phone_id: str = ""  # Meta Cloud API phone_number_id
    whatsapp_business_id: str = ""

    def has_calendar(self) -> bool:
        return bool(self.google_calendar_id)

    def has_whatsapp(self) -> bool:
        return bool(self.whatsapp_phone_id and self.whatsapp_business_id)


# Sentinel for "no tenant loaded — refuse to serve a call".
# Never expose this as a default; the WS handler MUST fetch a real tenant.
_UNCONFIGURED = TenantConfig(
    tenant_id="",
    company_name="",
    agent_name="",
    city="",
    default_lang="en-IN",
    voice_id_en="",
    voice_id_hi="",
    voice_id_ta="",
    industry_key="",
)


class TenantNotFound(LookupError):
    """Raised when a tenant_id cannot be resolved at call boot."""


# --- In-memory seed registry (Phase 1).
# Phase 2 replaces this with a Supabase `tenants` table fetch.
# Two seeded rows: the frozen SPC tenant (current behavior) and the
# demo real-estate broker tenant used to close week-1 clients.

_SEED: dict[str, TenantConfig] = {
    "spc-tenant": TenantConfig(
        tenant_id="spc-tenant",
        company_name="Supreme Petrochemicals",
        agent_name="Priya",
        city="Chennai",
        default_lang="hi-IN",
        voice_id_en="emily",
        voice_id_hi="anushka",
        voice_id_ta="anushka",
        industry_key="chemicals",
        pronunciation_pack={"SPC": "S-P-C"},
    ),
    "demo-broker-tenant": TenantConfig(
        tenant_id="demo-broker-tenant",
        company_name="Almmatix Realty Demo",
        agent_name="Priya",
        city="Mumbai",
        default_lang="hi-IN",
        voice_id_en="emily",
        voice_id_hi="anushka",
        voice_id_ta="anushka",
        industry_key="real_estate",
        pronunciation_pack={
            "Bandra": "Baandra",
            "Powai": "Pow-eye",
            "Andheri": "And-heri",
            "BHK": "B-H-K",
        },
    ),
}


def get_tenant(tenant_id: str) -> TenantConfig:
    """Resolve a tenant by id. Raises TenantNotFound for unknown ids.

    Phase 1: reads from the in-process seed dict above.
    Phase 2: will hit Supabase `tenants` table with a 60s in-process cache.
    """
    cfg = _SEED.get(tenant_id)
    if cfg is None:
        raise TenantNotFound(f"tenant_id={tenant_id!r} not in registry")
    return cfg


def register_tenant(cfg: TenantConfig) -> None:
    """Test helper. Production path goes through Supabase, not this."""
    _SEED[cfg.tenant_id] = cfg
