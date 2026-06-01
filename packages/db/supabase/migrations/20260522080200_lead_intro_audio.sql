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
create policy lead_intro_audio_tenant_read on public.lead_intro_audio
  for select using (tenant_id = public.current_tenant_id());
create policy lead_intro_audio_tenant_insert on public.lead_intro_audio
  for insert with check (tenant_id = public.current_tenant_id());
create policy lead_intro_audio_tenant_update on public.lead_intro_audio
  for update using (tenant_id = public.current_tenant_id());

comment on table public.lead_intro_audio is
  'Pre-cached intro audio per (lead, lang). r2_key points to the .mp3 in R2 bucket intro-audio.';
