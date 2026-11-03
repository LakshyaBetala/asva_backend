-- 0015 — per-lead call preferences for AI outbound
-- Lets the operator pick a language + voice gender per lead from the CRM,
-- overriding the tenant default. Used by StartAiCallButton.

alter table public.leads
  add column if not exists preferred_lang text
    check (preferred_lang in ('ta-IN', 'hi-IN', 'en-IN')),
  add column if not exists preferred_voice_gender text
    check (preferred_voice_gender in ('female', 'male'));

comment on column public.leads.preferred_lang is
  'CRM-set override for outbound language. NULL = use tenant default.';
comment on column public.leads.preferred_voice_gender is
  'CRM-set voice gender for AI agent (female=Priya, male=Pranav). NULL = female default.';
