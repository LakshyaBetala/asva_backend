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
