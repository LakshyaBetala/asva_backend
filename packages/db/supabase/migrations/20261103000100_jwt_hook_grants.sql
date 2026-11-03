-- custom_access_token_hook runs as supabase_auth_admin. Without these grants + policy it cannot
-- read public.users under RLS, so tenant_id is never injected and every tenant sees zero rows.
grant usage on schema public to supabase_auth_admin;
grant select on public.users to supabase_auth_admin;

drop policy if exists users_auth_admin_read on public.users;
create policy users_auth_admin_read on public.users
  for select to supabase_auth_admin using (true);

revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;
