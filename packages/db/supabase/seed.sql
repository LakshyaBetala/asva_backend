-- Seed SPC as tenant #1
insert into public.tenants (id, name, slug, persona_name, persona_lang_default,
                            exotel_caller_id, whatsapp_handoff_number)
values ('00000000-0000-0000-0000-0000000000c1',
        'Supreme Petrochemicals', 'spc', 'Priya', 'en-IN',
        '+914440000000', '+919000000000')
on conflict (slug) do nothing;

-- Demo admin user. Password = 'demo-password-change-me'. Change after first login.
insert into auth.users (id, email, encrypted_password, email_confirmed_at, role,
                        aud, instance_id)
values ('00000000-0000-0000-0000-0000000000a1',
        'admin@spc.test',
        crypt('demo-password-change-me', gen_salt('bf')),
        now(),
        'authenticated',
        'authenticated',
        '00000000-0000-0000-0000-000000000000')
on conflict (id) do nothing;

insert into public.users (id, tenant_id, email, full_name, role, whatsapp)
values ('00000000-0000-0000-0000-0000000000a1',
        '00000000-0000-0000-0000-0000000000c1',
        'admin@spc.test', 'SPC Admin', 'admin', '+919000000000')
on conflict (id) do nothing;
