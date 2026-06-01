-- tenants: one row per customer organization
create extension if not exists "uuid-ossp";

create table public.tenants (
  id                      uuid primary key default uuid_generate_v4(),
  name                    text not null,
  slug                    text not null unique,
  persona_name            text not null default 'Priya',
  persona_lang_default    text not null default 'en-IN'
                          check (persona_lang_default in ('en-IN','hi-IN','ta-IN')),
  samvaad_agent_id        text,
  exotel_caller_id        text,
  whatsapp_handoff_number text,
  created_at              timestamptz not null default now()
);

create index tenants_slug_idx on public.tenants (slug);
comment on table public.tenants is 'Customer organizations using the voice agent (e.g. SPC).';
