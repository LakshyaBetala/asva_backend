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
