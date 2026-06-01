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
