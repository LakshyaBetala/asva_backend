-- Master agent ON/OFF + BYON (Bring Your Own Number) support.
-- BYON credentials live in Supabase Vault; tenants holds only the secret ref.

alter table public.tenants
  add column agent_enabled bool not null default true,
  add column telephony_mode text not null default 'managed'
    check (telephony_mode in ('managed','byon')),
  add column byon_provider text
    check (byon_provider in ('exotel','plivo','tata')),
  add column byon_from_number text,
  add column byon_credentials_ref uuid;

comment on column public.tenants.agent_enabled is
  'Master switch. When false, dispatch refuses to start new outbound calls.';
comment on column public.tenants.telephony_mode is
  'managed = we route via our Plivo trunk; byon = tenant supplies provider+from_number+credentials_ref.';
comment on column public.tenants.byon_credentials_ref is
  'UUID into vault.secrets. The secret JSON shape is {sid, token}. Never store credentials in this table directly.';
