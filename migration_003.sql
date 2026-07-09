-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 003 — contractor verification
--  Run ONCE in Supabase SQL Editor on your EXISTING project.
--  (Fresh installs skip this — schema.sql already includes it.)
--
--  Existing accounts become 'unverified' and will be prompted to
--  verify on their next login. To manually approve anyone (including
--  your own test accounts): Table Editor -> profiles -> set
--  verification_status to 'verified'.
-- ═══════════════════════════════════════════════════════════════════

alter table profiles
  add column if not exists verification_status text not null default 'unverified',
  add column if not exists verified_at   timestamptz,
  add column if not exists cslb_status   text,   -- raw status line from CSLB
  add column if not exists cslb_expires  text,   -- license expiration
  add column if not exists cslb_business text;   -- business name on the license

alter table profiles drop constraint if exists profiles_verification_status_check;
alter table profiles add constraint profiles_verification_status_check
  check (verification_status in ('unverified','pending','verified','rejected'));
