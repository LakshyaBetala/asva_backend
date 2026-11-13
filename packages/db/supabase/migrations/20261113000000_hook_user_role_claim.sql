-- The hook wrote the app role (admin|rep) into the JWT "role" claim. PostgREST uses that claim
-- as the Postgres role to SET, so every logged-in query failed with: role "admin" does not exist.
-- Keep "role" = authenticated and expose the app role as "user_role" (nothing reads claims.role).
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
as $$
declare
  claims        jsonb;
  v_tenant_id   uuid;
  v_role        text;
begin
  claims := coalesce(event->'claims', '{}'::jsonb);

  select tenant_id, role into v_tenant_id, v_role
  from public.users
  where id = (event->>'user_id')::uuid;

  if v_tenant_id is not null then
    claims := jsonb_set(claims, '{tenant_id}', to_jsonb(v_tenant_id::text));
    claims := jsonb_set(claims, '{user_role}', to_jsonb(v_role));
  end if;

  event := jsonb_set(event, '{claims}', claims);
  return event;
end;
$$;
