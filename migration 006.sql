-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 006 — contact name for personal greetings
--  Run ONCE in Supabase SQL Editor on your EXISTING project.
-- ═══════════════════════════════════════════════════════════════════

alter table profiles
  add column if not exists contact_name text;
