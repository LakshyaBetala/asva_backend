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
