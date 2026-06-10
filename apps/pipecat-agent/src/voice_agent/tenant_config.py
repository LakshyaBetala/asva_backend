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
    google_refresh_token: str = ""  # per-tenant OAuth refresh token
    whatsapp_phone_id: str = ""  # Meta Cloud API phone_number_id
    whatsapp_business_id: str = ""
    whatsapp_access_token: str = ""  # Meta system-user permanent token
    whatsapp_template_name: str = "almmatix_demo_confirm"  # approved template

    def has_calendar(self) -> bool:
        return bool(self.google_calendar_id and self.google_refresh_token)

    def has_whatsapp(self) -> bool:
        return bool(
            self.whatsapp_phone_id
            and self.whatsapp_business_id
            and self.whatsapp_access_token
        )


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
    # The meta-tenant. Almmatix's own outbound — Priya rings up brokers
    # in North India and pitches them on hiring Priya. The product IS
    # the sales call. The close is a 15-min demo with the founder team.
    "almmatix-self-tenant": TenantConfig(
        tenant_id="almmatix-self-tenant",
        company_name="Almmatix",
        agent_name="Priya",
        city="Bangalore",  # where the brand is based; not the broker's city
        default_lang="hi-IN",  # North India default
        voice_id_en="emily",
        voice_id_hi="anushka",
        voice_id_ta="anushka",  # unused — brain rejects ta-IN
        industry_key="voice_agent_sales",
        pronunciation_pack={
            # Brand + product nouns the TTS must pronounce cleanly
            "Almmatix": "All-matix",
            "Laksh": "Laksh",
            "Betala": "Beh-ta-la",
            "Priya": "Priyaa",
            # Product terms (no rupee amounts — Priya never quotes prices)
            "BHK": "B-H-K",
            "CRM": "C-R-M",
            "API": "A-P-I",
            "EMI": "E-M-I",
            "GST": "G-S-T",
            "RERA": "Rera",
            "demo": "demo",
            # Competitor / channel nouns we name in the script
            "Magicbricks": "Magic-bricks",
            "99acres": "ninety-nine acres",
            "WhatsApp": "Whats-app",
            "NoBroker": "No-broker",
            # North India localities (Delhi NCR, Punjab, UP, Rajasthan)
            "Gurgaon": "Gur-gaon",
            "Gurugram": "Guru-gram",
            "Noida": "No-ee-da",
            "Greater Noida": "Greater No-ee-da",
            "Faridabad": "Faridabad",
            "Ghaziabad": "Gha-ziabad",
            "Dwarka": "Dwarka",
            "Saket": "Saa-ket",
            "Vasant Kunj": "Vasant Kunj",
            "Hauz Khas": "Hoz Khas",
            "Connaught Place": "Connaught Place",
            "Karol Bagh": "Karol Bagh",
            "Lajpat Nagar": "Lajpat Nagar",
            "Rohini": "Ro-hini",
            "Pitampura": "Pitam-pura",
            "Chandigarh": "Chandi-garh",
            "Mohali": "Moh-ali",
            "Panchkula": "Panch-kula",
            "Lucknow": "Luck-now",
            "Gomti Nagar": "Gomti Nagar",
            "Jaipur": "Jai-pur",
            "Mansarovar": "Man-sarovar",
            "Vaishali Nagar": "Vaishali Nagar",
        },
    ),
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
        company_name="XYZ Broker",
        agent_name="Priya",
        city="Chennai",
        default_lang="hi-IN",
        voice_id_en="emily",
        voice_id_hi="anushka",
        voice_id_ta="anushka",  # unused for brokers — see real_estate brain
        industry_key="real_estate",
        # Pronunciation hints drive Sarvam Bulbul TTS phoneme bias for
        # Indian property nouns. Mapped values use the spelling shape the
        # TTS already pronounces well; the engine substitutes on render.
        # Keep these *short* — long substitutions break the prosody.
        pronunciation_pack={
            # MINIMAL pack — Indian TTS engines handle Adyar/Velachery/
            # Mylapore/T.Nagar/Bandra/Powai/BHK NATIVELY. The only override
            # we keep is XYZ → phonetic, because TTS cannot guess "ksyz" vs
            # "ex-why-zee". Everything else is left to native TTS handling.
            #
            # History of broken overrides (do NOT re-add):
            #   "BHK": "B-H-K"           → call 24ae751d: "bee dash aitch dash kay"
            #   "BHK": "bee aitch kay"   → call 42282a3b: user heard "BHKI"
            #   "Adyar": "Ad-yar"        → call 27e1a582: "ad dash yar"
            #   "XYZ": "X Y Z"           → call 24ae751d: garbled
            "XYZ Broker": "Eks Why Zee Broker",
            "XYZ": "Eks Why Zee",
            "sqft": "square feet",
            "RERA": "Rera",
        },
    ),
}


def get_tenant(tenant_id: str) -> TenantConfig:
    """Resolve a tenant by id.

    DEMO-DAY OVERRIDE (2026-06-08): force every call to use the broker
    tenant, regardless of incoming tenant_id. Restores real_estate brain
    + property-flavoured prompts for the recording session. Revert after
    demos are captured.
    """
    cfg = _SEED["demo-broker-tenant"]
    print(
        f"[get_tenant OVERRIDE] requested={tenant_id!r} -> "
        f"returning company={cfg.company_name!r} city={cfg.city!r} "
        f"industry={cfg.industry_key!r}",
        flush=True,
    )
    return cfg


def register_tenant(cfg: TenantConfig) -> None:
    """Test helper. Production path goes through Supabase, not this."""
    _SEED[cfg.tenant_id] = cfg
