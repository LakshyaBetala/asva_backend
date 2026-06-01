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
