-- Align DB credit billing with the agent (pipeline.py billed_units: 4 tiers up to the 600s hard cap).
-- Fixes two bugs left by 20260526000000_credit_billing:
--   * calls_billed_units_check still capped billed_units at 2, so every >300s call was rejected;
--   * estimated_cost_inr was billed_units * avg_order_size_inr (₹2,00,000 ROI figure), so
--     tenant_spend_today() blew past the ₹600 daily cap after one call and dispatch halted.

alter table public.calls drop constraint if exists calls_billed_units_check;
alter table public.calls add constraint calls_billed_units_check check (billed_units between 0 and 4);

create or replace function public.compute_billed_units()
returns trigger
language plpgsql as $$
begin
  if new.status = 'completed' and new.duration_sec is not null then
    new.billed_units := case
      when new.duration_sec <= 150 then 1
      when new.duration_sec <= 300 then 2
      when new.duration_sec <= 450 then 3
      else 4
    end;
    -- cost_guard.py writes the measured cost; otherwise use dispatch.ts PROJECTED_UNIT_COST_INR (₹12/unit).
    if new.estimated_cost_inr = 0 then
      new.estimated_cost_inr := new.billed_units * 12.00;
    end if;
  end if;
  return new;
end $$;

comment on function public.compute_billed_units() is
  'Credit billing: 0-150s=1, 151-300s=2, 301-450s=3, 451-600s=4. Falls back to ₹12/unit cost.';

-- Repair rows written under the old avg_order_size_inr formula.
update public.calls c
   set estimated_cost_inr = c.billed_units * 12.00
  from public.tenants t
 where t.id = c.tenant_id
   and c.billed_units > 0
   and c.estimated_cost_inr = c.billed_units * t.avg_order_size_inr;
