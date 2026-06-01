-- Per-call qualification data extracted live by the voice agent.
-- One row per call, updated each turn as Priya extracts more signal.
-- Used by the live scoring worker + CRM lead detail page.

create table public.qualification_slots (
  call_id             uuid primary key references public.calls on delete cascade,
  tenant_id           uuid not null references public.tenants on delete cascade,
  lead_id             uuid not null references public.leads on delete cascade,

  product_interest    text,
  volume_monthly_kg   int,
  buying_frequency    text check (buying_frequency in ('one_off','monthly','ad_hoc','unknown')),
  current_supplier    text,
  pain_point          text,
  decision_role       text check (decision_role in ('owner','procurement','engineer','assistant','unknown')),
  timeline_days       int,
  buying_confidence   numeric(3,2) check (buying_confidence >= 0 and buying_confidence <= 1),

  -- Per-slot confidence (LLM self-rated 0..1). Helps the CRM show "extracted but uncertain".
  slot_confidence     jsonb not null default '{}'::jsonb,

  -- Last turn that updated this row. Used for "Qualification still updating" UI state.
  last_turn_idx       int not null default 0,
  updated_at          timestamptz not null default now()
);

create index qualification_slots_tenant_lead_idx
  on public.qualification_slots (tenant_id, lead_id);

comment on table public.qualification_slots is
  'Live-updated qualification data per call. Powers Hot/Warm/Cold scoring and CRM detail panel.';
comment on column public.qualification_slots.buying_confidence is
  'LLM-inferred buying intent on a 0..1 scale. >=0.7 + decision_role + timeline => Hot.';
comment on column public.qualification_slots.slot_confidence is
  'Per-slot 0..1 confidence map, e.g. {"volume_monthly_kg": 0.4, "timeline_days": 0.9}. CRM uses to dim uncertain slots.';

alter table public.qualification_slots enable row level security;

create policy qualification_slots_tenant_read   on public.qualification_slots
  for select using (tenant_id = public.current_tenant_id());
create policy qualification_slots_tenant_insert on public.qualification_slots
  for insert with check (tenant_id = public.current_tenant_id());
create policy qualification_slots_tenant_update on public.qualification_slots
  for update using (tenant_id = public.current_tenant_id());
