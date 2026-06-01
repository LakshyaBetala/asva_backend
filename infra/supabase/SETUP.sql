-- =============================================================================
-- AI Voice Agent — single-shot Supabase setup file.
-- Project: rcbvdxyehtwhzgajzdlj
--
-- HOW TO RUN
-- ----------
-- 1. Open Supabase SQL Editor:
--    https://supabase.com/dashboard/project/rcbvdxyehtwhzgajzdlj/sql/new
-- 2. Paste BLOCK 1 (the SCHEMA block below), click Run, wait for "Success".
-- 3. Paste BLOCK 2 (the SEED block). Replace the email if yours is different.
--    It returns a tenant_id — copy it.
-- 4. Go to Authentication → Users → Add user, create your login email + password.
-- 5. Paste BLOCK 3 (the USER LINK block). Replace __TENANT_UUID__ with the value
--    from step 3 and the email if different. Run.
-- 6. Enable the JWT hook:
--    https://supabase.com/dashboard/project/rcbvdxyehtwhzgajzdlj/auth/hooks
--    Add hook → "Custom Access Token" → public.custom_access_token_hook → Save.
--
-- Total time: ~5 minutes.
-- =============================================================================


-- =============================================================================
-- BLOCK 0 — RESET (run ONLY if a previous BLOCK 1 attempt partially applied)
-- Safe even on a fresh project — it's all "if exists" drops.
-- =============================================================================

drop view  if exists public.tenant_monthly_units cascade;

drop function if exists public.tenant_spend_today(uuid)        cascade;
drop function if exists public.compute_billed_units()           cascade;
drop function if exists public.current_tenant_id()              cascade;
drop function if exists public.custom_access_token_hook(jsonb)  cascade;

drop table if exists public.qualification_slots cascade;
drop table if exists public.lead_intro_audio    cascade;
drop table if exists public.turn_latencies      cascade;
drop table if exists public.dnc_list            cascade;
drop table if exists public.handoffs            cascade;
drop table if exists public.lead_scores         cascade;
drop table if exists public.transcripts         cascade;
drop table if exists public.call_events         cascade;
drop table if exists public.calls               cascade;
drop table if exists public.campaigns           cascade;
drop table if exists public.leads               cascade;
drop table if exists public.users               cascade;
drop table if exists public.tenants             cascade;


-- =============================================================================
-- BLOCK 1 — SCHEMA (13 migrations folded into one paste)
-- =============================================================================

create extension if not exists "uuid-ossp";

-- ── tenants ─────────────────────────────────────────────────────────────────
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


-- ── users + JWT custom-claims hook ──────────────────────────────────────────
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

create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb language plpgsql stable as $$
declare claims jsonb; v_tenant_id uuid; v_role text;
begin
  claims := coalesce(event->'claims', '{}'::jsonb);
  select tenant_id, role into v_tenant_id, v_role
    from public.users where id = (event->>'user_id')::uuid;
  if v_tenant_id is not null then
    claims := jsonb_set(claims, '{tenant_id}', to_jsonb(v_tenant_id::text));
    claims := jsonb_set(claims, '{role}',      to_jsonb(v_role));
  end if;
  event := jsonb_set(event, '{claims}', claims);
  return event;
end; $$;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;


-- ── leads ───────────────────────────────────────────────────────────────────
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


-- ── campaigns + calls ───────────────────────────────────────────────────────
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


-- ── call_events + transcripts ──────────────────────────────────────────────
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


-- ── lead_scores + handoffs + dnc_list ──────────────────────────────────────
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


-- ── RLS policies (multi-tenant isolation) ──────────────────────────────────
create or replace function public.current_tenant_id()
returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id','')::uuid
$$;

do $$ declare t text; begin
  foreach t in array array['tenants','users','leads','campaigns','calls','call_events',
                           'transcripts','lead_scores','handoffs','dnc_list'] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

