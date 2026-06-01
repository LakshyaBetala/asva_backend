create table public.lead_scores (
  id                  uuid primary key default uuid_generate_v4(),
  lead_id             uuid not null references public.leads on delete cascade,
  call_id             uuid not null references public.calls on delete cascade,
  classification      text not null check (classification in ('hot','warm','cold')),
  score_0_100         int not null check (score_0_100 between 0 and 100),
  reason              text not null,
  summary             text not null,
  next_action         text,
  extracted           jsonb not null default '{}'::jsonb,
  call_quality_flags  text[] not null default '{}',
  scored_at           timestamptz not null default now(),
  unique (call_id)
);
create index lead_scores_lead_idx on public.lead_scores (lead_id);
alter publication supabase_realtime add table public.lead_scores;

create table public.handoffs (
  id          uuid primary key default uuid_generate_v4(),
  lead_id     uuid not null references public.leads on delete cascade,
  call_id     uuid references public.calls on delete set null,
  channel     text not null check (channel in ('whatsapp','email')),
  sent_to     text not null,
  sent_at     timestamptz not null default now(),
  opened_at   timestamptz
);
create index handoffs_lead_idx on public.handoffs (lead_id);

create table public.dnc_list (
  tenant_id   uuid not null references public.tenants on delete cascade,
  phone_e164  text not null,
  reason      text,
  added_at    timestamptz not null default now(),
  primary key (tenant_id, phone_e164)
);
