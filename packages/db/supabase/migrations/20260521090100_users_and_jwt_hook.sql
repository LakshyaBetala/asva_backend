-- users: app-level profile pinned to auth.users
create table public.users (
  id          uuid primary key references auth.users on delete cascade,
  tenant_id   uuid not null references public.tenants on delete restrict,
  email       text not null,
  full_name   text,
  role        text not null check (role in ('admin','rep')),
  whatsapp    text,
  created_at  timestamptz not null default now()
);

create index users_tenant_idx on public.users (tenant_id);

-- JWT custom-claims hook: injects tenant_id + role into the access token.
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
    claims := jsonb_set(claims, '{role}',      to_jsonb(v_role));
  end if;

  event := jsonb_set(event, '{claims}', claims);
  return event;
end;
$$;

grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
