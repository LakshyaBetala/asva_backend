-- Update billing from 180s dual-unit to 150s triple-credit system.
--
-- Credit tiers:
--   0-150s  = 1 credit
--   150-300s = 2 credits
--   300-450s = 3 credits (hard cap)

-- Update the trigger function that computes billed_units on call completion.
create or replace function public.compute_billed_units()
returns trigger
language plpgsql as $$
begin
  if new.status = 'completed' and new.duration_sec is not null then
    if new.duration_sec <= 150 then
      new.billed_units := 1;
    elsif new.duration_sec <= 300 then
      new.billed_units := 2;
    else
      new.billed_units := 3;
    end if;
    new.estimated_cost_inr :=
      new.billed_units * coalesce(
        (select avg_order_size_inr from public.tenants where id = new.tenant_id),
        5.00
      );
  end if;
  return new;
end $$;

comment on function public.compute_billed_units() is
  'Credit billing: 0-150s=1, 150-300s=2, 300-450s=3 (capped). Triggers on calls INSERT/UPDATE.';
