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
-- users: app-level profile pinned to auth.users
create table public.users (
  id          uuid primary key references auth.users on delete cascade,
  tenant_id   uuid not null references public.tenants on delete restrict,
  email       text not null,
  full_name   text,
  role        text not null check (role in ('admin','rep')),
  whatsapp    text,
  created_at  timestamptz not null default now()
);

create index users_tenant_idx on public.users (tenant_id);

-- JWT custom-claims hook: injects tenant_id + role into the access token.
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
as $$
declare
  claims        jsonb;
  v_tenant_id   uuid;
  v_role        text;
begin
  claims := coalesce(event->'claims', '{}'::jsonb);

  select tenant_id, role into v_tenant_id, v_role
  from public.users
  where id = (event->>'user_id')::uuid;

  if v_tenant_id is not null then
    claims := jsonb_set(claims, '{tenant_id}', to_jsonb(v_tenant_id::text));
    claims := jsonb_set(claims, '{role}',      to_jsonb(v_role));
  end if;

  event := jsonb_set(event, '{claims}', claims);
  return event;
end;
$$;

grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
create table public.leads (
  id           uuid primary key default uuid_generate_v4(),
  tenant_id    uuid not null references public.tenants on delete cascade,
  name         text not null,
  phone_e164   text not null,
  company      text,
  industry     text,
  source       text,
  notes        text,
  status       text not null default 'new'
               check (status in ('new','queued','calling','called',
                                 'hot','warm','cold','do_not_call','needs_review')),
  assigned_to  uuid references public.users on delete set null,
  created_at   timestamptz not null default now(),
  unique (tenant_id, phone_e164)
);

create index leads_tenant_status_idx on public.leads (tenant_id, status);
create index leads_assigned_idx       on public.leads (assigned_to);
create table public.campaigns (
  id              uuid primary key default uuid_generate_v4(),
  tenant_id       uuid not null references public.tenants on delete cascade,
  name            text not null,
  script_version  int not null default 1,
  created_by      uuid references public.users on delete set null,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now()
);
create index campaigns_tenant_idx on public.campaigns (tenant_id);

create table public.calls (
  id                  uuid primary key default uuid_generate_v4(),
  tenant_id           uuid not null references public.tenants on delete cascade,
  lead_id             uuid not null references public.leads on delete cascade,
  campaign_id         uuid references public.campaigns on delete set null,
  samvaad_call_id     text unique,
  status              text not null default 'queued'
                      check (status in ('queued','ringing','in_progress','completed',
                                        'failed','voicemail','no_answer')),
  kind                text not null default 'ai_outbound'
                      check (kind in ('ai_outbound','human_followup')),
  started_at          timestamptz,
  ended_at            timestamptz,
  duration_sec        int,
  language_used       text,
  recording_r2_key    text,
  created_at          timestamptz not null default now()
);
create index calls_tenant_lead_idx on public.calls (tenant_id, lead_id);
create index calls_status_idx      on public.calls (status);
create table public.call_events (
  id           uuid primary key default uuid_generate_v4(),
  call_id      uuid not null references public.calls on delete cascade,
  event_id     text not null,
  kind         text not null,
  payload      jsonb not null,
  occurred_at  timestamptz not null default now(),
  unique (call_id, event_id)
);
create index call_events_call_idx on public.call_events (call_id);

create table public.transcripts (
  id         uuid primary key default uuid_generate_v4(),
  call_id    uuid not null references public.calls on delete cascade,
  speaker    text not null check (speaker in ('agent','lead')),
  text       text not null,
  lang       text,
  ts_ms      int not null,
  idx        int not null,
  unique (call_id, idx)
);
create index transcripts_call_idx_idx on public.transcripts (call_id, idx);

alter publication supabase_realtime add table public.transcripts;
alter publication supabase_realtime add table public.calls;
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
-- Helper: tenant_id from JWT claim
create or replace function public.current_tenant_id()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id','')::uuid
$$;