create policy tenant_self_read   on public.tenants for select using (id = public.current_tenant_id());
create policy tenant_self_update on public.tenants for update using (id = public.current_tenant_id());
create policy users_same_tenant_read on public.users for select using (tenant_id = public.current_tenant_id());

-- Tables that have tenant_id directly:
do $$ declare t text; begin
  foreach t in array array['leads','campaigns','calls','dnc_list'] loop
    execute format($f$
      create policy %1$I_tenant_read   on public.%1$I for select using (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_insert on public.%1$I for insert with check (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_update on public.%1$I for update using (tenant_id = public.current_tenant_id());
      create policy %1$I_tenant_delete on public.%1$I for delete using (tenant_id = public.current_tenant_id());
    $f$, t);
  end loop;
end $$;

-- call_events scopes through calls.
create policy call_events_via_call_read on public.call_events for select
  using (exists (select 1 from public.calls c
                 where c.id = call_events.call_id and c.tenant_id = public.current_tenant_id()));
create policy call_events_via_call_insert on public.call_events for insert
  with check (exists (select 1 from public.calls c
                      where c.id = call_events.call_id and c.tenant_id = public.current_tenant_id()));

-- transcripts scopes through calls.
create policy transcripts_via_call_read on public.transcripts for select
  using (exists (select 1 from public.calls c
                 where c.id = transcripts.call_id and c.tenant_id = public.current_tenant_id()));
create policy transcripts_via_call_insert on public.transcripts for insert
  with check (exists (select 1 from public.calls c
                      where c.id = transcripts.call_id and c.tenant_id = public.current_tenant_id()));

-- lead_scores scopes through calls.
create policy lead_scores_via_call_read on public.lead_scores for select
  using (exists (select 1 from public.calls c
                 where c.id = lead_scores.call_id and c.tenant_id = public.current_tenant_id()));
create policy lead_scores_via_call_insert on public.lead_scores for insert
  with check (exists (select 1 from public.calls c
                      where c.id = lead_scores.call_id and c.tenant_id = public.current_tenant_id()));
create policy lead_scores_via_call_update on public.lead_scores for update
  using (exists (select 1 from public.calls c
                 where c.id = lead_scores.call_id and c.tenant_id = public.current_tenant_id()));

-- handoffs scopes through leads.
create policy handoffs_via_lead_read on public.handoffs for select
  using (exists (select 1 from public.leads l
                 where l.id = handoffs.lead_id and l.tenant_id = public.current_tenant_id()));
create policy handoffs_via_lead_insert on public.handoffs for insert
  with check (exists (select 1 from public.leads l
                      where l.id = handoffs.lead_id and l.tenant_id = public.current_tenant_id()));
create policy handoffs_via_lead_update on public.handoffs for update
  using (exists (select 1 from public.leads l
                 where l.id = handoffs.lead_id and l.tenant_id = public.current_tenant_id()));


-- ── Agent toggle + BYON (Bring Your Own Number) ────────────────────────────
alter table public.tenants
  add column agent_enabled bool not null default true,
  add column telephony_mode text not null default 'managed'
    check (telephony_mode in ('managed','byon')),
  add column byon_provider text check (byon_provider in ('exotel','plivo','tata')),
  add column byon_from_number text,
  add column byon_credentials_ref uuid;


-- ── turn_latencies (per-turn telemetry) ────────────────────────────────────
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
create policy turn_latencies_tenant_read on public.turn_latencies for select
  using (tenant_id = public.current_tenant_id());
create policy turn_latencies_tenant_insert on public.turn_latencies for insert
  with check (tenant_id = public.current_tenant_id());


-- ── lead_intro_audio (R2-cached first-turn audio) ──────────────────────────
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
create policy lead_intro_audio_tenant_read on public.lead_intro_audio for select
  using (tenant_id = public.current_tenant_id());
create policy lead_intro_audio_tenant_insert on public.lead_intro_audio for insert
  with check (tenant_id = public.current_tenant_id());
create policy lead_intro_audio_tenant_update on public.lead_intro_audio for update
  using (tenant_id = public.current_tenant_id());


-- ── qualification_slots (CP3 — live 8-slot extraction) ─────────────────────
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
  slot_confidence     jsonb not null default '{}'::jsonb,
  last_turn_idx       int not null default 0,
  updated_at          timestamptz not null default now()
);
create index qualification_slots_tenant_lead_idx
  on public.qualification_slots (tenant_id, lead_id);
alter table public.qualification_slots enable row level security;
create policy qualification_slots_tenant_read   on public.qualification_slots for select
  using (tenant_id = public.current_tenant_id());
create policy qualification_slots_tenant_insert on public.qualification_slots for insert
  with check (tenant_id = public.current_tenant_id());
create policy qualification_slots_tenant_update on public.qualification_slots for update
  using (tenant_id = public.current_tenant_id());


-- ── Dual-unit billing (CP3 — 180s=1 unit, 181-360s=2 units) ────────────────
alter table public.calls
  add column billed_units int not null default 0
    check (billed_units >= 0 and billed_units <= 2),
  add column estimated_cost_inr numeric(10,2) not null default 0
    check (estimated_cost_inr >= 0);

create or replace function public.compute_billed_units()
returns trigger language plpgsql as $$
begin
  if new.status = 'completed' and new.duration_sec is not null then
    if new.duration_sec <= 180 then new.billed_units := 1;
    elsif new.duration_sec <= 360 then new.billed_units := 2;
    else new.billed_units := 2;  -- defensive: 360s hard cap should prevent this
    end if;
  end if;
  return new;
end; $$;

drop trigger if exists calls_compute_billed_units on public.calls;
create trigger calls_compute_billed_units
  before insert or update of status, duration_sec on public.calls
  for each row execute function public.compute_billed_units();

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


-- ── Tenant overage policy + daily spend cap (CP3) ──────────────────────────
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

create or replace function public.tenant_spend_today(p_tenant_id uuid)
returns numeric language sql stable as $$
  select coalesce(sum(estimated_cost_inr), 0)::numeric
    from public.calls
   where tenant_id = p_tenant_id
     and coalesce(ended_at, started_at, created_at) >= date_trunc('day', now() at time zone 'Asia/Kolkata');
$$;


-- ── Lead-source configuration (migration 0014) ─────────────────────────────
alter table public.tenants
  add column lead_industries     text[] not null default '{}',
  add column lead_locations      text[] not null default '{}',
  add column ingest_api_key      text,
  add column places_sync_enabled bool   not null default false;

create unique index tenants_ingest_api_key_uidx
  on public.tenants (ingest_api_key)
  where ingest_api_key is not null;


-- =============================================================================
-- BLOCK 2 — SEED: create your tenant
-- Run AFTER block 1 succeeds. Copy the returned UUID — you'll need it.
-- =============================================================================

-- insert into public.tenants (name, slug, persona_lang_default)
-- values ('Supreme Petrochemicals', 'spc', 'hi-IN')
-- returning id;


-- =============================================================================
-- BLOCK 3 — SEED: link your auth user to the tenant
-- Steps before running:
--   (a) Run Block 1, then Block 2 and copy the tenant UUID.
--   (b) Go to Authentication → Users → Add user, create with your email.
-- Then replace __TENANT_UUID__ below and run.
-- =============================================================================

-- insert into public.users (id, tenant_id, email, role)
-- values (
--   (select id from auth.users where email = 'almmatix@gmail.com'),
--   '__TENANT_UUID__',
--   'almmatix@gmail.com',
--   'admin'
-- );


-- =============================================================================
-- BLOCK 4 — JWT HOOK (done in dashboard, NOT SQL)
-- Go to:
--   https://supabase.com/dashboard/project/rcbvdxyehtwhzgajzdlj/auth/hooks
-- Click "Add hook" → choose "Custom Access Token (JWT)"
-- Pick:        public.custom_access_token_hook
-- Click Save.
-- =============================================================================
