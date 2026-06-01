begin;
select plan(4);

insert into public.tenants (id, name, slug) values
  ('11111111-1111-1111-1111-111111111111','Alpha','alpha'),
  ('22222222-2222-2222-2222-222222222222','Beta','beta');

insert into auth.users (id, email) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','a@alpha.test'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb','b@beta.test');

insert into public.users (id, tenant_id, email, role) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','11111111-1111-1111-1111-111111111111','a@alpha.test','admin'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb','22222222-2222-2222-2222-222222222222','b@beta.test','admin');

insert into public.leads (tenant_id, name, phone_e164) values
  ('11111111-1111-1111-1111-111111111111','Alpha Lead','+919000000001'),
  ('22222222-2222-2222-2222-222222222222','Beta Lead','+919000000002');

select set_config('request.jwt.claims',
  '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","tenant_id":"11111111-1111-1111-1111-111111111111","role":"admin"}',
  true);
set role authenticated;
select is( (select count(*)::int from public.leads), 1, 'alpha admin sees only alpha leads');
select is( (select name from public.leads), 'Alpha Lead'::text, 'alpha admin sees alpha lead');
reset role;

select set_config('request.jwt.claims',
  '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","tenant_id":"22222222-2222-2222-2222-222222222222","role":"admin"}',
  true);
set role authenticated;
select is( (select count(*)::int from public.leads), 1, 'beta admin sees only beta leads');
select is( (select name from public.leads), 'Beta Lead'::text, 'beta admin sees beta lead');

select * from finish();
rollback;