-- Enable RLS on every tenant-scoped table
do $$
declare t text;
begin
  foreach t in array array[
    'tenants','users','leads','campaigns','calls','call_events',
    'transcripts','lead_scores','handoffs','dnc_list'
  ] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- tenants: only own tenant
create policy tenant_self_read   on public.tenants for select
  using (id = public.current_tenant_id());
create policy tenant_self_update on public.tenants for update
  using (id = public.current_tenant_id());

-- users: visible only within same tenant
create policy users_same_tenant_read on public.users for select
  using (tenant_id = public.current_tenant_id());

-- Generic tenant-scoped policies for the rest
do $$
declare t text;
begin
  foreach t in array array[
    'leads','campaigns','calls','transcripts','lead_scores',
    'handoffs','dnc_list'
  ] loop
    execute format($f$
      create policy %1$I_tenant_read   on public.%1$I for select
        using (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_insert on public.%1$I for insert
        with check (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_update on public.%1$I for update
        using (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_delete on public.%1$I for delete
        using (tenant_id = public.current_tenant_id());
    $f$, t);
  end loop;
end $$;

-- call_events: scope through calls
create policy call_events_via_call_read on public.call_events for select
  using (exists (select 1 from public.calls c
                 where c.id = call_events.call_id
                   and c.tenant_id = public.current_tenant_id()));
create policy call_events_via_call_insert on public.call_events for insert
  with check (exists (select 1 from public.calls c
                      where c.id = call_events.call_id
                        and c.tenant_id = public.current_tenant_id()));
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
-- Per-turn latency telemetry. One row per agent turn so we can compute
-- p50/p95 over arbitrary windows without scanning call_events.payload.

create table public.turn_latencies (
  id                   uuid primary key default uuid_generate_v4(),
  call_id              uuid not null references public.calls on delete cascade,
  tenant_id            uuid not null references public.tenants on delete cascade,
  turn_idx             int not null,
  stt_final_ms         int,
  llm_first_token_ms   int,
  tts_first_chunk_ms   int,
  total_turn_ms        int not null,
  used_intro_cache     bool not null default false,
  occurred_at          timestamptz not null default now(),
  unique (call_id, turn_idx)
);

create index turn_latencies_tenant_time_idx
  on public.turn_latencies (tenant_id, occurred_at desc);

alter table public.turn_latencies enable row level security;

create policy turn_latencies_tenant_isolation
  on public.turn_latencies
  for select
  using (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

comment on table public.turn_latencies is
  'One row per agent turn. Used to prove sub-1s latency to clients and detect regressions.';
-- Pre-synthesized intro phrases per (lead, lang). Lets Pipecat skip
-- live TTS on the first turn, dropping the first-impression latency
-- from ~840ms to ~250ms (R2 TTFB).

create table public.lead_intro_audio (
  id              uuid primary key default uuid_generate_v4(),
  tenant_id       uuid not null references public.tenants on delete cascade,
  lead_id         uuid not null references public.leads on delete cascade,
  lang            text not null check (lang in ('en-IN','hi-IN','ta-IN')),
  r2_key          text not null,
  voice_id        text,
  text_hash       text not null,
  synthesized_at  timestamptz not null default now(),
  unique (lead_id, lang)
);
create index lead_intro_audio_lead_idx on public.lead_intro_audio (lead_id);

alter table public.lead_intro_audio enable row level security;
create policy lead_intro_audio_tenant_isolation
  on public.lead_intro_audio
  for select
  using (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid);

comment on table public.lead_intro_audio is
  'Pre-cached intro audio per (lead, lang). r2_key points to the .mp3 in R2 bucket intro-audio.';
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
-- Dual-unit billing: 0-180s = 1 unit, 181-360s = 2 units, hard cap 360s.
-- Computed at call end from duration_sec by a trigger.

alter table public.calls
  add column billed_units int not null default 0
    check (billed_units >= 0 and billed_units <= 2),
  add column estimated_cost_inr numeric(10,2) not null default 0
    check (estimated_cost_inr >= 0);

comment on column public.calls.billed_units is
  '0 for queued/failed/no_answer, 1 for 0-180s completed calls, 2 for 181-360s completed calls. Capped at 2 by 360s hard cap.';
comment on column public.calls.estimated_cost_inr is
  'Per-call cost estimate written by cost_guard.py at call end. Used for per-tenant daily-spend rollup.';

-- Compute billed_units from duration_sec when a call transitions to completed.
create or replace function public.compute_billed_units()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'completed' and new.duration_sec is not null then
    if new.duration_sec <= 180 then
      new.billed_units := 1;
    elsif new.duration_sec <= 360 then
      new.billed_units := 2;
    else
      -- Should never happen given the 360s hard cap, but cap defensively.
      new.billed_units := 2;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists calls_compute_billed_units on public.calls;
create trigger calls_compute_billed_units
  before insert or update of status, duration_sec on public.calls
  for each row execute function public.compute_billed_units();

-- Monthly rollup view used by the CRM quota indicator.
create or replace view public.tenant_monthly_units as
select
  tenant_id,
  date_trunc('month', coalesce(ended_at, started_at, created_at)) as month_start,
  sum(billed_units)::int as units_used,
  sum(estimated_cost_inr)::numeric(12,2) as cost_inr,
  count(*) filter (where status = 'completed')::int as completed_calls,
  count(*)::int as total_calls
from public.calls
group by tenant_id, date_trunc('month', coalesce(ended_at, started_at, created_at));

comment on view public.tenant_monthly_units is
  'Per-tenant per-month billing rollup. CRM "X / 2000 units used this month" reads from here.';
-- Tenant overage policy + daily spend cap (cost guardrail).

alter table public.tenants
  add column monthly_unit_allowance int not null default 2000
    check (monthly_unit_allowance > 0),
  add column overage_policy text not null default 'continue_billed'
    check (overage_policy in ('continue_billed','hard_pause')),
  add column overage_rate_inr numeric(6,2) not null default 10.00
    check (overage_rate_inr >= 0),
  add column wiggle_room_pct int not null default 10
    check (wiggle_room_pct >= 0 and wiggle_room_pct <= 50),
  add column daily_spend_cap_inr numeric(8,2) not null default 600.00
    check (daily_spend_cap_inr >= 0),
  add column avg_order_size_inr numeric(12,2) not null default 200000
    check (avg_order_size_inr >= 0);

comment on column public.tenants.monthly_unit_allowance is
  'Number of billed_units included in the monthly subscription. Default 2000.';
comment on column public.tenants.overage_policy is
  'continue_billed = keep calling past allowance and bill per-call; hard_pause = stop dispatching when allowance hit.';
comment on column public.tenants.overage_rate_inr is
  'Per-unit overage rate (applied only past wiggle_room). SPC: 10, clients #2+: 12.';
comment on column public.tenants.wiggle_room_pct is
  'Free overage allowance as percent of monthly_unit_allowance. 10% = 200 free bonus calls at 2000 allowance.';
comment on column public.tenants.daily_spend_cap_inr is
  'Cost-guard: dispatcher halts new calls if today projected variable cost would exceed this. Default ₹600/day.';
comment on column public.tenants.avg_order_size_inr is
  'Used by CRM Performance tab to compute ROI: Hot_leads * avg_order_size_inr.';

-- Today's spend rollup helper for the dispatcher daily-cap check.
create or replace function public.tenant_spend_today(p_tenant_id uuid)
returns numeric
language sql
stable
as $$
  select coalesce(sum(estimated_cost_inr), 0)::numeric
    from public.calls
   where tenant_id = p_tenant_id
     and coalesce(ended_at, started_at, created_at) >= date_trunc('day', now() at time zone 'Asia/Kolkata');
$$;

comment on function public.tenant_spend_today is
  'Sum of estimated_cost_inr for the tenant today (IST). Used by the dispatcher daily-cap check.';
