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

create policy turn_latencies_tenant_read on public.turn_latencies
  for select using (tenant_id = public.current_tenant_id());
create policy turn_latencies_tenant_insert on public.turn_latencies
  for insert with check (tenant_id = public.current_tenant_id());

comment on table public.turn_latencies is
  'One row per agent turn. Used to prove sub-1s latency to clients and detect regressions.';
