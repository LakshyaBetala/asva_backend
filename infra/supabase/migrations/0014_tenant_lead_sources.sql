-- =============================================================================
-- 0014 — Tenant lead-source configuration
--
-- Adds per-tenant config for automated lead acquisition:
--   * lead_industries     — search terms for source adapters (e.g. Google Places)
--   * lead_locations      — city/region names paired against industries
--   * ingest_api_key      — bearer token for the generic /api/leads/ingest webhook
--   * places_sync_enabled — toggle for the Google Places cron job
--
-- Run AFTER block 1 of SETUP.sql. Idempotent.
-- =============================================================================

alter table public.tenants
  add column if not exists lead_industries     text[] not null default '{}',
  add column if not exists lead_locations      text[] not null default '{}',
  add column if not exists ingest_api_key      text,
  add column if not exists places_sync_enabled bool   not null default false;

create unique index if not exists tenants_ingest_api_key_uidx
  on public.tenants (ingest_api_key)
  where ingest_api_key is not null;

-- Seed sensible defaults for the SPC tenant (Tamil Nadu petrochemicals).
update public.tenants
   set lead_industries = coalesce(nullif(lead_industries, '{}'), array[
         'plastic manufacturer',
         'polymer trader',
         'packaging company',
         'PVC pipe manufacturer',
         'paint manufacturer',
         'chemical distributor'
       ]),
       lead_locations = coalesce(nullif(lead_locations, '{}'), array[
         'Chennai', 'Coimbatore', 'Tiruppur', 'Madurai', 'Salem', 'Bangalore'
       ])
 where slug = 'spc';
